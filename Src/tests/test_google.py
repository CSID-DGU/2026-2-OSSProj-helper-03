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



class SlowClient(FakeClient):
    """복사본마다 다른 시간 · 실패 (보낸 순서대로 delays 를 씀)."""
    def __init__(self, delays, fail=()):
        super().__init__()
        self.delays, self.fail, self.n = list(delays), set(fail), 0

    def recognize(self, request, timeout=None):
        import time
        i, self.n = self.n, self.n + 1
        time.sleep(self.delays[i])
        if i in self.fail:
            raise RuntimeError("504")
        return super().recognize(request, timeout)


def test_hedged_request_uses_the_first_answer():
    """같은 요청을 두 번 보내면 먼저 온 답을 쓰고, 두 복사본의 처리 시간을 요청 기록에 남긴다."""
    import time
    eng = engine()
    eng.hedge, eng.client = 2, SlowClient([0.5, 0.05])
    t0 = time.perf_counter()
    eng.transcribe(np.zeros(16000, dtype="float32"))
    assert time.perf_counter() - t0 < 0.4                 # 느린 쪽(0.5초)을 기다리지 않음
    info = eng.request_info()
    assert len(info["copies"]) >= 1 and eng.request_info() == {}   # 한 번 읽으면 비움
    time.sleep(0.6)
    assert len(info["copies"]) == 2                       # 늦은 복사본 시간도 나중에 채워짐


def test_hedged_request_survives_one_failure():
    eng = engine()
    eng.hedge, eng.client = 2, SlowClient([0.01, 0.1], fail={0})
    assert eng.transcribe(np.zeros(16000, dtype="float32")) == ""   # 실패한 복사본 대신 다른 답
    eng.client = SlowClient([0.01, 0.02], fail={0, 1})
    with pytest.raises(RuntimeError):
        eng.transcribe(np.zeros(16000, dtype="float32"))


def test_hedge_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_STT_HEDGE", "2")
    eng = GoogleEngine()
    assert eng.hedge == 2 and eng.label.endswith("x2")
    monkeypatch.setenv("GOOGLE_STT_HEDGE", "")
    assert GoogleEngine().hedge == 1
