"""엔진이 보내는 메시지가 화면의 ui/src/protocol.ts 정의와 같은 필드인지 확인 (규약이 바뀌면 여기서 깨진다)."""
import re

from conftest import SRC
from engine.protocol import deviation_alert, input_status, position_update


def ts_fields(interface: str) -> set[str]:
    src = (SRC / "ui" / "src" / "protocol.ts").read_text(encoding="utf-8")
    body = re.search(rf"export interface {interface} \{{(.*?)\n\}}", src, re.S).group(1)
    return set(re.findall(r"^\s+(\w+)\??:", body, re.M))


def test_position_update_fields():
    msg = position_update(845, 0.923, 1400.7, "빛이 다시")
    assert set(msg) == ts_fields("PositionUpdate")
    assert msg["type"] == "position.update" and msg["confidence"] == 0.92 and msg["latency_ms"] == 1400


def test_deviation_alert_fields():
    msg = deviation_alert("skip", 1_700_000_000_000, None)
    assert set(msg) == ts_fields("DeviationAlert")
    assert msg["return_cue_id"] is None


def test_input_status_fields():
    msg = input_status(1.7, "song")
    assert set(msg) == ts_fields("InputStatus")
    assert msg["audio_level"] == 1.0


def test_input_status_audio_position_is_optional():
    assert "audio_sec" not in input_status(0.5, "dialogue")
    assert input_status(0.5, "dialogue", 12.345)["audio_sec"] == 12.35
