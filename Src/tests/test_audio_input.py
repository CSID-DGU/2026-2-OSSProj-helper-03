"""마이크 입력: 고리 버퍼 · 주파수 바꾸기 · 파이프라인 연결 (sounddevice 없이 가짜 장치로)."""
import threading
import time

import numpy as np
import pytest
from conftest import FakeSTT

from engine.audio_input import SR, MicSource, resample
from engine.pipeline import Pipeline


def ramp(start: float, sec: float) -> np.ndarray:
    """값 = 소리 시각(초)인 신호. 버퍼에서 꺼낸 부분이 어느 시각인지 바로 알 수 있다."""
    return (np.arange(int(start * SR), int((start + sec) * SR)) / SR / 1000).astype("float32")


def push_seconds(mic: MicSource, sec: float):
    for i in range(int(round(sec / 0.1))):
        mic._push(ramp(i * 0.1, 0.1))


def test_ring_buffer_segment():
    mic = MicSource(buffer_sec=1.0)
    assert mic.now_audio() == 0.0 and len(mic.segment(0, 1)) == 0
    push_seconds(mic, 0.5)
    assert mic.pos == mic.now_audio() == 0.5
    seg = mic.segment(0.1, 0.3)
    assert len(seg) == int(0.2 * SR)
    assert np.allclose(seg, ramp(0.1, 0.2))
    assert len(mic.segment(0.4, 0.9)) == int(0.1 * SR)       # 아직 안 들어온 뒷부분은 빠짐


def test_ring_buffer_keeps_last_seconds():
    mic = MicSource(buffer_sec=1.0)
    push_seconds(mic, 2.5)                                    # 1초 버퍼를 두 바퀴 넘게
    assert abs(mic.pos - 2.5) < 1e-9
    assert np.allclose(mic.segment(0, 2.5), ramp(1.5, 1.0))   # 최근 1초만 남음
    assert np.allclose(mic.segment(2.0, 3.0), ramp(2.0, 0.5))
    assert len(mic.segment(0.2, 1.0)) == 0                    # 이미 밀려난 부분
    assert mic.level > 0


def test_push_longer_than_buffer():
    mic = MicSource(buffer_sec=0.5)
    mic._push(ramp(0, 2.0))
    assert mic.pos == 2.0
    assert np.allclose(mic.segment(0, 2.0), ramp(1.5, 0.5))


def test_resample_to_16k():
    for rate in (48000, 44100):
        t = np.arange(int(rate * 0.1)) / rate
        x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        y = resample(x, rate)
        assert len(y) == 1600 and y.dtype == np.float32
        assert abs(np.sqrt(np.mean(y[50:-50] ** 2)) - 0.5 / np.sqrt(2)) < 0.02   # 440Hz 는 그대로
    x = np.ones(1600, "float32")
    assert resample(x, SR) is x                               # 16kHz 면 그대로


class FakeStream:
    """sounddevice.InputStream 대신: 0.1초 조각을 빨리 감기로 넣어 준다."""

    def __init__(self, mic: MicSource, seconds: float, rate: int = SR, speed: float = 20):
        self.mic, self.seconds, self.rate, self.speed = mic, seconds, rate, speed
        self.closed = threading.Event()

    def start(self):
        def feed():
            for _ in range(int(self.seconds / 0.1)):
                if self.closed.is_set():
                    return
                self.mic._q.put(np.zeros(int(self.rate * 0.1), dtype="float32"))
                time.sleep(0.1 / self.speed)
        threading.Thread(target=feed, daemon=True).start()

    def stop(self):
        self.closed.set()

    def close(self):
        self.closed.set()


class FakeMic(MicSource):
    def __init__(self, seconds: float, rate: int = SR):
        super().__init__(buffer_sec=10)
        self.seconds, self.fake_rate = seconds, rate

    def open(self):
        if self._stream is None:
            self._stream = FakeStream(self, self.seconds, self.fake_rate)
            self.rate, self.name = self.fake_rate, "fake"


def test_frames_resamples_and_stops():
    mic = FakeMic(1.0, rate=48000)
    got = []
    for pcm in mic.frames():
        got.append(len(pcm))
        if mic.pos >= 1.0:
            mic.stop()
    assert got == [3200] * 10                                 # 16kHz PCM16 0.1초 = 3200 바이트
    assert mic.done.is_set() and mic._stream is None and mic.level == 0.0


def test_pipeline_with_mic_source(sample_cues):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    msgs, stt = [], FakeSTT([c.text for c in lines[:3]])
    mic = FakeMic(9.5)
    pipe = Pipeline(sample_cues, mic, stt, msgs.append)
    assert pipe.source is mic and mic.duration == float("inf")
    pipe.start()
    deadline = time.time() + 5
    while time.time() < deadline and mic.pos < 9.4:
        time.sleep(0.05)
    time.sleep(0.2)
    assert not pipe.finished                                  # 마이크는 멈추기 전까지 끝나지 않음
    pipe.stop()
    pipe.join(timeout=5)
    assert pipe.finished and not any(th.is_alive() for th in pipe.threads)
    assert [m["cue_id"] for m in msgs if m["type"] == "position.update"] == [c.id for c in lines[:3]]
    assert stt.calls == 3                                     # 3초 조각 3개 (9.5초)


def test_server_session_with_mic(sample_cues, monkeypatch):
    """HELPER_INPUT=mic 이면 녹음 파일 없이 마이크로 회차를 시작한다."""
    from fastapi.testclient import TestClient

    import server.main as srv

    lines = [c for c in sample_cues if c.type == "dialogue"]
    monkeypatch.setattr(srv, "get_engine", lambda name: FakeSTT([c.text for c in lines[:2]]))
    monkeypatch.setattr(srv, "find_audio_file", lambda cue_path: pytest.fail("마이크 모드에서 녹음을 찾음"))
    monkeypatch.setattr(srv, "MicSource", lambda device: FakeMic(6.5))
    monkeypatch.setenv("HELPER_INPUT", "mic")

    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "test", "cue_file": "sample_cues.csv"})
        got, deadline = [], time.time() + 10
        while time.time() < deadline and len([m for m in got if m["type"] == "position.update"]) < 2:
            got.append(ws.receive_json())
        ws.send_json({"type": "session.end", "show_id": "test"})

    assert [m["cue_id"] for m in got if m["type"] == "position.update"] == [c.id for c in lines[:2]]
