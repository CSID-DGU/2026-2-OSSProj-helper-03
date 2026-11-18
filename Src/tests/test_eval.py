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


def test_processing_order_follows_the_pipeline():
    """저장된 결과를 다시 돌릴 때 파이프라인과 같은 순서: 조각 순서, 늦게 와서 쓴 결과는 도착한 때, 버린 결과는 뺌."""
    from eval.metrics import processing_order
    recs = [{"chunk_end": 1.0, "proc_sec": 1.0},
            {"chunk_end": 2.0, "proc_sec": 2.5, "late": True, "late_used": True},   # 4.5초에 도착
            {"chunk_end": 3.0, "proc_sec": 1.0},
            {"chunk_end": 4.0, "proc_sec": 1.0},
            {"chunk_end": 4.5, "proc_sec": 9.0, "late": True}]                     # 늦어서 버림
    assert [r["chunk_end"] for r in processing_order(recs)] == [1.0, 3.0, 2.0, 4.0]
    seq = [{"chunk_end": 3.0, "proc_sec": 2.0}, {"chunk_end": 4.5, "proc_sec": 0.3}]  # 하나씩 보낸 기록은 조각 순서
    assert [r["chunk_end"] for r in processing_order(seq)] == [3.0, 4.5]


def test_exact_and_only_given_cues(sample_cues):
    """같은 큐 비율, 그리고 only 로 고른 큐를 말하는 동안만 세기 (숫자 대사만 볼 때)."""
    lines = [c for c in sample_cues if c.type in ("dialogue", "lyric")][:4]
    labels = [(i * 3.0, c.id) for i, c in enumerate(lines)]
    timeline = [(t + 2.0, cid) for t, cid in labels[1:]]          # 2초 늦게 따라감
    rep = evaluate(timeline, labels, sample_cues, end_sec=11.5)
    assert rep.accuracy == 1.0 and rep.exact == 0.5
    one = evaluate(timeline, labels, sample_cues, end_sec=11.5, only={lines[2].id})
    assert one.samples == 6 and one.reach == {lines[2].id: 2.0} and one.missed == 0


def test_unseen_counts_cues_jumped_over(sample_cues):
    """뒤 큐로 건너뛰어 화면에 한 번도 안 보인 큐 (missed 는 뒤 큐에 닿으면 지난 것으로 셈)."""
    lines = [c for c in sample_cues if c.type in ("dialogue", "lyric")][:4]
    labels = [(i * 3.0, c.id) for i, c in enumerate(lines)]
    rep = evaluate([(4.0, lines[1].id), (10.0, lines[3].id)], labels, sample_cues, end_sec=11.5)
    assert rep.unseen == 1 and rep.missed == 0


def test_suite_table(tmp_path, sample_cues):
    """세트 파일 하나로 묶음마다 위치 추적 · 이탈 감지 값을 모아 표를 만든다."""
    import json
    import shutil

    from conftest import SAMPLE_CSV
    from eval import suite

    lines = [c for c in sample_cues if c.type in ("dialogue", "lyric")][:4]
    shutil.copy(SAMPLE_CSV, tmp_path / "cues.csv")
    (tmp_path / "labels.txt").write_text("".join(f"{i * 3.0}\t{i * 3.0}\t{c.id}\n" for i, c in enumerate(lines)),
                                         encoding="utf-8")
    with open(tmp_path / "run.jsonl", "w", encoding="utf-8") as f:
        for i, c in enumerate(lines):
            f.write(json.dumps({"chunk_start": i * 3.0, "chunk_end": i * 3.0 + 3.0, "text": c.text, "proc_sec": 0.0},
                               ensure_ascii=False) + "\n")
    (tmp_path / "truth.json").write_text(json.dumps({"labels": "labels.txt", "deviations": [
        {"id": "X", "type": "skip", "return_cue_id": lines[3].id, "start_sec": 100.0, "end_sec": 100.0}]}),
        encoding="utf-8")
    (tmp_path / "set.json").write_text(json.dumps({"groups": [
        {"name": "정상", "cues": "cues.csv", "labels": "labels.txt", "runs": [{"results": "run.jsonl"}]},
        {"name": "정답 있음", "cues": "cues.csv", "runs": [{"results": "run.jsonl", "truth": "truth.json"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    plain, with_truth = suite.run(tmp_path / "set.json")
    assert plain["accuracy"] == 1.0 and plain["missed"] == plain["unseen"] == 0 and plain["false"] == 0 and plain["deviations"] == 0
    assert with_truth["deviations"] == 1 and with_truth["found"] == 0 and with_truth["accuracy"] == 1.0
    table = suite.markdown([plain, with_truth])
    assert "| 정상 | 1 |" in table and "0/1" in table
