"""화면과 같은 방식으로 WebSocket 에 붙어 회차를 시작해 본다 (가짜 음성인식, 30배속)."""
import time

from conftest import FakeSTT
from fastapi.testclient import TestClient

import server.main as srv


def test_session_over_websocket(sample_cues, silence, monkeypatch):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    monkeypatch.setattr(srv, "get_engine", lambda name: FakeSTT([c.text for c in lines[:3]]))
    monkeypatch.setattr(srv, "find_audio_file", lambda cue_path: cue_path)
    monkeypatch.setattr(srv, "load_wav", lambda path: silence)
    monkeypatch.setenv("HELPER_SPEED", "30")

    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "test", "cue_file": "sample_cues.csv"})
        got, deadline = [], time.time() + 10
        while time.time() < deadline and len([m for m in got if m["type"] == "position.update"]) < 3:
            got.append(ws.receive_json())
        ws.send_json({"type": "session.end", "show_id": "test"})

    pos = [m["cue_id"] for m in got if m["type"] == "position.update"]
    assert pos == [c.id for c in lines[:3]]
    assert any(m["type"] == "input.status" for m in got)


def test_health():
    with TestClient(srv.app) as client:
        assert client.get("/health").json()["ok"] is True
