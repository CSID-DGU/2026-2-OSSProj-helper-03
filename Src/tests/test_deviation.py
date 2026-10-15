import time

import pytest
from conftest import FakeSTT

from engine.aligner import Step
from engine.cue_loader import Cue
from engine.deviation import BASELINE, START_TYPE, DeviationDetector
from engine.pipeline import Pipeline

CUE = Cue(1, 1, "dialogue", "", "가나다라마바")
LINES = tuple(Cue(i, i, "dialogue", "", f"지나친 대사 {i}번") for i in (90, 91, 92))


def miss(status="miss"):
    return Step(status, CUE, 30)


def move(cue_id=1, skipped=0, again=False, ctype="dialogue"):
    return Step("move", Cue(cue_id, cue_id, ctype, "", "x"), 90, skipped=LINES[:skipped], again=again)


def quiet():
    return Step("skip", CUE)


def test_no_alert_before_time():
    d = DeviationDetector(deviate_after_sec=6)
    assert d.update(miss(), 0, 0) is None
    assert d.update(miss(), 0, 3000) is None   # 3초: 아직


def test_alert_after_time_then_return_with_type():
    d = DeviationDetector(deviate_after_sec=6)
    d.update(move(), 4, 0)                      # 마지막으로 맞은 위치 = 4
    d.update(miss(), 4, 1000)
    start = d.update(miss(), 4, 7000)
    assert start and start.deviation_type == START_TYPE and start.return_cue_id is None
    assert start.since == 1000
    assert d.update(miss(), 4, 9000) is None    # 이탈 중에는 다시 안 보냄
    back = d.update(move(7, skipped=2), 7, 10000)   # 안 들린 대사 2개를 지나쳐 돌아옴 = 누락
    assert back.deviation_type == "skip" and back.return_cue_id == 7 and back.since == 1000


@pytest.mark.parametrize("ret_idx, skipped, kind", [(5, 0, "adlib"), (4, 0, "adlib"), (2, 0, "repeat"),
                                                    (6, 2, "skip"), (6, 0, "adlib")])
def test_return_type(ret_idx, skipped, kind):
    d = DeviationDetector(deviate_after_sec=1)
    d.update(move(), 4, 0)
    d.update(miss(), 4, 0)
    assert d.update(miss(), 4, 2000) is not None
    assert d.update(move(ret_idx, skipped), ret_idx, 3000).deviation_type == kind


def test_silence_and_song_do_not_trigger():
    d = DeviationDetector(deviate_after_sec=1)
    for t in (0, 2000, 4000):
        assert d.update(quiet(), 0, t) is None
        assert d.update(miss(), 0, t, hold=True) is None


def test_states():
    d = DeviationDetector(deviate_after_sec=2)
    assert d.state == "normal"
    d.update(miss(), 0, 0)
    assert d.state == "suspect"
    d.update(miss("lost"), 0, 1000)
    assert d.state == "searching"
    d.update(miss("lost"), 0, 2500)
    assert d.state == "deviating"
    d.update(move(2), 1, 3000)
    assert d.state == "normal"
    d.update(miss(), 1, 4000, hold=True)
    assert d.state == "song"


def test_silence_clears_suspicion():
    """말이 끊긴 사이는 이탈 시간에 넣지 않는다: 의심 → 4초 넘게 조용 → 입력 없음 → 다시 처음부터."""
    d = DeviationDetector(deviate_after_sec=3, silence_sec=4)
    d.update(miss(), 0, 0)
    d.update(miss(), 0, 1000)
    for t in range(2000, 7000, 1000):
        assert d.update(quiet(), 0, t) is None
    assert d.state == "no_input"
    assert d.update(miss(), 0, 7000) is None    # 1차 감지기라면 0초부터 7초 = 이탈로 봤을 것
    assert d.state == "suspect" and d.since == 7000


def test_quiet_level_tick_sets_no_input():
    d = DeviationDetector(silence_sec=4)
    d.update(miss(), 0, 0)
    for t in range(0, 6000, 1000):
        d.tick(t, 0.0)
    assert d.state == "no_input" and d.since is None
    d.tick(7000, 0.5)                           # 소리가 다시 들어와도 다음 인식까지 상태는 그대로
    assert d.state == "no_input"


def test_tick_does_not_end_deviation():
    d = DeviationDetector(deviate_after_sec=1, silence_sec=2)
    d.update(miss(), 0, 0)
    assert d.update(miss(), 0, 1000) is not None
    for t in range(1000, 6000, 1000):
        d.tick(t, 0.0)
    assert d.state == "deviating"               # 복귀 알림은 대본과 다시 맞을 때만


