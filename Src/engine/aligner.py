"""④ 위치 추적: 대본을 이어 붙인 자모 글자열 + 큐 경계표 위에서 현재 위치를 따라간다.

- 짧은 인식 결과("거야" "뭐야")는 버린다 (min_jamo)
- 현재 위치 근처 [-back, +ahead] 큐만 본다 → 반복 후렴 · 짧은 글자 가짜 일치를 줄임
- 앞으로 1~2큐는 바로 이동, 그보다 큰 이동은 같은 곳이 연속으로 나와야 이동
  (긴 문장이 아주 잘 맞으면 앞으로 크게 가도 바로 이동)
- 몇 번 연속 안 맞으면 '놓침' → 현재 위치부터 대본 끝까지 다시 찾는다

기준값은 1차 데이터 실험의 추천값 (accept 65, ahead 15, strong 85).
2차 개선 (사람 정답 라벨로 측정, eval/run_eval.py):
- 맞은 구간의 끝을 현재 위치로 (anchor="end") — 한 조각에 큐가 여러 개 들어 있을 때 덜 늦음
- 한 번에 4큐까지 바로 이동 (small_step=4) — 짧은 대사가 빠르게 오가는 구간
- 놓친 상태에서는 가까운 범위부터 다시 찾기 (near_first) — 반복 후렴 · 같은 대사로 잘못 점프 방지
"""
from bisect import bisect_right
from dataclasses import dataclass

from rapidfuzz import fuzz

from .cue_loader import TRACK_TYPES, Cue, to_jamo

# 개선 전(엔진 서버 첫 버전) 설정. 평가(eval/run_eval.py --baseline)에서 비교용으로 쓴다.
BASELINE = dict(min_jamo=6, accept=65.0, back=3, ahead=15, small_step=2, confirm=2, lost_after=3,
                strong=85.0, strong_jamo=10, anchor="mid", widen=0, near_first=0)


@dataclass
class Step:
    status: str            # skip / move / stay / pending / miss / lost
    cue: Cue               # 이 단계 뒤 현재 위치
    score: float = 0.0     # 0~100
    cand: Cue | None = None  # 이번 인식이 가리킨 큐 (받아들였는지와 별개)

    @property
    def matched(self) -> bool:
        """이번 인식이 현재 위치를 확인했거나 옮겼는가."""
        return self.status in ("move", "stay")

    @property
    def heard(self) -> bool:
        """판단할 만한 말소리였는가 (너무 짧은 글자·빈 결과가 아님)."""
        return self.status != "skip"


class Aligner:
    def __init__(self, cues: list[Cue], track_types=TRACK_TYPES, start_id: int | None = None,
                 min_jamo=6, accept=65.0, back=3, ahead=15, small_step=4, confirm=2, lost_after=3,
                 strong=85.0, strong_jamo=10, anchor="end", widen=0, near_first=1):
        self.items = [c for c in cues if c.type in track_types and c.jamo]
        if not self.items:
            raise ValueError("추적할 큐(대사·가사)가 없습니다.")
        self.starts, s = [], 0
        for c in self.items:
            self.starts.append(s)
            s += len(c.jamo)
        self.text = "".join(c.jamo for c in self.items)
        self.min_jamo, self.accept = min_jamo, accept
        self.back, self.ahead, self.small_step = back, ahead, small_step
        self.confirm, self.lost_after = confirm, lost_after
        self.strong, self.strong_jamo = strong, strong_jamo
        self.anchor = anchor          # 인식 글자가 맞은 구간의 어디를 현재 위치로 볼지: mid(가운데) / end(끝)
        self.widen = int(widen)       # 안 맞는 결과가 이어질 때마다 앞쪽 탐색 범위를 이만큼씩 넓힘
        self.near_first = int(near_first)  # 놓친 상태에서 먼저 가까운 범위를 찾고, 없을 때만 끝까지
        self.stale = 0                # 마지막으로 위치를 확인한 뒤 지난 인식 횟수 (빈 결과 포함)
        self.pos = 0
        if start_id is not None:
            self.jump_to(start_id)
        self.miss = 0
        self.pending: list[int] = []

    @property
    def current(self) -> Cue:
        return self.items[self.pos]

    @property
    def lost(self) -> bool:
        return self.miss >= self.lost_after

    def jump_to(self, cue_id: int) -> bool:
        """위치 맞추기 (오퍼레이터가 지정). 추적 대상이 아닌 큐면 그 앞의 추적 큐로."""
        idx = next((i for i, c in enumerate(self.items) if c.id == cue_id), None)
        if idx is None:
            return False
        self.pos, self.miss, self.pending, self.stale = idx, 0, [], 0
        return True

    def hint_cues(self, n_next: int = 3) -> list[Cue]:
        """대본 힌트: 현재 큐 + 다음 n 큐. 놓친 상태에서는 힌트에 묶이지 않게 비운다."""
        if self.lost:
            return []
        return self.items[self.pos:self.pos + 1 + n_next]

    def _search(self, t: str, lo: int, hi: int) -> tuple[int, float]:
        a = self.starts[lo]
        b = self.starts[hi] if hi < len(self.items) else len(self.text)
        al = fuzz.partial_ratio_alignment(t, self.text[a:b])
        if self.anchor == "end":   # 맞은 구간의 끝 = 배우가 방금 말한 곳 (한 조각에 큐가 여러 개일 때 덜 늦음)
            at = a + max(al.dest_start, al.dest_end - 1)
        else:
            at = a + (al.dest_start + al.dest_end) // 2
        return bisect_right(self.starts, at) - 1, al.score

    def update(self, text: str) -> Step:
        t = to_jamo(text)
        if len(t) < self.min_jamo:
            self.stale += 1
            return Step("skip", self.current)
        self.stale += 1
        far = max([self.pos] + self.pending)
        lo = max(0, self.pos - self.back)
        near_hi = min(len(self.items), far + self.ahead + self.widen * (self.stale - 1) + 1)
        if self.lost:   # 공연은 대체로 앞으로 가므로 현재 위치 조금 앞부터 끝까지
            idx, score = (-1, 0.0)
            if self.near_first:   # 반복 후렴 · 같은 대사가 있으면 가까운 쪽을 먼저
                idx, score = self._search(t, lo, near_hi)
            if score < self.accept:
                idx, score = self._search(t, lo, len(self.items))
        else:
            idx, score = self._search(t, lo, near_hi)
        cand = self.items[idx]
        if score < self.accept:
            self.miss += 1
            return Step("lost" if self.lost else "miss", self.current, score, cand)

        self.miss = 0
        d = idx - self.pos
        if 0 <= d <= self.small_step:                      # 자연스러운 진행
            self.pos, self.pending, self.stale = idx, [], 0
            return Step("move" if d else "stay", self.current, score, cand)
        if d > 0 and score >= self.strong and len(t) >= self.strong_jamo:   # 긴 문장이 확실히 맞음
            self.pos, self.pending, self.stale = idx, [], 0
            return Step("move", self.current, score, cand)
        # 큰 이동(뒤로 가거나 많이 건너뜀): 대기 후보와 같은 곳이거나 그 바로 뒤로 이어지면 인정
        self.pending = [p for p in self.pending if -1 <= idx - p <= self.small_step + 1] + [idx]
        if len(self.pending) >= self.confirm:
            self.pos, self.pending, self.stale = idx, [], 0
            return Step("move", self.current, score, cand)
        return Step("pending", self.current, score, cand)
