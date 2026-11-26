"""⑧ 송출 연동 (#46): 오퍼레이터 송출 → 오롯플래닛 신호 (index, emergence, blackout)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

import server.main as srv
from engine.output import LogChannel, OffChannel, Signal, cue_signal, make_channel, text_signal


def test_cue_signal_sends_line_number():
    """대사 · 가사 · 음향 · 안내 줄은 그 줄 번호(index), 암전 줄은 화면 끄기(blackout)."""
    assert cue_signal(103, "dialogue") == Signal("index", subtitle_idx=103)
    assert cue_signal(102, "sound") == Signal("index", subtitle_idx=102)
    assert cue_signal(7) == Signal("index", subtitle_idx=7)        # 유형을 모르면 번호 표시
    assert cue_signal(129, "blackout") == Signal("blackout")


def test_text_signal_and_data_fields():
    sig = text_signal("잠깐만요 바닥이 미끄러워요")
    assert sig.kind == "emergence"
    assert sig.data() == {"subtitle_idx": None, "rendered_text": "잠깐만요 바닥이 미끄러워요"}
    assert cue_signal(1).data() == {"subtitle_idx": 1, "rendered_text": None}


def test_make_channel(monkeypatch):
    monkeypatch.delenv("HELPER_OUTPUT", raising=False)
    assert isinstance(make_channel(), LogChannel)
    monkeypatch.setenv("HELPER_OUTPUT", "off")
    assert isinstance(make_channel(), OffChannel)
    with pytest.raises(ValueError, match="HELPER_OUTPUT=radio"):
        make_channel("radio")


def test_operator_sends_become_signals(sample_cues, monkeypatch, tmp_path):
    """대사 입력 회차에서 큐 송출 · 임시 자막 송출을 누르면 신호가 나가고 회차 기록에도 남는다."""
    channel = LogChannel()
    monkeypatch.setattr(srv, "make_channel", lambda: channel)
    monkeypatch.setenv("HELPER_LOG_DIR", str(tmp_path))
    blackout = next(c for c in sample_cues if c.type == "blackout")
    line = next(c for c in sample_cues if c.type == "dialogue")

    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "송출", "cue_file": "sample_cues.csv", "input": "text"})
        ws.send_json({"type": "cue.send", "cue_id": line.id})
        ws.send_json({"type": "cue.send", "cue_id": blackout.id})
        ws.send_json({"type": "subtitle.send", "text": "잠깐만요", "source": "manual"})
        ws.send_json({"type": "subtitle.send", "text": "  ", "source": "manual"})      # 빈 글자는 안 보냄
        ws.send_json({"type": "cue.send", "cue_id": "다음"})                           # 번호가 아니면 무시
        deadline = time.time() + 5
        while time.time() < deadline and len(channel.sent) < 3:
            time.sleep(0.02)
        ws.send_json({"type": "session.end", "show_id": "송출"})

    assert channel.sent == [Signal("index", subtitle_idx=line.id), Signal("blackout"),
                            Signal("emergence", rendered_text="잠깐만요")]
    [path] = list(tmp_path.glob("*_송출.jsonl"))
    deadline = time.time() + 3
    while time.time() < deadline and '"kind": "end"' not in path.read_text(encoding="utf-8"):
        time.sleep(0.05)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [(r["signal"], r["subtitle_idx"], r["rendered_text"]) for r in rows if r["kind"] == "signal"] == [
        ("index", line.id, None), ("blackout", None, None), ("emergence", None, "잠깐만요")]


def test_channel_failure_does_not_stop_session(sample_cues, monkeypatch):
    """송출 채널이 실패해도 연결과 추적은 계속된다 (오퍼레이터는 기존 방식으로 송출)."""
    class Broken:
        def send(self, signal):
            raise ConnectionError("채널 끊김")

    monkeypatch.setattr(srv, "make_channel", lambda: Broken())
    line = next(c for c in sample_cues if c.type == "dialogue")
    with TestClient(srv.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "show_id": "t", "cue_file": "sample_cues.csv", "input": "text"})
        ws.send_json({"type": "cue.send", "cue_id": line.id})
        ws.send_json({"type": "test.say", "text": line.text})
        got, deadline = [], time.time() + 5
        while time.time() < deadline and not any(m["type"] == "position.update" for m in got):
            got.append(ws.receive_json())
        ws.send_json({"type": "session.end", "show_id": "t"})
    assert any(m["type"] == "position.update" and m["cue_id"] == line.id for m in got)
