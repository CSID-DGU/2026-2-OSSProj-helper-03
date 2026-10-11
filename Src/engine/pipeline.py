"""②~⑤ 연결: 오디오 → 음성인식 → 위치 추적 → 이탈 감지 → 화면 메시지.

스레드 3개로 돈다 (음성인식이 느려도 소리 재생 · 상태 보내기가 끊기지 않게).
- 재생: FileSource 가 실제 시간 속도로 소리를 흘려보냄
- 인식: 조각 방식이면 chunk_sec 마다 최근 소리를 인식 / 스트리밍이면 결과가 올 때마다
- 상태: 1초마다 input.status (화면은 5초간 메시지가 없으면 '엔진 응답 없음')
"""
import logging
import re
import threading
import time
from collections.abc import Callable

import numpy as np

from .aligner import Aligner
from .audio_input import FileSource
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
    def __init__(self, cues: list[Cue], audio: np.ndarray, stt: STTEngine, emit: Callable[[dict], None], *,
                 hints: bool = True, chunk_sec: float = 3.0, deviate_after: float = 6.0,
                 speed: float = 1.0, song_segment: bool = True):
        self.aligner = Aligner(cues)
        self.detector = DeviationDetector(deviate_after)
        self.source = FileSource(audio, speed)
        self.stt, self.emit = stt, emit
        self.hints, self.chunk_sec, self.speed = hints, chunk_sec, speed
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
        """인식 글자 하나를 정렬기 · 이탈 감지에 넣고 화면 메시지를 보낸다."""
        with self.lock:
            step = self.aligner.update(text)
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
            with self.lock:
                seg = "dialogue" if ended else self._segment()
            self.emit(input_status(0.0 if ended else self.source.level, seg))
            self.stopped.wait(1.0)

    # ── 조각 방식 ────────────────────────────────────────────
    def _chunk_loop(self):
        end = self.chunk_sec
        while not self.stopped.is_set():
            while self.source.now_audio() < end and not self.stopped.is_set():
                time.sleep(0.02)
            if self.stopped.is_set() or end > self.source.duration + 1e-6:
                break
            seg = self.source.segment(end - self.chunk_sec, end)
            try:
                text = self.stt.transcribe(seg, self._hint_texts())
            except Exception as ex:   # 인식 실패는 건너뛰고 계속 (끊김은 로그로 남김)
                log.warning("인식 실패 (%.1fs): %s", end, ex)
                text = ""
            raw = text
            if implausible(text, self.prev_text, self.chunk_sec):
                text = ""
            self.prev_text = raw
            self._handle(text, end, raw)
            end += self.chunk_sec
            behind = self.source.now_audio() - end
            if behind > self.chunk_sec:   # 인식이 밀리면 지난 조각은 버리고 최신 소리로 (지연이 쌓이지 않게)
                end += (behind // self.chunk_sec) * self.chunk_sec
        log.info("인식 끝")

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
