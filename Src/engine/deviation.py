"""⑤ 이탈 감지 (1차): 말소리가 일정 시간 대본과 안 맞으면 이탈, 다시 맞으면 복귀.

이탈 유형은 돌아온 위치로 정한다.
- 이탈 전 위치보다 2큐 이상 뒤로 돌아옴 → skip (누락)
- 이탈 전 위치보다 앞으로 돌아옴     → repeat (반복)
- 같은 자리 · 바로 다음 큐로 돌아옴   → adlib (애드리브)

이탈이 시작될 때는 유형을 아직 모른다. 화면(protocol.ts)은 시작 알림에도 유형이 필요해서
임시로 START_TYPE 을 보내고, 복귀 알림에 진짜 유형을 보낸다 (화면은 복귀 알림으로 덮어씀).
→ 화면에 '미정' 유형이 생기면 START_TYPE 만 바꾸면 된다.
"""
from dataclasses import dataclass

from .aligner import Step

START_TYPE = "adlib"


@dataclass
class Alert:
    deviation_type: str      # skip / repeat / adlib
    since: int               # 이탈 시작 시각 (epoch ms)
    return_cue_id: int | None


class DeviationDetector:
    def __init__(self, deviate_after_sec: float = 6.0, min_misses: int = 2):
        self.after_ms = int(deviate_after_sec * 1000)
        self.min_misses = min_misses
        self.deviating = False
        self.since: int | None = None      # 처음 안 맞기 시작한 시각
        self.misses = 0
        self.last_idx = 0                  # 마지막으로 맞았던 위치 (aligner.items 순서)

    def reset(self, idx: int = 0):
        self.deviating, self.since, self.misses, self.last_idx = False, None, 0, idx

    def update(self, step: Step, idx: int, now_ms: int, hold: bool = False) -> Alert | None:
        """인식 결과 하나를 반영. idx = 이 단계 뒤 aligner.pos. hold = 노래 구간 등 알림 보류."""
        if step.matched:
            if self.deviating:
                self.deviating = False
                d = idx - self.last_idx
                kind = "skip" if d >= 2 else "repeat" if d < 0 else "adlib"
                alert = Alert(kind, self.since, step.cue.id)
                self.since, self.misses, self.last_idx = None, 0, idx
                return alert
            self.since, self.misses, self.last_idx = None, 0, idx
            return None

        if not step.heard or hold:          # 조용함 · 짧은 글자 · 노래 구간은 이탈 근거로 안 씀
            return None
        if self.deviating:
            return None
        if self.since is None:
            self.since = now_ms
        self.misses += 1
        if self.misses >= self.min_misses and now_ms - self.since >= self.after_ms:
            self.deviating = True
            return Alert(START_TYPE, self.since, None)
        return None
