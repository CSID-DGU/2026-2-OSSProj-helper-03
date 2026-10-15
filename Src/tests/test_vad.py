"""VAD: 말소리 없는 조각 거르기 (VADGate) · 음량 VAD · Silero (faster-whisper 가 있을 때만)."""
import numpy as np
import pytest
from conftest import FakeSTT

from engine import vad
from engine.vad import EnergyVAD, VADGate, make_vad, rms_db

SR = 16000


def vowels(sec: float = 2.0) -> np.ndarray:
    """말소리 비슷한 합성음: 배음이 있는 목소리 + 0.25초마다 바뀌는 모음(포먼트) + 4Hz 음절."""
    t = np.arange(int(sec * SR)) / SR
    phase = 2 * np.pi * np.cumsum(130 + 25 * np.sin(2 * np.pi * 1.5 * t)) / SR
    src = sum(np.sin(k * phase) / k for k in range(1, 30))
    out, seg = np.zeros_like(t), int(0.25 * SR)
    forms = [(700, 1200), (300, 2300), (500, 900), (400, 2000)]
    for i in range(0, len(t), seg):
        f1, f2 = forms[(i // seg) % 4]
        x = src[i:i + seg]
        f = np.fft.rfftfreq(len(x), 1 / SR)
        h = np.exp(-((f - f1) / 120) ** 2) + 0.7 * np.exp(-((f - f2) / 150) ** 2)
        out[i:i + seg] = np.fft.irfft(np.fft.rfft(x) * h, n=len(x))
    y = out * 0.5 * (1 - np.cos(2 * np.pi * 4 * t))
    return (0.3 * y / np.abs(y).max()).astype("float32")


def noise(db: float, sec: float = 3.0) -> np.ndarray:
    x = np.random.default_rng(0).normal(0, 1, int(sec * SR)).astype("float32")
    return x / np.sqrt(np.mean(x ** 2)) * 10 ** (db / 20)


class FakeVAD:
    name = "fake"

    def __init__(self, answers):
        self.answers = list(answers)

    def has_input(self, audio):
        ans = self.answers.pop(0)
        if isinstance(ans, Exception):
            raise ans
        return ans


def test_gate_skips_chunks_without_input():
    stt = FakeSTT(["첫 줄", "둘째 줄"])
    gate = VADGate(stt, FakeVAD([False, True, False, True]))
    silence = np.zeros(SR * 3, dtype="float32")
    assert [gate.transcribe(silence, ["힌트"]) for _ in range(4)] == ["", "첫 줄", "", "둘째 줄"]
    assert stt.calls == 2 and stt.hints_seen == [["힌트"], ["힌트"]]   # 거른 조각은 엔진을 부르지 않음
    assert (gate.calls, gate.skipped) == (4, 2)
    assert gate.mode == "chunk" and gate.label == "fake+vad(fake)"


def test_gate_sends_when_vad_fails():
    stt = FakeSTT(["글자"])
    gate = VADGate(stt, FakeVAD([RuntimeError("모델 없음")]))
    assert gate.transcribe(np.zeros(SR, dtype="float32")) == "글자"


def test_gate_passes_stream_through():
    class Streamer(FakeSTT):
        mode = "stream"

        def stream(self, frames, hints_fn=None):
            yield {"text": "x", "final": True}

    gate = VADGate(Streamer([]), FakeVAD([]))
    assert gate.mode == "stream"
    assert list(gate.stream(iter([]))) == [{"text": "x", "final": True}]


def test_energy_vad():
    v = EnergyVAD()
    assert abs(rms_db(noise(-20)) + 20) < 0.1
    assert not v.is_speech(np.zeros(SR * 3, dtype="float32"))
    assert not v.has_input(noise(-60))
    assert v.is_speech(noise(-20)) and v.has_input(noise(-20))   # 음량 VAD 는 잡음도 말소리로 봄
    assert v.speech_ratio(np.concatenate([np.zeros(SR, "float32"), noise(-20, 1.0)])) == pytest.approx(0.5, abs=0.05)
    assert len(v.probs(np.zeros(100, dtype="float32"))) == 0


def test_make_vad_falls_back_to_energy(monkeypatch):
    def broken(self, **kw):
        raise ImportError("faster_whisper 없음")
    monkeypatch.setattr(vad.SileroVAD, "__init__", broken)
    v = make_vad(threshold=0.2, min_speech_sec=0.3)
    assert isinstance(v, EnergyVAD) and v.min_speech_sec == 0.3
    assert isinstance(make_vad("energy"), EnergyVAD)


@pytest.fixture(scope="module")
def silero():
    pytest.importorskip("onnxruntime")
    pytest.importorskip("faster_whisper")
    return vad.SileroVAD()


def test_silero_speech_and_silence(silero):
    speech = vowels()
    before = speech.copy()
    p = silero.probs(speech)
    assert len(p) == -(-len(speech) // vad.WINDOW)            # 32ms 창마다 하나
    assert np.array_equal(speech, before)                     # 입력을 고쳐 쓰지 않음
    assert silero.is_speech(speech) and silero.speech_ratio(speech) > 0.5
    silence = np.zeros(SR * 3, dtype="float32")
    assert not silero.is_speech(silence) and not silero.has_input(silence)
    assert not silero.has_input(noise(-55))                   # 조용한 잡음: 보내지 않음
    assert silero.has_input(noise(-20))                       # 큰 소리는 말소리를 놓쳤을 수 있어 보냄


def test_silero_gate_end_to_end(silero):
    stt = FakeSTT(["대사"])
    gate = VADGate(stt, silero)
    assert gate.transcribe(np.zeros(SR * 3, dtype="float32")) == ""
    assert gate.transcribe(vowels(3.0) * 0.05) == "대사"       # 작게 들려도 말소리면 보냄
    assert stt.calls == 1


def test_server_wraps_engine_with_vad(sample_cues, silence, monkeypatch):
    """HELPER_VAD=1 이면 서버가 음성인식 엔진을 VADGate 로 감싼다 (조용한 녹음 → 엔진을 부르지 않음)."""
    import time

    from fastapi.testclient import TestClient

    import server.main as srv

    stt, gates = FakeSTT(["대사"]), []

    def make_gate(inner):
        gates.append(VADGate(inner, FakeVAD([False] * 100)))
        return gates[-1]

    monkeypatch.setattr(srv, "get_engine", lambda name: stt)
    monkeypatch.setattr(srv, "find_audio_file", lambda cue_path: cue_path)
    monkeypatch.setattr(srv, "load_wav", lambda path: silence[:SR * 9])
    monkeypatch.setattr(srv, "VADGate", make_gate)
    monkeypatch.setenv("HELPER_SPEED", "30")
    monkeypatch.setenv("HELPER_VAD", "1")

    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "test", "cue_file": "sample_cues.csv"})
        deadline = time.time() + 5
        while time.time() < deadline and not (gates and gates[0].calls >= 3):
            ws.receive_json()
        ws.send_json({"type": "session.end", "show_id": "test"})

    assert gates and gates[0].calls >= 3 and gates[0].skipped == gates[0].calls
    assert stt.calls == 0
