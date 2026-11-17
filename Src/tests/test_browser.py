"""브라우저 소리 입력과 인터넷 서버 설정 (접속 코드, 입력 제한, 시간 제한, 동시 회차 수)."""
import threading
import time

import numpy as np
import pytest
from conftest import SAMPLE_CSV, FakeSTT
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import server.main as srv
from engine.audio_input import SR, PushSource, to_pcm16


def pcm(sec: float, value: float = 0.0) -> bytes:
    """브라우저가 보내는 것과 같은 16kHz 모노 PCM16."""
    return to_pcm16(np.full(int(round(sec * SR)), value, dtype="float32"))


def receive_until(ws, done, limit: int = 200) -> list[dict]:
    """done(받은 메시지 목록)이 참이 될 때까지 받는다. input.status 가 1초마다 오므로 오래 막히지 않는다."""
    got = []
    while len(got) < limit and not done(got):
        got.append(ws.receive_json())
    return got


def start_msg(show_id="t", **kw) -> dict:
    return {"type": "session.start", "show_id": show_id, "cue_file": "sample_cues.csv", **kw}


def test_push_source_feed():
    src = PushSource()
    th = threading.Thread(target=src.run)
    th.start()
    for _ in range(10):
        src.feed(pcm(0.1, 0.5))
    src.feed(b"\x01")                                         # 반 샘플은 버림
    deadline = time.time() + 2
    while time.time() < deadline and src.pos < 1.0:
        time.sleep(0.01)
    seg = src.segment(0, 1.0)
    assert len(seg) == SR and abs(float(seg.mean()) - 0.5) < 1e-3
    assert src.now_audio() == pytest.approx(1.0)
    src.stop()
    th.join(timeout=2)
    assert src.done.is_set() and src.level == 0.0
    src.feed(pcm(0.1))                                        # 끝난 뒤 온 소리는 버림
    assert src._q.empty()


def test_browser_session(sample_cues, monkeypatch):
    """브라우저가 보낸 큐 파일 내용과 소리로 회차를 돌린다 (서버 폴더의 큐 · 녹음을 찾지 않음)."""
    lines = [c for c in sample_cues if c.type == "dialogue"]
    monkeypatch.setattr(srv, "get_engine", lambda name: FakeSTT([c.text for c in lines[:3]]))
    monkeypatch.setattr(srv, "find_cue_file", lambda name: pytest.fail("서버 폴더에서 큐를 찾음"))

    got = []
    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(start_msg(cue_file="내 대본.csv", cue_csv=SAMPLE_CSV.read_text(encoding="utf-8"), input="browser"))
        # 3초 조각을 하나씩 보내고 결과를 받은 뒤 다음 조각을 보낸다. 한꺼번에 보내면 엔진은 실시간 입력에서
        # 밀린 조각으로 보고 최신 조각만 인식한다 (pipeline._chunk_loop). 실제 브라우저는 0.1초마다 보냄
        for _ in range(3):
            for _ in range(30):
                ws.send_bytes(pcm(0.1))
            got += receive_until(ws, lambda g: any(m["type"] == "position.update" for m in g))
        ws.send_json({"type": "session.end", "show_id": "t"})

    assert [m["cue_id"] for m in got if m["type"] == "position.update"] == [c.id for c in lines[:3]]


def test_bytes_without_session_are_ignored():
    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_bytes(pcm(0.1))                               # 회차 전 소리: 무시하고 연결 유지
        ws.send_json(start_msg(input="text"))
        assert receive_until(ws, lambda g: any(m["type"] == "input.status" for m in g))


def test_access_code(sample_cues, monkeypatch):
    monkeypatch.setenv("HELPER_ACCESS_CODE", "abc")
    with TestClient(srv.app) as client:
        with client.websocket_connect("/ws?code=xyz") as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
            assert e.value.code == 4401
        with client.websocket_connect("/ws?code=abc") as ws:
            ws.send_json(start_msg(input="text"))
            ws.send_json({"type": "test.say", "text": sample_cues[0].text})
            got = receive_until(ws, lambda g: any(m["type"] == "position.update" for m in g))
            assert got[-1]["type"] == "position.update"


def test_inputs_limited(monkeypatch):
    monkeypatch.setenv("HELPER_INPUTS", "browser,text")
    with TestClient(srv.app) as client:
        assert client.get("/health").json()["inputs"] == ["browser", "text"]
        with client.websocket_connect("/ws") as ws:
            ws.send_json(start_msg(input="file"))
            err = receive_until(ws, lambda g: any(m["type"] == "engine.error" for m in g))[-1]
    assert err["during"] == "session.start" and "file" in err["message"]


def test_time_limit(monkeypatch):
    monkeypatch.setenv("HELPER_MAX_SESSION_SEC", "0.3")
    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(start_msg(input="text"))
        err = receive_until(ws, lambda g: any(m["type"] == "engine.error" for m in g))[-1]
    assert err["during"] == "limit" and "0.3초" in err["message"]
    assert not srv._live


def test_max_sessions(monkeypatch):
    monkeypatch.setenv("HELPER_MAX_SESSIONS", "1")
    with TestClient(srv.app) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            a.send_json(start_msg("a", input="text"))
            receive_until(a, lambda g: any(m["type"] == "input.status" for m in g))
            b.send_json(start_msg("b", input="text"))
            err = receive_until(b, lambda g: any(m["type"] == "engine.error" for m in g))[-1]
            assert "다른 사람" in err["message"]
            a.send_json({"type": "session.end", "show_id": "a"})
    assert not srv._live
