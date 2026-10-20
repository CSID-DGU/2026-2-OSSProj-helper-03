"""위치 추적 지표.

- 타임라인: 화면에 보이는 큐가 언제 바뀌었는지 [(시각초, 큐번호)]
- 정답 라벨: Audacity 라벨 내보내기 (시작초<TAB>끝초<TAB>큐번호), 큐마다 배우가 말을 시작한 시각

지표 (계획서 지표 정의 기준)
- ±1큐 정확도: 0.5초마다 화면 큐와 정답 큐를 비교, 추적 큐 순서로 1칸 이내면 정답
  (정답 시각에 음향 · 암전 큐가 진행 중이면 그 직전 추적 큐를 정답으로 본다)
- 도달 지연: 배우가 큐를 시작한 시각 → 화면이 그 큐(또는 그 뒤)를 처음 보여 준 시각
- 뒤로 감 · 큰 점프(3큐 이상): 화면이 흔들리는 정도
"""
import json
from bisect import bisect_right
from dataclasses import dataclass, field

from engine.cue_loader import TRACK_TYPES, Cue


def read_records(path) -> list[dict]:
    """저장된 인식 결과 JSONL. 회차 기록(engine/session_log.py)이면 인식 요청(kind=stt) 줄만."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return [r for r in rows if r.get("kind", "stt") == "stt" and "chunk_end" in r]


def read_labels(path) -> list[tuple[float, int]]:
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[2].strip():
                out.append((float(parts[0]), int(parts[2].strip().lstrip("#"))))
    return sorted(out)


@dataclass
class Report:
    accuracy: float                 # ±1큐 정확도 (0~1)
    by_type: dict[str, float]       # dialogue / lyric 별 정확도
    reach_median: float | None      # 도달 지연 중앙값 (초)
    reach_p90: float | None
    missed: int                     # 끝까지 화면에 안 나온 큐 수
    back: int                       # 뒤로 간 횟수
    big_jumps: int                  # 3큐 이상 건너뛴 횟수
    samples: int
    reach: dict[int, float] = field(default_factory=dict)


def evaluate(timeline: list[tuple[float, int]], labels: list[tuple[float, int]], cues: list[Cue],
             end_sec: float, step: float = 0.5) -> Report:
    items = [c for c in cues if c.type in TRACK_TYPES and c.jamo]
    idx = {c.id: i for i, c in enumerate(items)}
    order = {c.id: c.order for c in cues}
    ctype = {c.id: c.type for c in items}
    tracked_orders = sorted((c.order, c.id) for c in items)

    def tracked_at_or_before(cue_id: int) -> int | None:
        """음향 · 암전 큐면 그 앞의 추적 큐로."""
        if cue_id in idx:
            return cue_id
        o = order.get(cue_id)
        if o is None:
            return None
        k = bisect_right([x for x, _ in tracked_orders], o) - 1
        return tracked_orders[k][1] if k >= 0 else None

    lab_t = [t for t, _ in labels]
    tl_t = [t for t, _ in timeline]
    start_id = items[0].id

    def shown(t: float) -> int:
        k = bisect_right(tl_t, t) - 1
        return timeline[k][1] if k >= 0 else start_id

    hit = total = 0
    typed = {"dialogue": [0, 0], "lyric": [0, 0]}
    t = labels[0][0] if labels else 0.0
    while t <= end_sec:
        k = bisect_right(lab_t, t) - 1
        truth = tracked_at_or_before(labels[k][1]) if k >= 0 else None
        s = shown(t)
        if truth is not None and s in idx:
            ok = abs(idx[truth] - idx[s]) <= 1
            total += 1
            hit += ok
            typed[ctype[truth]][0] += ok
            typed[ctype[truth]][1] += 1
        t += step

    reach = {}
    shown_from_start = [(0.0, start_id)] + list(timeline)   # 화면은 시작부터 첫 추적 큐를 보여 준다
    for t0, cid in labels:
        if cid not in idx:
            continue
        first = next((t for t, c in shown_from_start if c in idx and idx[c] >= idx[cid] and t >= t0 - 1.0), None)
        if first is not None:
            reach[cid] = max(0.0, first - t0)
    delays = sorted(reach.values())
    labelled = [cid for _, cid in labels if cid in idx]

    back = big = 0
    prev = idx.get(start_id, 0)
    for _, c in timeline:
        if c not in idx:
            continue
        i = idx[c]
        back += i < prev
        big += abs(i - prev) > 2
        prev = i

    def pct(p):
        return delays[min(len(delays) - 1, int(p * len(delays)))] if delays else None

    return Report(
        accuracy=hit / total if total else 0.0,
        by_type={k: (v[0] / v[1] if v[1] else 0.0) for k, v in typed.items()},
        reach_median=pct(0.5), reach_p90=pct(0.9),
        missed=len(labelled) - len(reach), back=back, big_jumps=big, samples=total, reach=reach)
