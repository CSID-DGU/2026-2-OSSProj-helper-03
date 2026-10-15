"""로컬 서버 (FastAPI). 화면은 ws://localhost:8000/ws 하나로만 주고받는다 (ui/src/protocol.ts).

실행 (Src 폴더에서):  uvicorn server.main:app --port 8000

화면 → 엔진
- session.start {show_id, cue_file} : cue_file 이름을 HELPER_DATA_DIR 에서 찾아 큐를 읽고, 녹음 파일 재생 시작
- session.end   {show_id}           : 멈춤
- settings.update {alert_threshold} : 지금은 기록만
엔진 → 화면: position.update / deviation.alert / input.status
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from engine.audio_input import load_wav
from engine.config import SRC, env, env_float, env_path
from engine.cue_loader import load_cues
from engine.pipeline import Pipeline
from engine.stt import STTEngine, make_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("helper.server")

_engines: dict[str, STTEngine] = {}


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


def start_session(msg: dict, emit) -> Pipeline:
    cue_path = find_cue_file(msg.get("cue_file", ""))
    audio_path = find_audio_file(cue_path)
    stt = get_engine(env("HELPER_STT", "whisper"))
    log.info("큐 %s, 녹음 %s, 음성인식 %s", cue_path.name, audio_path.name, stt.label)
    pipe = Pipeline(load_cues(cue_path), load_wav(audio_path), stt, emit,
                    hints=env("HELPER_HINTS", "1") != "0",
                    chunk_sec=env_float("HELPER_CHUNK_SEC", 3.0),
                    hop_sec=env_float("HELPER_HOP_SEC", 0.0) or None,
                    deviate_after=env_float("DEVIATE_AFTER_SEC", 6.0),
                    speed=env_float("HELPER_SPEED", 1.0))
    pipe.start()
    return pipe


@app.get("/health")
def health():
    return {"ok": True, "stt": env("HELPER_STT", "whisper")}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    log.info("화면 연결됨")
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()

    def emit(msg: dict):   # 엔진 스레드에서 부르므로 이벤트 루프로 넘긴다
        loop.call_soon_threadsafe(out.put_nowait, msg)

    async def sender():
        while True:
            await ws.send_text(json.dumps(await out.get(), ensure_ascii=False))

    send_task = asyncio.create_task(sender())
    pipe: Pipeline | None = None
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                log.warning("JSON 이 아닌 메시지 무시")
                continue
            kind = msg.get("type")
            if kind == "session.start":
                if pipe:
                    pipe.stop()
                try:
                    pipe = await loop.run_in_executor(None, start_session, msg, emit)
                except Exception as ex:   # 화면에는 오류 메시지 형식이 없어서 서버 로그로 알린다
                    log.error("회차 시작 실패: %s", ex)
                    pipe = None
            elif kind == "session.end":
                if pipe:
                    pipe.stop()
                pipe = None
                log.info("회차 종료: %s", msg.get("show_id"))
            elif kind == "settings.update":
                log.info("설정 변경: %s", msg)
            else:
                log.warning("모르는 메시지: %s", msg)
    except WebSocketDisconnect:
        log.info("화면 연결 끊김")
    finally:
        if pipe:
            pipe.stop()
        send_task.cancel()
