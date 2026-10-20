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
3차 (이탈 감지와 함께):
- 놓친 뒤 다시 찾는 범위를 현재 장면 + 다음 장면으로 제한 (큐에 막 · 장 정보가 없으면 lost_window 큐)
- 앞으로 2큐 넘게 이동할 때, 건너뛴 대사 중 최근 인식 글자에 없는 것을 Step.skipped 로 알려 줌 (누락 근거)
- 들었던 큐를 기억해 두고, 그 큐로 되돌아가면 Step.again (반복 근거)
- 멀리 있는 큐와 가까운 큐가 똑같이 맞으면 가까운 쪽 (같은 대사가 대본에 두 번 있을 때 잘못 점프 방지, prefer_near)
4차 (큰 이동 확인 강화, 인식 글자의 소리 끝 시각을 같이 받음):
- 큰 이동 후보는 pending_sec 초 안에 다시 나와야 인정 — 전에는 1분 넘게 지난 후보가 남아 있다가
  엉뚱한 말 한 번으로 10큐 넘게 튀었다 (엉뚱한 대본 시험에서 5큐 넘는 이동 6번 → 0번)
- 지나칠 대사를 사람이 말할 수 있는 빠르기(pace 음절/초)보다 빨리 지나가면 긴 문장 즉시 이동을 막고
  확인을 한 번 더 받는다. 뒤처졌다 따라잡는 이동은 그대로, 몇 초 만에 대본을 크게 건너뛰는 이동만 신중하게
  (반복 후렴이 10큐 뒤 같은 가사와 100점으로 맞아 튀던 것을 막음)
- 소리가 겹치는 조각(3초 조각을 1.5초마다)은 확인 한 번으로 치는 방법도 해 봤지만 반복 감지를 놓쳐서 뺐다
- 짧은 대사(1~3음절, 글자가 적어 맞춰 볼 수 없음) 넘기기도 해 봤다: 방금 맞은 뒤 짧은 말이 들리고 다음 큐가
  짧은 대사면 한 칸. 짧은 대사가 몰린 구간의 대사 정확도는 그대로였고, 애드리브 구간에서 앞서 가서 뺐다
