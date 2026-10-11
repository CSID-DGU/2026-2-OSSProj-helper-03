"""평가 지표 계산 확인 (샘플 대본 + 손으로 만든 라벨 · 타임라인)."""
from eval.metrics import evaluate


def test_perfect_timeline_scores_full(sample_cues):
    lines = [c for c in sample_cues if c.type in ("dialogue", "lyric")][:5]
    labels = [(i * 3.0, c.id) for i, c in enumerate(lines)]
    timeline = [(t + 0.5, cid) for t, cid in labels[1:]]          # 0.5초 늦게 따라감
    rep = evaluate(timeline, labels, sample_cues, end_sec=14.5)
    assert rep.accuracy == 1.0                                   # 1칸 이내라 모두 정답
    assert rep.reach_median == 0.5 and rep.missed == 0 and rep.back == 0


def test_stuck_timeline_scores_low_and_counts_missed(sample_cues):
    lines = [c for c in sample_cues if c.type == "dialogue"][:6]
    labels = [(i * 3.0, c.id) for i, c in enumerate(lines)]
    rep = evaluate([], labels, sample_cues, end_sec=17.5)         # 화면이 첫 큐에서 안 움직임
    assert rep.accuracy < 0.5 and rep.missed == 5


def test_sound_cue_counts_as_previous_tracked_cue(sample_cues):
    by_id = {c.id: c for c in sample_cues}
    assert by_id[110].type == "sound"
    labels = [(0.0, 109), (3.0, 110)]                             # 3초부터 음향 큐 진행 중
    rep = evaluate([(0.0, 109)], labels, sample_cues, end_sec=6.0)
    assert rep.accuracy == 1.0                                   # 음향 큐 동안은 109 를 보여 주면 정답
