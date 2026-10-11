"""공통 준비물. 저장소에 있는 샘플 대본(ui/mock/sample_cues.csv)만 쓴다 (실제 공연 데이터 없음)."""
from pathlib import Path

import numpy as np
import pytest

from engine.cue_loader import load_cues
from engine.stt.base import STTEngine

SRC = Path(__file__).resolve().parents[1]
SAMPLE_CSV = SRC / "ui" / "mock" / "sample_cues.csv"


@pytest.fixture(autouse=True)
def no_preload(monkeypatch):
    """테스트에서는 서버가 진짜 음성인식 모델을 미리 불러오지 않게 한다."""
    monkeypatch.setenv("HELPER_PRELOAD", "0")


@pytest.fixture
def sample_cues():
    return load_cues(SAMPLE_CSV)


@pytest.fixture
def silence():
    """30초 무음 (16kHz)."""
    return np.zeros(16000 * 30, dtype="float32")


class FakeSTT(STTEngine):
    """정해 둔 글자를 조각마다 차례로 돌려주는 가짜 음성인식 (조각 방식)."""
    key = label = "fake"
    mode = "chunk"

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.calls = 0
        self.hints_seen: list[list[str] | None] = []

    def transcribe(self, audio, hints=None):
        self.hints_seen.append(hints)
        text = self.texts[self.calls] if self.calls < len(self.texts) else ""
        self.calls += 1
        return text
