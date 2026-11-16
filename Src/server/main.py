"""로컬 서버 (FastAPI). 화면은 ws://localhost:8000/ws 하나로만 주고받는다 (ui/src/protocol.ts).

실행 (Src 폴더에서):  uvicorn server.main:app --port 8000

화면 → 엔진
- session.start {show_id, cue_file, cue_csv?, input?} : 큐를 읽고 시작.
      input = file(녹음 파일 재생) / mic(마이크) / text(대사 입력 테스트) / browser(브라우저가 보낸 소리).
      없으면 .env 의 HELPER_INPUT. 큐는 cue_csv(화면이 보낸 큐 파일 내용)가 있으면 그것을, 없으면
      cue_file 이름을 HELPER_DATA_DIR 에서 찾는다 (녹음 재생은 큐 파일 옆 녹음을 틀어야 해서 항상 폴더에서)
- (바이너리)                         : browser 회차에서 브라우저가 보낸 소리 (16kHz 모노 PCM16 조각)
- session.end   {show_id}           : 멈춤
- test.say {text}                   : 대사 입력 테스트 회차에서, 친 글자를 음성인식 결과 한 번으로 보고 추적
- subtitle.send {text, source}      : 애드리브 임시 자막 송출. 송출 프로그램 연동 전이라 회차 기록 · 로그에만 남김
- cue.send {cue_id, grouped_ids?}   : 대본 큐 송출 (오퍼레이터가 확인하고 누름). 연동 전이라 기록만
- position.set {cue_id}             : 오퍼레이터 위치 맞추기 (추적 위치를 이 큐로, 이탈 판단도 여기서 다시)
GET /session/audio : 진행 중인 녹음 재생 회차의 녹음 파일 (화면이 같은 녹음을 틀어 들으면서 볼 때)
- settings.update {alert_threshold} : 지금은 기록만
엔진 → 화면: position.update / deviation.alert / input.status / engine.error (회차를 못 엶 · 음성인식이 계속 실패 · 시간 제한)
회차마다 인식 글자 · 추적 위치 · 알림을 HELPER_LOG_DIR(기본 Src/logs)에 JSONL 로 남긴다 (engine/session_log.py)

인터넷에 올릴 때 (Src/DEPLOY.md)
- HELPER_INPUTS=browser,text       : 서버 마이크 · 서버 녹음은 막고 브라우저 소리와 대사 입력만
- HELPER_ACCESS_CODE=...           : 화면이 ws://.../ws?code=... 로 붙어야 함 (틀리면 4401 로 닫음)
- HELPER_MAX_SESSION_SEC=600       : 한 회차를 이 시간이 지나면 멈춤 (음성인식 요금 보호)
- HELPER_MAX_SESSIONS=3            : 동시에 도는 회차 수
- HELPER_LOG_DIR=off               : 회차 기록을 남기지 않음
"""
import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from engine.aligner import parse_settings
from engine.audio_input import MicSource, PushSource, TextSource, load_wav
from engine.config import SRC, env, env_float, env_path
from engine.cue_loader import load_cues, parse_cues
from engine.pipeline import Pipeline, TypedInput
from engine.protocol import engine_error
from engine.session_log import SessionLog
from engine.stt import STTEngine, make_engine
from engine.vad import VADGate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("helper.server")

_engines: dict[str, STTEngine] = {}
_audio_file: Path | None = None   # 진행 중인 녹음 재생 회차의 녹음 (GET /session/audio)
_live: set[Pipeline] = set()      # 지금 돌고 있는 회차 (HELPER_MAX_SESSIONS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버를 켤 때 음성인식 모델을 미리 불러 둔다 (첫 회차가 몇 초 늦게 시작하지 않게)
    name = env("HELPER_STT", "whisper")
    if env("HELPER_PRELOAD", "1") == "0":
        yield
        return
    try:
        await asyncio.get_running_loop().run_in_executor(None, get_engine, name)
        log.info("음성인식 준비됨: %s", name)
    except Exception as ex:
        log.error("음성인식 준비 실패 (%s): %s — 회차 시작 때 다시 시도", name, ex)
    yield


app = FastAPI(title="Helper engine", lifespan=lifespan)


def get_engine(name: str) -> STTEngine:
    """음성인식 엔진은 한 번만 준비한다 (모델 불러오기가 몇 초 걸림)."""
    if name not in _engines:
        eng = make_engine(name)
        eng.check()
        eng.setup()
        _engines[name] = eng
    return _engines[name]


def find_cue_file(name: str) -> Path:
    """화면은 파일 이름만 보낸다 → 데이터 폴더 · 샘플 폴더에서 같은 이름을 찾는다."""
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    roots = [r for r in (env_path("HELPER_DATA_DIR"), SRC / "ui" / "mock") if r and r.exists()]
    for root in roots:
        hit = next(iter(sorted(root.rglob(p.name))), None)
        if hit:
            return hit
    raise FileNotFoundError(f"큐 파일 '{name}' 를 찾을 수 없음 (HELPER_DATA_DIR={env('HELPER_DATA_DIR')})")


