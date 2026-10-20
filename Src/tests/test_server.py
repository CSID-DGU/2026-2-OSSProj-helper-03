"""화면과 같은 방식으로 WebSocket 에 붙어 회차를 시작해 본다 (가짜 음성인식, 30배속)."""
import json
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


def test_session_log(sample_cues, silence, monkeypatch, tmp_path):
    """회차 기록: 시작 정보 · 인식 요청(힌트 큐 번호 포함) · 추적 판단 · 끝이 JSONL 로 남고, 측정 도구로 다시 읽힌다."""
    from eval.metrics import read_records

    lines = [c for c in sample_cues if c.type == "dialogue"]
    monkeypatch.setattr(srv, "get_engine", lambda name: FakeSTT([c.text for c in lines[:3]]))
    monkeypatch.setattr(srv, "find_audio_file", lambda cue_path: cue_path)
    monkeypatch.setattr(srv, "load_wav", lambda path: silence)
    monkeypatch.setenv("HELPER_SPEED", "30")
    monkeypatch.setenv("HELPER_LOG_DIR", str(tmp_path))

    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "회차 1", "cue_file": "sample_cues.csv"})
        got, deadline = 0, time.time() + 10
        while time.time() < deadline and got < 3:
            got += ws.receive_json()["type"] == "position.update"
        ws.send_json({"type": "settings.update", "alert_threshold": 5})
        ws.send_json({"type": "session.end", "show_id": "회차 1"})

    [path] = list(tmp_path.glob("*_회차_1.jsonl"))
    deadline = time.time() + 5
    while time.time() < deadline and '"kind": "end"' not in path.read_text(encoding="utf-8"):
        time.sleep(0.05)                     # 인식 스레드가 끝나며 마지막 줄을 씀
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "start" and kinds[-1] == "end"
    assert rows[0]["cue_file"] == "sample_cues.csv" and rows[0]["stt"] == "fake"
    assert [r["cue"] for r in rows if r["kind"] == "step"][:3] == [c.id for c in lines[:3]]
    stt = [r for r in rows if r["kind"] == "stt"]
    assert stt[0]["hints"] and stt[0]["text"] == lines[0].text
    assert {"kind": "settings", "alert_threshold": 5}.items() <= next(r for r in rows if r["kind"] == "settings").items()
    assert [r["chunk_end"] for r in read_records(path)] == [r["chunk_end"] for r in stt]