def test_skip_without_deviation_alerts_once_with_return_cue():
    d = DeviationDetector()
    d.update(move(1), 0, 0)
    alert = d.update(move(5, skipped=2), 4, 1500)
    assert alert.deviation_type == "skip" and alert.return_cue_id == 5 and alert.since == 0
    assert d.state == "normal"
    assert d.update(move(6), 5, 3000) is None


def test_one_unheard_line_is_not_a_skip():
    d = DeviationDetector()
    d.update(move(1), 0, 0)
    assert d.update(move(4, skipped=1), 3, 1500) is None


def test_skip_into_song_alerts_but_catching_up_after_song_does_not():
    d = DeviationDetector()
    d.update(move(1), 0, 0)
    alert = d.update(move(5, skipped=2, ctype="lyric"), 4, 1500, hold=True)   # 대사 두 줄을 건너뛰고 노래로
    assert alert and alert.deviation_type == "skip"
    d.update(move(6, ctype="lyric"), 5, 3000, hold=True)
    assert d.update(move(10, skipped=3), 9, 4500) is None    # 노래에서 나올 때 따라잡는 이동은 누락이 아님


def test_repeat_back_to_heard_line():
    d = DeviationDetector()
    d.update(move(5), 5, 0)
    alert = d.update(move(3, again=True), 3, 1500)
    assert alert.deviation_type == "repeat" and alert.return_cue_id == 3
    d.update(move(6), 6, 3000)
    assert d.update(move(5, again=False), 5, 4500) is None   # 들은 적 없는 큐로 돌아감 = 추적기 보정


def test_baseline_types_by_distance():
    d = DeviationDetector(**BASELINE)
    d.update(move(), 4, 0)
    assert d.update(move(8, skipped=3), 8, 1000) is None     # 1차 감지기는 이탈 없이는 알림 없음
    d.update(miss(), 8, 2000)
    assert d.update(miss(), 8, 8000) is not None
    assert d.update(move(11), 11, 9000).deviation_type == "skip"


def test_lyric_like_miss_counts_as_song():
    """현재 큐는 대사인데 들린 말이 가사와 꽤 비슷하면 노래가 시작된 것으로 보고 알림을 보류한다."""
    d = DeviationDetector(deviate_after_sec=1)
    lyric = Cue(50, 50, "lyric", "", "x")
    for t in (0, 1500, 3000):
        assert d.update(Step("miss", CUE, 62, lyric), 0, t) is None
    assert d.state == "song"
    assert d.update(Step("miss", CUE, 40, lyric), 0, 4500) is None   # 가사와도 안 비슷하면 다시 의심
    assert d.state == "suspect"


def run_pipeline(cues, audio, texts):
    msgs = []
    pipe = Pipeline(cues, audio, FakeSTT(texts), msgs.append, speed=30)
    pipe.start()
    pipe.source.done.wait(timeout=10)
    time.sleep(0.3)
    pipe.stop()
    pipe.join(timeout=5)
    return [m for m in msgs if m["type"] == "deviation.alert"], pipe


def test_pipeline_skip_is_one_alert_with_return_cue(sample_cues, silence):
    """대사 두 줄을 건너뛰면 기다리지 않고 복귀 큐가 채워진 누락 알림 하나만 간다."""
    lines = [c for c in sample_cues if c.type == "dialogue"]
    alerts, pipe = run_pipeline(sample_cues, silence, [lines[0].text, lines[1].text, lines[4].text, lines[5].text])
    assert [(a["deviation_type"], a["return_cue_id"]) for a in alerts] == [("skip", lines[4].id)]
    assert pipe.detector.state in ("normal", "no_input")


def test_pipeline_in_order_has_no_alert(sample_cues, silence):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    alerts, _ = run_pipeline(sample_cues, silence, [c.text for c in lines[:8]])
    assert alerts == []


def test_passing_unheard_lines_after_long_gap_is_not_a_skip():
    """오래 아무것도 안 맞다가 앞으로 가면, 인식이 놓쳤을 수 있어 누락으로 보지 않는다."""
    d = DeviationDetector(skip_recent_sec=10)
    d.update(move(1), 0, 0)
    assert d.update(move(5, skipped=2), 4, 30000) is None


def test_near_miss_on_current_line_is_not_evidence():
    """인식이 조금 틀려 점수가 기준보다 약간 낮아도, 가리킨 곳이 현재 · 다음 큐면 이탈로 세지 않는다."""
    d = DeviationDetector(deviate_after_sec=1)
    nxt = Cue(2, 2, "dialogue", "", "x")
    for t in (0, 1500, 3000):
        assert d.update(Step("miss", CUE, 62, nxt), 0, t) is None
    assert d.state == "normal"
    far = Cue(9, 9, "dialogue", "", "x")
    d.update(Step("miss", CUE, 62, far), 0, 4500)
    assert d.state == "suspect"
