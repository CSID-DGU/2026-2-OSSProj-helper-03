"""음성 구간 감지 (VAD).

- Silero VAD: faster-whisper 에 들어 있는 ONNX 모델(silero_vad_v6.onnx)을 onnxruntime 으로 돌린다 (torch 없음)
- 음량 VAD: Silero 를 못 쓸 때 대신 쓰는 간단한 방식 (말소리와 음악 · 잡음을 가리지 못함)

쓰는 곳
- VADGate: 소리가 없는 조각은 음성인식에 보내지 않는다 (API 비용 절약 · 무음에서 대본 힌트를 지어내는 것 줄이기)
- is_speech / speech_ratio / has_input: '음향 입력 없음' 같은 상태 판단용

1차 데이터(음악 위 대사 · 노래)에서 Silero 는 말소리를 많이 놓쳤다 (기본값 0.5 로 거르면 chirp ±1큐 83% → 55%,
가사 88% → 38%). 그래서 문턱을 낮추고, 조각이 어느 정도 크게 들리면 Silero 와 상관없이 보낸다 (has_input)
→ 조용하고 말소리도 없는 조각만 건너뛴다 (1차 데이터에서 정확도 그대로, 녹음 음량을 −20dB 줄여도 그대로).
"""
import functools
import logging

import numpy as np

from .audio_input import SR
from .stt.base import STTEngine

log = logging.getLogger("helper.vad")

WINDOW = 512                 # Silero 가 한 번에 보는 길이 (16kHz 에서 32ms)
THRESHOLD = 0.1              # 이 확률 이상인 창을 말소리로 본다 (Silero 기본 0.5 는 노래 · 음악 위 대사를 놓침)
MIN_SPEECH_SEC = 0.1         # 조각 안 말소리가 이보다 짧으면 말소리 없음
LOUD_DB = -40.0              # 조각 음량이 이보다 크면(dBFS, 음량 막대 0.33) Silero 가 놓쳤을 수 있어 보낸다
ENERGY_DB = -40.0            # 음량 VAD: 이보다 큰 창을 말소리로 본다


def rms_db(audio: np.ndarray) -> float:
    """조각 전체 음량 (dBFS)."""
    audio = np.asarray(audio, dtype="float32")
    if len(audio) == 0:
        return -120.0
    return float(20 * np.log10(max(float(np.sqrt(np.mean(audio ** 2))), 1e-6)))


class SileroVAD:
    name = "silero"

    def __init__(self, threshold: float = THRESHOLD, min_speech_sec: float = MIN_SPEECH_SEC,
                 loud_db: float = LOUD_DB):
        from faster_whisper.vad import get_vad_model   # 모델 파일만 빌린다 (onnxruntime 으로 돎)
        self.model = get_vad_model()
        self.threshold, self.min_speech_sec, self.loud_db = threshold, min_speech_sec, loud_db

    def probs(self, audio: np.ndarray) -> np.ndarray:
        """32ms 창마다 말소리 확률 (0~1). 조각마다 상태를 새로 시작한다."""
        audio = np.asarray(audio, dtype="float32").reshape(-1)
        if len(audio) == 0:
            return np.zeros(0, dtype="float32")
        padded = np.pad(audio, (0, (-len(audio)) % WINDOW))   # 새 배열 (모델이 입력을 고쳐 쓰므로)
        return np.asarray(self.model(padded), dtype="float32").reshape(-1)

    def speech_ratio(self, audio: np.ndarray) -> float:
        """조각에서 말소리 창의 비율 (0~1)."""
        p = self.probs(audio)
        return float((p >= self.threshold).mean()) if len(p) else 0.0

    def is_speech(self, audio: np.ndarray) -> bool:
        """말소리(노래 포함)가 MIN_SPEECH_SEC 이상 있나."""
        return float((self.probs(audio) >= self.threshold).sum()) * WINDOW / SR >= self.min_speech_sec

    def has_input(self, audio: np.ndarray) -> bool:
        """음성인식에 보낼 만한가: 크게 들리거나 말소리가 있으면 True (조용하고 말소리도 없으면 False)."""
        return rms_db(audio) > self.loud_db or self.is_speech(audio)


class EnergyVAD(SileroVAD):
    """Silero 를 못 쓸 때 대신: 창의 음량이 ENERGY_DB 보다 크면 말소리로 본다."""
    name = "energy"

    def __init__(self, threshold_db: float = ENERGY_DB, min_speech_sec: float = MIN_SPEECH_SEC,
                 loud_db: float = LOUD_DB):
        self.threshold, self.threshold_db = 0.5, threshold_db
        self.min_speech_sec, self.loud_db = min_speech_sec, loud_db

    def probs(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype="float32").reshape(-1)
        n = len(audio) // WINDOW
        if n == 0:
            return np.zeros(0, dtype="float32")
        rms = np.sqrt(np.mean(audio[:n * WINDOW].reshape(n, WINDOW) ** 2, axis=1))
        return (20 * np.log10(np.maximum(rms, 1e-9)) > self.threshold_db).astype("float32")


def make_vad(kind: str = "silero", **kw) -> SileroVAD:
    """kind: silero (못 쓰면 음량 VAD 로) / energy."""
    if kind != "energy":
        try:
            return SileroVAD(**kw)
        except Exception as ex:   # faster-whisper · onnxruntime 이 없거나 모델 파일을 못 읽음
            log.warning("Silero VAD 를 못 씀 (%s) → 음량 VAD 로", ex)
    kw.pop("threshold", None)
    return EnergyVAD(**kw)


@functools.lru_cache(maxsize=1)
def default_vad() -> SileroVAD:
    return make_vad()


def is_speech(audio: np.ndarray) -> bool:
    """이 소리에 말소리(노래 포함)가 있나."""
    return default_vad().is_speech(audio)


def speech_ratio(audio: np.ndarray) -> float:
    """이 소리에서 말소리 부분의 비율 (0~1)."""
    return default_vad().speech_ratio(audio)


def has_input(audio: np.ndarray) -> bool:
    """크게 들리거나 말소리가 있나 (False 면 '음향 입력 없음'으로 볼 수 있음)."""
    return default_vad().has_input(audio)


class VADGate(STTEngine):
    """음성인식 엔진을 감싸서, 소리가 없는 조각(has_input False)은 엔진을 부르지 않고 "" 를 돌려준다.

    조각 방식만 거른다 (스트리밍은 그대로 넘김). 파이프라인 코드는 바꾸지 않아도 된다.
    """

    def __init__(self, stt: STTEngine, vad: SileroVAD | None = None):
        self.stt, self.vad = stt, vad or default_vad()
        self.key, self.mode, self.workers = stt.key, stt.mode, stt.workers   # 동시 요청 수도 감싼 엔진 것을 그대로
        self.label = f"{stt.label}+vad({self.vad.name})"
        self.calls = self.skipped = 0

    def check(self):
        self.stt.check()

    def setup(self):
        self.stt.setup()

    def transcribe(self, audio, hints=None):
        self.calls += 1
        try:
            send = self.vad.has_input(audio)
        except Exception as ex:   # VAD 가 실패하면 거르지 않고 인식에 보낸다
            log.warning("VAD 실패: %s", ex)
            send = True
        if self.calls % 100 == 0:
            log.info("소리 없는 조각 건너뜀: %d / %d", self.skipped + (not send), self.calls)
        if not send:
            self.skipped += 1
            return ""
        return self.stt.transcribe(audio, hints)

    def stream(self, frames, hints_fn=None):
        return self.stt.stream(frames, hints_fn)
