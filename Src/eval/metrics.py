"""위치 추적 지표.

- 타임라인: 화면에 보이는 큐가 언제 바뀌었는지 [(시각초, 큐번호)]
- 정답 라벨: Audacity 라벨 내보내기 (시작초<TAB>끝초<TAB>큐번호), 큐마다 배우가 말을 시작한 시각

지표 (계획서 지표 정의 기준)
- ±1큐 정확도: 0.5초마다 화면 큐와 정답 큐를 비교, 추적 큐 순서로 1칸 이내면 정답
  (정답 시각에 음향 · 암전 큐가 진행 중이면 그 직전 추적 큐를 정답으로 본다)
- 도달 지연: 배우가 큐를 시작한 시각 → 화면이 그 큐(또는 그 뒤)를 처음 보여 준 시각
- 뒤로 감 · 큰 점프(3큐 이상): 화면이 흔들리는 정도
- 화면 안 보임: 휴대폰 자막에 한 번도 못 뜬 대사. 지금 줄에 더해 화면의 짧은 대사 묶어 보이기(지금 줄 바로 뒤 5음절 이하
  대사)와 지나간 줄 함께 띄우기(추적기가 지나친 줄 중 누락 근거가 없는 줄)로 뜨는 줄도 본 것으로 센다
"""
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from engine.cue_loader import TRACK_TYPES, Cue

# 화면 기준값 (ui/src/settings.ts 와 같게): 짧은 대사 묶어 보이기 음절과 줄 수, 지나간 줄 함께 띄우기 줄 수
SHORT_LINE_SYLLABLES, SHORT_LINE_MAX_GROUPED, PASSED_MAX_SHOWN = 5, 2, 2
SAID_WINDOW = 15.0   # 지나간 줄로 띄운 때부터 이만큼(초) 앞까지 그 줄을 말했으면 맞게 띄운 것


def short_followers(cues: list[Cue], cue_id: int) -> list[int]:
    """ui/src/shortLines.ts 의 shortFollowers 와 같음: 그 큐 바로 뒤에 이어지는 짧은 대사 (음향, 암전, 안내 줄은 건너뜀)."""
    at = next((i for i, c in enumerate(cues) if c.id == cue_id), None)
    out: list[int] = []
    for c in cues[at + 1:] if at is not None else []:
        if len(out) >= SHORT_LINE_MAX_GROUPED:
            break
        if c.type in ("sound", "blackout", "notice"):
            continue
        if c.type != "dialogue" or len(re.findall(r"[가-힣]", c.text)) > SHORT_LINE_SYLLABLES:
            break
        out.append(c.id)
    return out


def read_records(path) -> list[dict]:
    """저장된 인식 결과 JSONL. 회차 기록(engine/session_log.py)이면 인식 요청(kind=stt) 줄만."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return [r for r in rows if r.get("kind", "stt") == "stt" and "chunk_end" in r]


def processing_order(records: list[dict]) -> list[dict]:
    """저장된 인식 결과를 파이프라인이 처리한 순서로: 조각 순서대로, 늦게 와서 쓴 결과(late_used)는 도착한 때에
    끼워 넣고, 늦어서 버린 결과는 뺀다 (하나씩 보낸 기록 · 늦은 결과를 버리던 예전 기록도 그대로 맞음)."""
    done = lambda r: r["chunk_end"] + r.get("proc_sec", 0.0)   # noqa: E731
    normal = sorted((r for r in records if not r.get("late")), key=lambda r: r["chunk_end"])
    late = sorted((r for r in records if r.get("late_used")), key=done)
    out, t, i = [], 0.0, 0
    for r in normal:
        t = max(t, done(r))                  # 이 결과를 처리한 때 (앞 조각보다 먼저일 수 없음)
        while i < len(late) and done(late[i]) <= t:
            out.append(late[i])
            i += 1
        out.append(r)
    return out + late[i:]


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
    exact: float = 0.0              # 화면 큐가 정답 큐와 정확히 같은 비율
    unseen: int = 0                 # 화면에 한 번도 안 보인 큐 (뒤 큐로 건너뛰어 지나감. missed 는 뒤 큐에 닿으면 지난 것으로 셈)
    screen_unseen: int = 0          # 휴대폰 자막에 한 번도 못 뜬 대사 (짧은 대사 묶어 보이기와 지나간 줄 함께 띄우기까지 넣고 셈)
    wrong_passed: int = 0           # 지나간 줄로 띄웠는데 그 무렵(SAID_WINDOW 초 안) 말하지 않은 줄


def evaluate(timeline: list[tuple[float, int]], labels: list[tuple[float, int]], cues: list[Cue],
             end_sec: float, step: float = 0.5, only: set[int] | None = None,
             passed: list[tuple[float, list[int]]] | None = None) -> Report:
    """only = 이 큐들을 말하는 동안만 센다 (예: 숫자가 든 대사만). 뒤로 간 횟수 · 큰 점프는 전체로 센다.
    passed = 지나간 줄 함께 띄우기로 화면에 간 줄 [(시각초, [큐번호])] (eval/run_eval.replay 의 passed)."""
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

    hit = total = same = 0
    typed = {"dialogue": [0, 0], "lyric": [0, 0]}
    t = labels[0][0] if labels else 0.0
    while t <= end_sec:
        k = bisect_right(lab_t, t) - 1
        truth = tracked_at_or_before(labels[k][1]) if k >= 0 else None
        s = shown(t)
        if truth is not None and s in idx and (only is None or truth in only):
            ok = abs(idx[truth] - idx[s]) <= 1
            total += 1
            hit += ok
            same += truth == s
            typed[ctype[truth]][0] += ok
            typed[ctype[truth]][1] += 1
        t += step

    reach = {}
    shown_from_start = [(0.0, start_id)] + list(timeline)   # 화면은 시작부터 첫 추적 큐를 보여 준다
    for t0, cid in labels:
        if cid not in idx or (only is not None and cid not in only):
            continue
        first = next((t for t, c in shown_from_start if c in idx and idx[c] >= idx[cid] and t >= t0 - 1.0), None)
        if first is not None:
            reach[cid] = max(0.0, first - t0)
    delays = sorted(reach.values())
    labelled = [cid for _, cid in labels if cid in idx and (only is None or cid in only)]

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

    on_screen = {start_id} | {c for _, c in timeline}
    seen = on_screen | {f for c in on_screen for f in short_followers(cues, c)}
    wrong = 0
    for t, ids in passed or []:
        for x in ids[-PASSED_MAX_SHOWN:]:          # 화면은 지금 줄에 가까운 줄부터 PASSED_MAX_SHOWN 줄까지
            seen.add(x)
            wrong += not any(c == x and t - SAID_WINDOW <= t0 <= t + 0.5 for t0, c in labels)

    return Report(
        accuracy=hit / total if total else 0.0,
        by_type={k: (v[0] / v[1] if v[1] else 0.0) for k, v in typed.items()},
        reach_median=pct(0.5), reach_p90=pct(0.9),
        missed=len(labelled) - len(reach), back=back, big_jumps=big, samples=total, reach=reach,
        exact=same / total if total else 0.0, unseen=len(set(labelled) - on_screen),
        screen_unseen=len(set(labelled) - seen), wrong_passed=wrong)
