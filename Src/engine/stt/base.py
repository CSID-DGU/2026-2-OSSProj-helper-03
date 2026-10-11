"""③ 음성인식: 로컬 · 클라우드를 같은 모양으로 감싸는 틀.

- 조각 방식 (mode="chunk"): transcribe(소리 조각, hints) → 글자
- 스트리밍 (mode="stream"):  stream(PCM 조각 생성기, hints_fn) → {"text", "final", "audio_end"} 이벤트들
"""
from collections.abc import Callable, Iterator

import numpy as np


class MissingConfig(Exception):
    """키·설정이 없어서 이 엔진을 쓸 수 없음."""


class STTEngine:
    key = ""
    label = ""
    mode = "chunk"

    def check(self) -> None:
        """설정이 모자라면 MissingConfig."""

    def setup(self) -> None:
        """모델 불러오기 · 클라이언트 만들기 (한 번만)."""

    def transcribe(self, audio: np.ndarray, hints: list[str] | None = None) -> str:
        raise NotImplementedError

    def stream(self, frames: Iterator[bytes], hints_fn: Callable[[], list[str]] | None = None) -> Iterator[dict]:
        raise NotImplementedError
