"""Google 음성인식 감싸개: 요청 모양만 본다 (가짜 클라이언트, API · 키 없이)."""
import numpy as np
import pytest

cloud_speech = pytest.importorskip("google.cloud.speech_v2.types.cloud_speech")

from engine.stt.google import GoogleEngine  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def recognize(self, request, timeout=None):
        self.calls.append((request, timeout))
        return cloud_speech.RecognizeResponse()


def engine():
    eng = GoogleEngine()
    eng.cs, eng.client, eng.recognizer = cloud_speech, FakeClient(), "projects/p/locations/us/recognizers/_"
    return eng


def test_request_timeout_is_short():
    """느린 요청이 동시 요청 자리를 오래 붙잡지 않게 (늦은 결과는 어차피 버림)."""
    eng = engine()
    eng.transcribe(np.zeros(16000 * 3, dtype="float32"))
    assert eng.client.calls[0][1] == eng.timeout <= 5

