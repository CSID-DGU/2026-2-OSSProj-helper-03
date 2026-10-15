"""③ 음성인식 엔진 목록. HELPER_STT 로 고른다."""
from ..config import env
from .base import MissingConfig, STTEngine


def make_engine(name: str) -> STTEngine:
    eng = _new_engine(name)
    workers = int(env("HELPER_STT_WORKERS") or 0)   # 동시 인식 요청 수. 비우면 엔진 기본값
    if workers > 0:
        eng.workers = workers
    return eng


def _new_engine(name: str) -> STTEngine:
    # 쓰는 엔진의 라이브러리만 불러오도록 여기서 import
    if name == "whisper":
        from .whisper import WhisperEngine
        return WhisperEngine()
    if name == "google":
        from .google import GoogleEngine
        return GoogleEngine()
    if name == "google_stream":
        from .google import GoogleStreamEngine
        return GoogleStreamEngine()
    if name == "clova_stream":
        from .clova_stream import ClovaStreamEngine
        return ClovaStreamEngine()
    raise ValueError(f"모르는 음성인식 엔진: {name} (whisper / google / google_stream / clova_stream)")


__all__ = ["MissingConfig", "STTEngine", "make_engine"]