"""
import inspect
import re
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from itertools import accumulate

from rapidfuzz import fuzz

from .cue_loader import TRACK_TYPES, Cue, to_jamo

# 개선 전(엔진 서버 첫 버전) 설정. 평가(eval/run_eval.py --baseline)에서 비교용으로 쓴다.
BASELINE = dict(min_jamo=6, accept=65.0, back=3, ahead=15, small_step=2, confirm=2, lost_after=3,
                strong=85.0, strong_jamo=10, anchor="mid", widen=0, near_first=0, scene_limit=0, lost_window=0,
                prefer_near=0, pending_sec=0.0, pace=0.0)


@dataclass
class Step:
    status: str            # skip / move / stay / pending / miss / lost
    cue: Cue               # 이 단계 뒤 현재 위치
    score: float = 0.0     # 0~100
    cand: Cue | None = None  # 이번 인식이 가리킨 큐 (받아들였는지와 별개)
    skipped: tuple[Cue, ...] = ()  # 이번 이동으로 지나친 대사 중 최근 인식 글자에 없던 것 (누락 근거)
    again: bool = False    # 이미 들었던 앞 큐로 되돌아감 (반복 근거)

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
                 strong=85.0, strong_jamo=10, anchor="end", widen=0, near_first=1,
                 scene_limit=1, lost_window=30, recent=3, heard_score=60.0, prefer_near=1,
                 pending_sec=9.0, pace=8.0):
        self.items = [c for c in cues if c.type in track_types and c.jamo]
        if not self.items:
            raise ValueError("추적할 큐(대사·가사)가 없습니다.")
        self.starts, s = [], 0
        for c in self.items:
            self.starts.append(s)
            s += len(c.jamo)
        self.text = "".join(c.jamo for c in self.items)
        # 큐까지 누적 음절 수 (지나친 대사를 말하는 데 드는 최소 시간 계산용)
        self.syl = [0, *accumulate(len(re.findall(r"[가-힣]", c.text)) for c in self.items)]
        self.min_jamo, self.accept = min_jamo, accept
        self.back, self.ahead, self.small_step = back, ahead, small_step
        self.confirm, self.lost_after = confirm, lost_after
        self.strong, self.strong_jamo = strong, strong_jamo
        self.anchor = anchor          # 인식 글자가 맞은 구간의 어디를 현재 위치로 볼지: mid(가운데) / end(끝)
        self.widen = int(widen)       # 안 맞는 결과가 이어질 때마다 앞쪽 탐색 범위를 이만큼씩 넓힘
        self.near_first = int(near_first)  # 놓친 상태에서 먼저 가까운 범위를 찾고, 없을 때만 끝까지
        self.lost_hi = self._lost_ranges(int(scene_limit), int(lost_window))
        self.recent: deque[str] = deque(maxlen=int(recent))  # 최근 인식 글자 (자모) — 지나친 대사를 들었는지 확인
        self.heard_score = heard_score
        self.heard: set[int] = set()  # 들었던 큐 (위치로 확인했거나, 지나칠 때 최근 인식 글자에 있던 것)
        self.prefer_near = int(prefer_near)
        self.pending_sec = pending_sec  # 큰 이동 후보는 이 시간(초) 안에 다시 나와야 인정 (0 = 끝없이 기다림)
        self.pace = pace                # 사람이 말할 수 있는 가장 빠른 속도 (음절/초). 0 = 안 봄
        self.clock = 0.0              # 마지막 인식 글자의 소리 끝 시각
        self.at: float | None = None  # 마지막으로 위치를 확인한 소리 시각
        self.stale = 0                # 마지막으로 위치를 확인한 뒤 지난 인식 횟수 (빈 결과 포함)
        self.pos = 0
        self.pending: list[tuple[int, float]] = []   # 큰 이동 후보 (위치, 소리 끝 시각), 나온 순서
        if start_id is not None:
            self.jump_to(start_id)
        self.miss = 0

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
        self.pos, self.miss, self.pending, self.stale, self.at = idx, 0, [], 0, self.clock
        return True

    def _lost_ranges(self, scene_limit: int, window: int) -> list[int]:
        """놓친 상태에서 다시 찾을 범위의 끝 (위치별). 같은 장면 + 다음 장면까지, 장면 정보가 없으면 window 큐."""
        n = len(self.items)
        if scene_limit and all(c.scene for c in self.items):
            scenes = list(dict.fromkeys(c.scene for c in self.items))
            last = {c.scene: i for i, c in enumerate(self.items)}   # 장면마다 마지막 큐
            nxt = {sc: scenes[min(k + 1, len(scenes) - 1)] for k, sc in enumerate(scenes)}
            return [last[nxt[c.scene]] + 1 for c in self.items]
        if window:
            return [min(n, i + window + 1) for i in range(n)]
        return [n] * n

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

    def _too_fast(self, idx: int) -> bool:
        """현재 위치 → idx 사이 대사를, 마지막 확인 뒤 지난 시간 동안 사람이 다 말할 수 없었나."""
        if not self.pace or self.at is None or idx <= self.pos + 1:
            return False
        need = (self.syl[idx] - self.syl[self.pos + 1]) / self.pace
        return self.clock - self.at < need

    def update(self, text: str, end: float | None = None) -> Step:
        """인식 글자 하나를 반영. end = 그 글자 소리의 끝 시각 (초). 안 주면 한 번에 1초씩 흐른 것으로 본다."""
        end = self.clock + 1.0 if end is None else end
        self.clock = end
        if self.pending_sec:   # 오래된 큰 이동 후보는 버린다 (한참 뒤 엉뚱한 말 한 번으로 튀지 않게)
            self.pending = [p for p in self.pending if end - p[1] <= self.pending_sec]
        t = to_jamo(text)
        if len(t) < self.min_jamo:
            self.stale += 1
            return Step("skip", self.current)
        self.stale += 1
        self.recent.append(t)
        far = max([self.pos] + [p for p, _ in self.pending])
        lo = max(0, self.pos - self.back)
        near_hi = min(len(self.items), far + self.ahead + self.widen * (self.stale - 1) + 1)
        if self.lost:   # 공연은 대체로 앞으로 가므로 현재 위치 조금 앞부터 끝까지
            idx, score = (-1, 0.0)
            if self.near_first:   # 반복 후렴 · 같은 대사가 있으면 가까운 쪽을 먼저
                idx, score = self._search(t, lo, near_hi)
            if score < self.accept:
                idx, score = self._search(t, lo, max(near_hi, self.lost_hi[self.pos]))
        else:
            idx, score = self._search(t, lo, near_hi)
        if self.prefer_near and not 0 <= idx - self.pos <= self.small_step:
            n_idx, n_score = self._search(t, self.pos, min(len(self.items), self.pos + self.small_step + 1))
            if n_score >= score:      # 가까운 곳도 똑같이 맞음 (같은 대사가 두 번) → 가까운 쪽
                idx, score = n_idx, n_score
        cand = self.items[idx]
        if score < self.accept:
            self.miss += 1
            return Step("lost" if self.lost else "miss", self.current, score, cand)

        self.miss = 0
        d = idx - self.pos
        fast = self._too_fast(idx)
        if 0 <= d <= self.small_step or (d > 0 and not fast and score >= self.strong and len(t) >= self.strong_jamo):
            # 자연스러운 진행 / 긴 문장이 확실히 맞음
            return self._move(idx, score, cand)
        # 큰 이동(뒤로 가거나 많이 건너뜀): 대기 후보와 같은 곳이거나 그 바로 뒤로 이어지면 인정.
        # 말할 수 없는 빠르기로 건너뛰면 한 번 더
        self.pending = [p for p in self.pending if -1 <= idx - p[0] <= self.small_step + 1] + [(idx, end)]
        if len(self.pending) >= self.confirm + fast:
            return self._move(idx, score, cand)
        return Step("pending", self.current, score, cand)

    def _move(self, idx: int, score: float, cand: Cue) -> Step:
        prev = self.pos
        again = idx < prev and idx in self.heard
        self.pos, self.pending, self.stale, self.at = idx, [], 0, self.clock
        skipped = []
        got = "".join(self.recent)
        for i in range(prev + 1, idx):        # 지나친 큐: 최근 인식 글자에 비슷한 부분이 있으면 들은 것으로
            c = self.items[i]
            if len(c.jamo) < self.min_jamo:   # 너무 짧은 큐는 판단 안 함
                continue
            if fuzz.partial_ratio(c.jamo, got) >= self.heard_score:
                if idx - prev <= self.small_step:   # 크게 건너뛴 이동은 잘못 튄 것일 수 있어 지나친 큐를 기억하지 않음
                    self.heard.add(i)
            elif c.type == "dialogue":
                skipped.append(c)
        self.heard.add(idx)
        return Step("move" if idx != prev else "stay", self.current, score, cand, tuple(skipped), again)


def parse_settings(text: str) -> dict:
    """'ahead=12, lost_window=20' → Aligner 설정 (.env 의 HELPER_ALIGN). 모르는 이름은 오류 (오타 방지)."""
    defaults = {k: p.default for k, p in inspect.signature(Aligner.__init__).parameters.items()
                if p.default is not inspect.Parameter.empty and k not in ("track_types", "start_id")}
    out = {}
    for kv in filter(None, (s.strip() for s in text.split(","))):
        k, sep, v = (s.strip() for s in kv.partition("="))
        if not sep or k not in defaults:
            raise ValueError(f"추적기 설정 '{kv}' 를 알 수 없음 (예: HELPER_ALIGN=ahead=12,lost_window=20)")
        d = defaults[k]
        out[k] = v if isinstance(d, str) else int(float(v)) if isinstance(d, int) else float(v)
    return out