def find_audio_file(cue_path: Path) -> Path:
    p = env_path("HELPER_AUDIO_FILE")
    if p:
        return p
    wavs = sorted(cue_path.parent.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"녹음 파일이 없음: HELPER_AUDIO_FILE 을 정하거나 {cue_path.parent} 에 .wav 를 두세요")
    return wavs[0]


INPUT_MODES = ("file", "mic", "text", "browser")
CUE_CSV_MAX = 2_000_000   # 화면이 보낸 큐 파일 내용의 최대 글자 수


def allowed_inputs() -> tuple[str, ...]:
    """쓸 수 있는 소리 입력. HELPER_INPUTS(쉼표로 나열)로 줄인다. 비우면 전부."""
    raw = env("HELPER_INPUTS")
    return tuple(m.strip() for m in raw.split(",") if m.strip()) if raw else INPUT_MODES


def read_cues(msg: dict, mode: str):
    """(큐 목록, 큐 파일 경로 또는 None, 기록용 이름). 화면이 보낸 내용이 있으면 그것을 쓴다."""
    text = msg.get("cue_csv")
    if text and mode != "file":
        if len(text) > CUE_CSV_MAX:
            raise ValueError("큐 파일이 너무 큽니다")
        return parse_cues(text), None, str(msg.get("cue_file") or "화면에서 보낸 큐")
    path = find_cue_file(msg.get("cue_file", ""))
    return load_cues(path), path, path.name


def start_session(msg: dict, emit) -> Pipeline:
    global _audio_file
    mode = msg.get("input") or env("HELPER_INPUT", "file")   # 화면에서 고른 소리 입력이 먼저
    if mode not in INPUT_MODES:
        raise ValueError(f"모르는 소리 입력: {mode} ({' / '.join(INPUT_MODES)})")
    if mode not in allowed_inputs():
        raise ValueError(f"이 서버에서는 '{mode}' 입력을 쓸 수 없습니다 ({' / '.join(allowed_inputs())})")
    cues, cue_path, cue_name = read_cues(msg, mode)
    if mode == "text":        # 대사 입력 테스트: 소리 · 음성인식 없이 화면이 보낸 글자를 쓴다
        stt, audio, src, speed = TypedInput(), TextSource(), "대사 입력", 1.0
    else:
        stt = get_engine(env("HELPER_STT", "whisper"))
        if env("HELPER_VAD", "0") == "1" and stt.mode == "chunk":
            stt = VADGate(stt)    # 조용하고 말소리도 없는 조각은 음성인식에 보내지 않음
    if mode == "mic":
        audio = MicSource(env("HELPER_MIC_DEVICE") or None)
        audio.open()          # 장치 문제를 여기서 바로 알림
        src, speed = f"마이크 {audio.name} ({audio.rate}Hz)", 1.0
    elif mode == "browser":   # 소리는 WebSocket 바이너리로 들어온다 (ws_endpoint)
        audio, src, speed = PushSource(), "브라우저 소리", 1.0
    elif mode == "file":
        audio_path = find_audio_file(cue_path)
        audio, src = load_wav(audio_path), f"녹음 {audio_path.name}"
        speed = env_float("HELPER_SPEED", 1.0)
    _audio_file = audio_path if mode == "file" else None
    align = parse_settings(env("HELPER_ALIGN"))
    log.info("큐 %s, %s, 음성인식 %s%s", cue_name, src, stt.label, f", 추적기 {align}" if align else "")
    pipe = Pipeline(cues, audio, stt, emit,
                    hints=env("HELPER_HINTS", "1") != "0",
                    chunk_sec=env_float("HELPER_CHUNK_SEC", 3.0),
                    hop_sec=env_float("HELPER_HOP_SEC", 0.0) or None,
                    deviate_after=env_float("DEVIATE_AFTER_SEC", 3.0),
                    speed=speed, aligner_kw=align)
    record = open_session_log(str(msg.get("show_id") or ""))
    if record:
        pipe.record = record
        record("start", show_id=msg.get("show_id"), cue_file=cue_name, input=mode, source=src,
               stt=stt.label, hints=pipe.hints, chunk_sec=pipe.chunk_sec, hop_sec=pipe.hop_sec, workers=pipe.workers,
               align=align, cues=len(pipe.aligner.items))
        log.info("회차 기록: %s", record.path)
    pipe.start()
    return pipe


def open_session_log(show_id: str) -> SessionLog | None:
    """HELPER_LOG_DIR(비우면 Src/logs)에 회차 기록을 연다. off 면 남기지 않음."""
    if env("HELPER_LOG_DIR").lower() == "off":
        return None
    return SessionLog.open_in(env_path("HELPER_LOG_DIR") or SRC / "logs", show_id)


@app.get("/session/audio")
def session_audio():
    """녹음 재생 회차의 녹음 파일. 화면이 같은 녹음을 엔진 재생 위치(input.status 의 audio_sec)에 맞춰 튼다."""
    if _audio_file is None or not _audio_file.exists():
        raise HTTPException(404, "녹음 재생 회차가 아님")
    return FileResponse(_audio_file, media_type="audio/wav")


