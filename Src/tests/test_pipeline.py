"""가짜 음성인식 + 30배속 재생으로 파이프라인 전체를 돌려 본다 (소리 · API 없이)."""
import time

import numpy as np
from conftest import FakeSTT

from engine.pipeline import Pipeline, implausible


def run(cues, audio, texts, **kw):
    msgs = []
    stt = FakeSTT(texts)
    pipe = Pipeline(cues, audio, stt, msgs.append, speed=30, **kw)
    pipe.start()
    pipe.source.done.wait(timeout=10)     # 녹음 끝까지
    time.sleep(0.3)                        # 마지막 인식 처리
    pipe.stop()
    pipe.join(timeout=5)
    return msgs, stt


def test_status_continues_after_audio_ends(sample_cues):
    msgs = []
    pipe = Pipeline(sample_cues, np.zeros(16000 * 3, dtype="float32"), FakeSTT([]), msgs.append, speed=30)
    pipe.start()
    pipe.source.done.wait(timeout=5)
    time.sleep(2.2)                        # 녹음이 끝난 뒤에도 1초마다 상태가 와야 화면이 '응답 없음'을 띄우지 않음
    pipe.stop()
    pipe.join(timeout=5)
    after = [m for m in msgs if m["type"] == "input.status" and m["audio_level"] == 0]
    assert len(after) >= 2


def of(msgs, kind):
    return [m for m in msgs if m["type"] == kind]


def test_follows_and_sends_status(sample_cues, silence):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    msgs, stt = run(sample_cues, silence, [c.text for c in lines[:5]])
    pos = of(msgs, "position.update")
    assert [m["cue_id"] for m in pos] == [c.id for c in lines[:5]]
    assert all(0 <= m["confidence"] <= 1 for m in pos)
    assert of(msgs, "input.status")                       # 상태 메시지가 간다
    assert stt.hints_seen[0] and stt.hints_seen[0][0]     # 대본 힌트가 엔진에 들어간다


def test_deviation_start_and_return(sample_cues, silence):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    off = ["아 오늘 비 진짜 많이 오네 여러분", "근데 이 차 너무 뜨거운데 정말로", "잠깐만 내가 무슨 말 하려고 했지"]
    texts = [lines[0].text, lines[1].text] + off + [lines[4].text]
    msgs, _ = run(sample_cues, silence, texts, deviate_after=0.1)
    alerts = of(msgs, "deviation.alert")
    assert len(alerts) == 2
    assert alerts[0]["return_cue_id"] is None
    assert alerts[1]["return_cue_id"] == lines[4].id and alerts[1]["since"] == alerts[0]["since"]
    assert alerts[1]["deviation_type"] == "skip"           # 2번째 줄 → 5번째 줄 = 건너뜀


def test_implausible_filter():
    assert implausible("가" * 30, "", 3)                   # 3초에 30음절
    assert implausible("내 가방", "내 가방", 3)              # 직전과 똑같음
    assert implausible("아 아 아 아", "", 3)                 # 같은 말 반복
    assert not implausible("빛이 다시 돌아올 거예요", "", 3)
