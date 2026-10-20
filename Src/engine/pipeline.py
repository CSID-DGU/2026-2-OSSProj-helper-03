"""②~⑤ 연결: 오디오 → 음성인식 → 위치 추적 → 이탈 감지 → 화면 메시지.

스레드 3개로 돈다 (음성인식이 느려도 소리 재생 · 상태 보내기가 끊기지 않게).
- 재생: FileSource(녹음, 실제 시간 속도) 또는 MicSource(마이크)가 소리를 흘려보냄
- 인식: 조각 방식이면 chunk_sec 마다 최근 소리를 인식 / 스트리밍이면 결과가 올 때마다
- 상태: 1초마다 input.status (화면은 5초간 메시지가 없으면 '엔진 응답 없음')
"""
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from .aligner import Aligner
from .audio_input import FileSource, MicSource
from .cue_loader import Cue
from .deviation import DeviationDetector
from .protocol import deviation_alert, input_status, position_update
from .stt import STTEngine

log = logging.getLogger("helper.pipeline")

MAX_SYLLABLES_PER_SEC = 8    # 이보다 빠르면 사람이 말한 게 아니라 환각으로 본다
STREAM_TAIL = 12             # 스트리밍 결과에서 정렬기에 넣을 최근 글자 수 (공백 제외)


def implausible(text: str, prev: str, dur_sec: float) -> bool:
    """정렬기에 넣기 전 걸러내기: 너무 빠른 말 · 직전과 똑같은 글자 · 같은 말 3번 이상 반복."""
    syllables = len(re.findall(r"[가-힣]", text))
    if dur_sec and syllables > MAX_SYLLABLES_PER_SEC * dur_sec:
        return True
    if text and text == prev:
        return True
    words = text.split()
    return any(words[i] == words[i + 1] == words[i + 2] for i in range(len(words) - 2))


