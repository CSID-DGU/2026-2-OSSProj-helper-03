"""② 오디오 입력. 지금은 파일 재생 모드(녹음 파일을 실제 시간 속도로 흘려보냄)만 있다.
마이크 입력(sounddevice)은 같은 모양(frames · level · pos)으로 나중에 추가한다.
"""
import io
import threading
import time

import numpy as np
import soundfile as sf

SR = 16000
FRAME_SEC = 0.1


def load_wav(path) -> np.ndarray:
    """16kHz 모노 float32 로 읽는다."""
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        raise ValueError(f"{path}: {sr}Hz. 16kHz 로 바꿔서 넣어 주세요 (예: ffmpeg -ar 16000 -ac 1)")
    return audio


def to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def to_wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, SR, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def level_of(frame: np.ndarray) -> float:
    """음량 막대용 0~1 (−60 dBFS → 0, 0 dBFS → 1)."""
    if len(frame) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(frame ** 2)))
    if rms < 1e-6:
        return 0.0
    return float(np.clip((20 * np.log10(rms) + 60) / 60, 0.0, 1.0))


class FileSource:
    """녹음 파일을 0.1초씩 실제 시간에 맞춰 내보낸다. speed > 1 이면 빨리 감기 (시험용)."""

    def __init__(self, audio: np.ndarray, speed: float = 1.0):
        self.audio = audio
        self.speed = speed
        self.duration = len(audio) / SR
        self.pos = 0.0          # 지금까지 흘려보낸 소리 길이 (초)
        self.level = 0.0
        self.done = threading.Event()
        self.stopped = threading.Event()
        self._t0 = None

    def now_audio(self) -> float:
        """시작 후 흐른 시간을 소리 시각으로 (빨리 감기 반영)."""
        return 0.0 if self._t0 is None else (time.perf_counter() - self._t0) * self.speed

    def frames(self):
        """PCM16 바이트 조각을 실제 속도로 내보내는 생성기 (스트리밍 엔진용)."""
        step = int(FRAME_SEC * SR)
        self._t0 = time.perf_counter()
        for i in range(0, len(self.audio), step):
            if self.stopped.is_set():
                break
            due = self._t0 + (i / SR) / self.speed
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            frame = self.audio[i:i + step]
            self.level = level_of(frame)
            self.pos = (i + len(frame)) / SR
            yield to_pcm16(frame)
        self.level = 0.0
        self.done.set()

    def run(self):
        """조각 방식 엔진용: 소비자 없이 재생 시계만 돌린다."""
        for _ in self.frames():
            pass

    def segment(self, start: float, end: float) -> np.ndarray:
        return self.audio[int(start * SR):int(end * SR)]

    def stop(self):
        self.stopped.set()