@app.get("/health")
def health():
    return {"ok": True, "stt": env("HELPER_STT", "whisper"), "inputs": list(allowed_inputs())}


def minutes(sec: float) -> str:
    return f"{sec / 60:g}분" if sec >= 60 else f"{sec:g}초"


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    code = env("HELPER_ACCESS_CODE")
    if code and not hmac.compare_digest(ws.query_params.get("code", ""), code):
        log.warning("접속 코드가 맞지 않아 연결을 닫음")
        await ws.close(code=4401, reason="access code")
        return
    log.info("화면 연결됨")
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    limit_sec = env_float("HELPER_MAX_SESSION_SEC", 0.0)
    max_sessions = int(env("HELPER_MAX_SESSIONS") or 0)

    def emit(msg: dict):   # 엔진 스레드에서 부르므로 이벤트 루프로 넘긴다
        loop.call_soon_threadsafe(out.put_nowait, msg)

    async def sender():
        while True:
            await ws.send_text(json.dumps(await out.get(), ensure_ascii=False))

    send_task = asyncio.create_task(sender())
    pipe: Pipeline | None = None
    limit_task: asyncio.Task | None = None

    def stop_pipe():
        nonlocal pipe, limit_task
        if pipe:
            pipe.stop()
            _live.discard(pipe)
        pipe = None
        if limit_task:
            limit_task.cancel()
            limit_task = None

    async def time_limit(p: Pipeline):
        await asyncio.sleep(limit_sec)
        if pipe is p:
            log.info("회차 시간 제한(%s)으로 멈춤", minutes(limit_sec))
            stop_pipe()
            emit(engine_error(f"한 회차는 {minutes(limit_sec)}까지 쓸 수 있어 멈췄습니다. 시작 화면에서 다시 시작하세요",
                              "limit"))

    try:
        while True:
            data = await ws.receive()
            if data["type"] == "websocket.disconnect":
                break
            if data.get("bytes") is not None:      # 브라우저 소리
                if pipe and isinstance(pipe.source, PushSource):
                    pipe.source.feed(data["bytes"])
                continue
            try:
                msg = json.loads(data.get("text") or "")
            except json.JSONDecodeError:
                log.warning("JSON 이 아닌 메시지 무시")
                continue
            kind = msg.get("type")
            if kind == "session.start":
                stop_pipe()
                if max_sessions and len(_live) >= max_sessions:
                    emit(engine_error(f"지금 다른 사람이 쓰고 있습니다 (동시에 {max_sessions}회차까지). "
                                      "잠시 뒤 다시 시작하세요", "session.start"))
                    continue
                try:
                    pipe = await loop.run_in_executor(None, start_session, msg, emit)
                except Exception as ex:   # 키 없음 · 파일 없음 · 마이크 오류 등: 서버 로그와 화면에 알린다
                    log.error("회차 시작 실패: %s", ex)
                    emit(engine_error(str(ex), "session.start"))   # 원인만. '회차를 못 엶'은 화면이 붙인다
                    pipe = None
                    continue
                _live.add(pipe)
                if limit_sec > 0:
                    limit_task = asyncio.create_task(time_limit(pipe))
            elif kind == "session.end":
                stop_pipe()
                log.info("회차 종료: %s", msg.get("show_id"))
            elif kind == "test.say":
                if not pipe:
                    log.warning("test.say: 진행 중인 회차가 없음")
                else:
                    try:
                        pipe.say(str(msg.get("text") or ""))
                    except ValueError as ex:   # 녹음 · 마이크 회차에 온 대사 입력
                        log.warning("test.say 무시: %s", ex)
            elif kind == "position.set":
                try:
                    cue_id = int(msg.get("cue_id"))
                except (TypeError, ValueError):
                    log.warning("position.set: cue_id 가 숫자가 아님: %s", msg)
                    continue
                if not pipe or not pipe.jump_to(cue_id):
                    log.warning("position.set 무시: 회차가 없거나 모르는 큐 #%s", cue_id)
            elif kind == "subtitle.send":
                # 애드리브 임시 자막: 송출 프로그램 연동(2단계) 전이라 기록만 남긴다
                log.info("임시 자막 송출 (%s): %s", msg.get("source"), msg.get("text"))
                if pipe:
                    pipe.record("subtitle", text=msg.get("text"), source=msg.get("source"))
            elif kind == "cue.send":
                # 대본 큐 송출: 오퍼레이터가 확인하고 누른 것. 송출 프로그램 연동 전이라 기록만 남긴다
                log.info("큐 송출: #%s %s", msg.get("cue_id"), msg.get("grouped_ids") or "")
                if pipe:
                    pipe.record("send", cue=msg.get("cue_id"), grouped=msg.get("grouped_ids"))
            elif kind == "settings.update":
                log.info("설정 변경: %s", msg)
                if pipe:
                    pipe.record("settings", **{k: v for k, v in msg.items() if k != "type"})
            else:
                log.warning("모르는 메시지: %s", msg)
    except WebSocketDisconnect:
        pass
    finally:
        log.info("화면 연결 끊김")
        stop_pipe()
        send_task.cancel()
