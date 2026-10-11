"""엔진 → 화면 메시지. 기준: ui/src/protocol.ts (필드 이름·형식을 그대로 맞춘다)."""


def position_update(cue_id: int, confidence: float, latency_ms: int, transcript: str = "") -> dict:
    return {"type": "position.update", "cue_id": int(cue_id),
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "latency_ms": max(0, int(latency_ms)), "transcript": transcript}


def deviation_alert(deviation_type: str, since: int, return_cue_id: int | None) -> dict:
    assert deviation_type in ("skip", "repeat", "adlib")
    return {"type": "deviation.alert", "deviation_type": deviation_type, "since": int(since),
            "return_cue_id": None if return_cue_id is None else int(return_cue_id)}


def input_status(audio_level: float, segment: str) -> dict:
    assert segment in ("dialogue", "song")
    return {"type": "input.status", "audio_level": round(max(0.0, min(1.0, audio_level)), 2),
            "segment": segment}
