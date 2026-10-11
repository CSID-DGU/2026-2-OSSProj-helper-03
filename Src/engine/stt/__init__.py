"""③ 음성인식 엔진 목록. HELPER_STT 로 고른다."""
from .base import MissingConfig, STTEngine


def make_engine(name: str) -> STTEngine:
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
