"""eval/latency.py: 도달 지연을 조각 대기 · 인식 · 나머지로 나눈다."""
import pytest

from eval.latency import breakdown


def test_breakdown_splits_reach_into_wait_proc_rest(sample_cues):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    a, b = lines[0], lines[1]
    labels = [(10.0, a.id), (20.0, b.id)]
    timeline = [(12.5, a.id), (23.0, b.id)]           # 화면이 바뀐 때 (재생 시계)
    records = [
        {"chunk_start": 8.0, "chunk_end": 11.0, "text": a.text, "proc_sec": 1.4},     # 12.4 에 답 → 12.5 화면
        {"chunk_start": 9.5, "chunk_end": 12.5, "text": "", "proc_sec": 2.0},         # 14.5: 화면보다 늦게 끝남
        {"chunk_start": 18.5, "chunk_end": 21.5, "text": b.text, "proc_sec": 1.3},    # 22.8 에 답 → 23.0 화면
        {"chunk_start": 20.0, "chunk_end": 23.0, "text": b.text, "error": "504"},     # 실패한 요청은 안 셈
    ]
    rows = {r["cue"]: r for r in breakdown(timeline, records, labels, sample_cues)}
    assert rows[a.id]["reach"] == pytest.approx(2.5)
    assert (rows[a.id]["wait"], rows[a.id]["proc"], rows[a.id]["rest"]) == pytest.approx((1.0, 1.4, 0.1))
    assert (rows[b.id]["wait"], rows[b.id]["proc"], rows[b.id]["rest"]) == pytest.approx((1.5, 1.3, 0.2))
