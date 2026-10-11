import pytest

from engine.aligner import Step
from engine.cue_loader import Cue
from engine.deviation import START_TYPE, DeviationDetector

CUE = Cue(1, 1, "dialogue", "", "가나다라마바")


def miss():
    return Step("miss", CUE, 30)


def move(cue_id=1):
    return Step("move", Cue(cue_id, cue_id, "dialogue", "", "x"), 90)


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
    back = d.update(move(7), 7, 10000)          # 4 → 7: 2큐 넘게 앞으로 = 누락
    assert back.deviation_type == "skip" and back.return_cue_id == 7 and back.since == 1000


@pytest.mark.parametrize("ret_idx, kind", [(5, "adlib"), (4, "adlib"), (2, "repeat"), (6, "skip")])
def test_return_type(ret_idx, kind):
    d = DeviationDetector(deviate_after_sec=1)
    d.update(move(), 4, 0)
    d.update(miss(), 4, 0)
    assert d.update(miss(), 4, 2000) is not None
    assert d.update(move(ret_idx), ret_idx, 3000).deviation_type == kind


def test_silence_and_song_do_not_trigger():
    d = DeviationDetector(deviate_after_sec=1)
    skip = Step("skip", CUE)
    for t in (0, 2000, 4000):
        assert d.update(skip, 0, t) is None
        assert d.update(miss(), 0, t, hold=True) is None