class Pipeline:
    def __init__(self, cues: list[Cue], audio: np.ndarray | FileSource | MicSource, stt: STTEngine,
                 emit: Callable[[dict], None], *,
                 hints: bool = True, chunk_sec: float = 3.0, hop_sec: float | None = None,
                 deviate_after: float = 3.0,
                 speed: float = 1.0, song_segment: bool = True, stt_workers: int | None = None,
                 aligner_kw: dict | None = None):
        self.aligner = Aligner(cues, **(aligner_kw or {}))
        self.detector = DeviationDetector(deviate_after)
        # 녹음(ndarray)이면 파일 재생, 아니면 받은 소리 원천(MicSource 등)을 그대로 쓴다
        self.source = FileSource(audio, speed) if isinstance(audio, np.ndarray) else audio
        self.stt, self.emit = stt, emit
        self.hints, self.chunk_sec, self.speed = hints, chunk_sec, speed
        self.hop_sec = hop_sec or chunk_sec    # 조각을 보내는 간격. chunk_sec 보다 짧으면 겹쳐 보냄
        self.workers = max(1, stt_workers or stt.workers)   # 동시에 보내는 인식 요청 수 (없으면 엔진 기본값)
        self.song_segment = song_segment
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.threads: list[threading.Thread] = []
        self.prev_text = ""

    # ── 시작 · 종료 ──────────────────────────────────────────
    def start(self):
        if self.stt.mode == "chunk":
            targets = [self.source.run, self._chunk_loop]
        else:
            targets = [self._stream_loop]
        targets.append(self._heartbeat_loop)
        for fn in targets:
            th = threading.Thread(target=fn, name=f"helper-{fn.__name__}", daemon=True)
            th.start()
            self.threads.append(th)
        log.info("회차 시작: %s, 소리 %.1f초, 추적 큐 %d개", self.stt.label, self.source.duration,
                 len(self.aligner.items))

    def stop(self):
        self.stopped.set()
        self.source.stop()

    def join(self, timeout: float | None = None):
        for th in self.threads:
            th.join(timeout)

    @property
    def finished(self) -> bool:
        return self.source.done.is_set()

    # ── 공통 ────────────────────────────────────────────────
    def _segment(self) -> str:
        if self.song_segment and self.aligner.current.type == "lyric":
            return "song"
        return "dialogue"

    def _hint_texts(self) -> list[str] | None:
        if not self.hints:
            return None
        with self.lock:
            return [c.text for c in self.aligner.hint_cues()] or None

    def _handle(self, text: str, audio_end: float, transcript: str | None = None):
        """인식 글자 하나를 정렬기 · 이탈 감지에 넣고 화면 메시지를 보낸다. audio_end = 그 소리의 끝 시각."""
        with self.lock:
            step = self.aligner.update(text, audio_end)
            song = self._segment() == "song"
            alert = self.detector.update(step, self.aligner.pos, int(time.time() * 1000), hold=song)
        if step.heard:
            latency_ms = (self.source.now_audio() - audio_end) * 1000 / self.speed
            self.emit(position_update(step.cue.id, step.score / 100, latency_ms, transcript or text))
        if alert:
            log.info("이탈 알림: %s since=%d 복귀=%s", alert.deviation_type, alert.since, alert.return_cue_id)
            self.emit(deviation_alert(alert.deviation_type, alert.since, alert.return_cue_id))

    def _heartbeat_loop(self):
        # 회차 종료(session.end)까지 계속 보낸다. 녹음이 끝난 뒤에는 '음향 입력 없음'(level 0)
        # → 멈추면 화면이 5초 뒤 '엔진 응답 없음'으로 오해한다
        while not self.stopped.is_set():
            ended = self.source.done.is_set()
            level = 0.0 if ended else self.source.level
            with self.lock:
                seg = "dialogue" if ended else self._segment()
                self.detector.tick(int(time.time() * 1000), level)   # 오래 조용하면 '입력 없음' (알림 안 보냄)
            self.emit(input_status(level, seg))
            self.stopped.wait(1.0)

    # ── 조각 방식 ────────────────────────────────────────────
    def _chunk_loop(self):
        """hop_sec 마다 최근 chunk_sec 소리를 인식 요청으로 보낸다. 요청은 동시에 최대 workers 개.

        - 대본 힌트는 요청을 보낼 때의 추적 위치로 만든다
        - 결과는 조각 순서대로 처리한다 (걸러내기 · 직전 글자 비교도 이 순서). 뒤 조각이 먼저 끝나면
          아직 안 끝난 앞 조각은 늦은 결과로 버린다 → 느린 요청 하나가 화면을 붙잡지 않음
          (조각이 겹치면 버린 조각의 소리는 앞뒤 조각에 들어 있다)
        - 요청이 다 차서 밀리면 지난 조각은 보내지 않고 최신 소리로 (지연이 쌓이지 않게)
        workers=1 이면 예전처럼 한 번에 하나씩: 결과를 처리한 뒤 다음 조각을 보낸다.
        """
        self.records: list[dict] = []           # 요청마다 chunk_start · chunk_end · text · proc_sec (+ error · late)
        self.stats = {"skipped": 0, "late": 0}  # 밀려서 안 보낸 조각 수 · 늦어서 버린 결과 수
        pool = ThreadPoolExecutor(self.workers, thread_name_prefix="helper-stt")
        pending: deque[tuple[dict, Future]] = deque()   # 보냈고 아직 처리 안 한 조각 (보낸 순서)
        busy: list[Future] = []                          # 진행 중인 요청 (버린 것 포함)
        end = self.hop_sec if self.hop_sec < self.chunk_sec else self.chunk_sec
        try:
            while not self.stopped.is_set():
                busy = [f for f in busy if not f.done()]   # 먼저 세고 처리 → 여기서 끝난 결과는 아래서 처리됨
                self._collect(pending)                     # (workers=1 이면 힌트가 늘 직전 결과까지 반영)
                now = self.source.now_audio()
                if now < end or len(busy) >= self.workers:
                    time.sleep(0.02)
                    continue
                behind = now - end
                if behind > self.hop_sec:   # 인식이 밀리면 지난 조각은 버리고 최신 소리로
                    n = int(behind // self.hop_sec)
                    end += n * self.hop_sec
                    self.stats["skipped"] += n
                if end > self.source.duration + 1e-6:
                    break
                rec = {"chunk_start": max(0.0, end - self.chunk_sec), "chunk_end": end}
                seg = self.source.segment(rec["chunk_start"], end)
                fut = pool.submit(self._recognize, seg, self._hint_texts(), rec)
                self.records.append(rec)
                pending.append((rec, fut))
                busy.append(fut)
                end += self.hop_sec
            while pending and not self.stopped.is_set():   # 녹음 끝: 남은 결과까지 처리
                self._collect(pending)
                time.sleep(0.02)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        log.info("인식 끝: 요청 %d, 밀려서 건너뜀 %d, 늦어서 버림 %d, 실패 %d", len(self.records),
                 self.stats["skipped"], self.stats["late"], sum("error" in r for r in self.records))

    def _recognize(self, seg: np.ndarray, hints: list[str] | None, rec: dict) -> str:
        """인식 요청 하나 (작업 스레드). 실패는 건너뛰고 계속 (끊김은 로그로 남김)."""
        t0 = time.perf_counter()
        try:
            text = self.stt.transcribe(seg, hints)
        except Exception as ex:
            log.warning("인식 실패 (%.1fs): %s", rec["chunk_end"], ex)
            text, rec["error"] = "", str(ex)
        rec.update(text=text, proc_sec=round(time.perf_counter() - t0, 3))
        return text

    def _collect(self, pending: deque):
        """끝난 인식 결과를 조각 순서대로 처리. 뒤 조각이 먼저 끝났으면 앞의 안 끝난 조각은 버린다."""
        last = max((i for i, (_, f) in enumerate(pending) if f.done()), default=-1)
        for _ in range(last + 1):
            rec, fut = pending.popleft()
            if not fut.done():         # 늦은 결과: 나중에 끝나도 쓰지 않음
                rec["late"] = True
                self.stats["late"] += 1
                continue
            raw = fut.result()
            text = "" if implausible(raw, self.prev_text, self.chunk_sec) else raw
            self.prev_text = raw
            self._handle(text, rec["chunk_end"], raw)

    # ── 스트리밍 ────────────────────────────────────────────
    def _stream_loop(self):
        prev, last_feed = "", -1.0
        try:
            for ev in self.stt.stream(self.source.frames(), self._hint_texts if self.hints else None):
                if self.stopped.is_set():
                    break
                text, now = ev["text"], self.source.now_audio()
                if text == prev or (not ev["final"] and now - last_feed < 0.5):
                    continue
                prev, last_feed = text, now
                tail = "".join(text.split())[-STREAM_TAIL:]
                end = ev.get("audio_end")
                self._handle(tail, min(end, now) if end else now, text)
                if ev["final"]:
                    prev = ""
        except Exception as ex:
            log.warning("스트리밍 끊김: %s", ex)
        finally:
            self.source.done.set()
        log.info("스트리밍 끝")
