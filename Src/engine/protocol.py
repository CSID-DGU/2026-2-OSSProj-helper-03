"""엔진 → 화면 메시지. 기준: ui/src/protocol.ts (필드 이름·형식을 그대로 맞춘다)."""


def position_update(cue_id: int, confidence: float, latency_ms: int, transcript: str = "") -> dict:
    return {"type": "position.update", "cue_id": int(cue_id),
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "latency_ms": max(0, int(latency_ms)), "transcript": transcript}


def deviation_alert(deviation_type: str, since: int, return_cue_id: int | None) -> dict:
    assert deviation_type in ("skip", "repeat", "adlib")
    return {"type": "deviation.alert", "deviation_type": deviation_type, "since": int(since),
            "return_cue_id": None if return_cue_id is None else int(return_cue_id)}


def engine_error(message: str, during: str) -> dict:
    """화면이 알아야 할 엔진 오류. during = session.start(회차를 못 엶) / recognize(음성인식이 계속 실패)."""
    assert during in ("session.start", "recognize")
    return {"type": "engine.error", "message": str(message), "during": during}


def input_status(audio_level: float, segment: str, audio_sec: float | None = None) -> dict:
    """audio_sec: 녹음 재생 회차에서 엔진이 재생 중인 위치(초). 화면이 같은 녹음을 맞춰 틀 때 쓴다 (그 외에는 안 보냄)."""
    assert segment in ("dialogue", "song")
    msg = {"type": "input.status", "audio_level": round(max(0.0, min(1.0, audio_level)), 2), "segment": segment}
    if audio_sec is not None:
        msg["audio_sec"] = round(audio_sec, 2)
    return msg
