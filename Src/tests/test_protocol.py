"""엔진이 보내는 메시지가 화면의 ui/src/protocol.ts 정의와 같은 필드인지 확인 (규약이 바뀌면 여기서 깨진다)."""
import re

from conftest import SRC
from engine.protocol import deviation_alert, input_status, position_update


def ts_fields(interface: str) -> tuple[set[str], set[str]]:
    """화면 정의의 (필수 필드, 선택 필드 name?:)."""
    src = (SRC / "ui" / "src" / "protocol.ts").read_text(encoding="utf-8")
    body = re.search(rf"export interface {interface} \{{(.*?)\n\}}", src, re.S).group(1)
    fields = re.findall(r"^\s+(\w+)(\??):", body, re.M)
    return {n for n, opt in fields if not opt}, {n for n, opt in fields if opt}


def same_fields(msg: dict, interface: str) -> bool:
    """필수 필드는 모두 있고, 그 밖의 필드는 화면 정의의 선택 필드여야 한다."""
    need, opt = ts_fields(interface)
    return need <= set(msg) <= need | opt


def test_position_update_fields():
    msg = position_update(845, 0.923, 1400.7, "빛이 다시")
    assert same_fields(msg, "PositionUpdate")
    assert msg["type"] == "position.update" and msg["confidence"] == 0.92 and msg["latency_ms"] == 1400


def test_deviation_alert_fields():
    msg = deviation_alert("skip", 1_700_000_000_000, None)
    assert same_fields(msg, "DeviationAlert")
    assert msg["return_cue_id"] is None


def test_input_status_fields():
    msg = input_status(1.7, "song")
    assert same_fields(msg, "InputStatus")
    assert msg["audio_level"] == 1.0


def test_input_status_audio_position_is_optional():
    assert "audio_sec" not in input_status(0.5, "dialogue")
    assert input_status(0.5, "dialogue", 12.345)["audio_sec"] == 12.35


def test_engine_error_fields():
    """화면 protocol.ts 에 EngineError 가 있으면 필드를 맞춘다 (화면 쪽이 아직 없으면 건너뜀)."""
    import pytest
    from engine.protocol import engine_error
    src = (SRC / "ui" / "src" / "protocol.ts").read_text(encoding="utf-8")
    if "export interface EngineError" not in src:
        pytest.skip("화면 protocol.ts 에 EngineError 가 아직 없음")
    assert same_fields(engine_error("키 파일이 없음", "session.start"), "EngineError")
