"""⑤ 이탈 감지: 위치 추적 결과(Step)로 상태를 바꾸고, 이탈 시작 · 복귀 알림을 낸다.

상태 (detector.state, 바뀔 때 로그)
- normal    대본대로 진행 중
- suspect   방금 인식이 대본과 안 맞음 (아직 알림 없음). 현재 큐 근처와 꽤 비슷하면(인식이 조금 틀린 대사) 안 셈
- searching 위치 추적기가 놓쳐서 장면 범위를 다시 찾는 중 (아직 알림 없음)
- deviating 이탈 알림을 보냄, 대본으로 돌아오기를 기다림
- song      노래 구간 (가사는 인식이 약해서 알림 보류). 현재 큐가 가사이거나, 안 맞은 말이 가사와 꽤 비슷할 때
- no_input  말소리 · 소리가 없음. 이 동안은 알림을 보내지 않고, 쌓인 의심도 지운다

알림
- 대본과 안 맞는 말이 deviate_after 초 이어지면 시작 알림, 다시 맞으면 복귀 알림.
  유형은 돌아온 위치로 정한다: 안 들린 대사를 skip_min 개 넘게 지나쳐 앞으로 → skip,
  이탈 전보다 뒤로 → repeat, 같은 자리 · 바로 다음 → adlib
- 이탈 없이 바로 건너뜀 (안 들린 대사 skip_min ~ skip_max 개를 지나쳐 이동) → skip 알림 하나 (복귀 큐 포함)
  그보다 크게 건너뛰거나, 마지막으로 맞은 지 skip_recent 초가 넘었으면 (인식이 놓친 것일 수 있음) 알림 없이 로그만
- 이미 들었던 앞 대사로 되돌아감 (위치 추적기가 두 번 확인한 뒤로 이동) → repeat 알림 하나

이탈이 시작될 때는 유형을 아직 모른다. 화면(protocol.ts)은 시작 알림에도 유형이 필요해서
임시로 START_TYPE 을 보내고, 복귀 알림에 진짜 유형을 보낸다 (화면은 복귀 알림으로 덮어씀).
→ 화면에 '미정' 유형이 생기면 START_TYPE 만 바꾸면 된다.
"""
import logging
from dataclasses import dataclass

from .aligner import Step

log = logging.getLogger("helper.deviation")

START_TYPE = "adlib"
STATES = ("normal", "suspect", "searching", "deviating", "song", "no_input")

# 1차(개선 전) 감지기와 거의 같게 동작하는 설정. 평가(eval/deviation_eval.py --baseline)에서 비교용
BASELINE = dict(deviate_after_sec=6.0, skip_min=0, repeat=False, silence_sec=0.0, song_score=0.0, near_score=0.0)


@dataclass
class Alert:
    deviation_type: str      # skip / repeat / adlib
    since: int               # 이탈 시작 시각 (epoch ms)
    return_cue_id: int | None


class DeviationDetector:
    def __init__(self, deviate_after_sec: float = 3.0, min_misses: int = 2, skip_min: int = 2, skip_max: int = 6,
                 skip_recent_sec: float = 10.0, repeat: bool = True, silence_sec: float = 4.0,
                 quiet_level: float = 0.1, song_score: float = 60.0, near_score: float = 55.0):
        self.after_ms = int(deviate_after_sec * 1000)
        self.min_misses = min_misses
        self.skip_min = skip_min                 # 안 들린 대사를 이만큼 지나치면 누락 (0 = 누락 바로 알림 안 함)
        self.skip_max = skip_max                 # 이보다 많이 지나치면 바로 알림은 안 함 (추적기가 튄 것일 수 있음)
        self.skip_recent_ms = int(skip_recent_sec * 1000)  # 직전까지 대본대로 가고 있었을 때만 누락으로 봄
        self.repeat = repeat                     # 들었던 앞 대사로 되돌아가면 반복 알림
        self.silence_ms = int(silence_sec * 1000)  # 이만큼 말소리가 없으면 입력 없음 (0 = 안 씀)
        self.quiet_level = quiet_level           # tick() 음량이 이 아래면 조용함
        self.song_score = song_score             # 안 맞은 말이 가사와 이 점수 넘게 비슷하면 노래로 봄 (0 = 안 씀)
        self.near_score = near_score             # 안 맞은 말이 현재 · 다음 큐와 이만큼 비슷하면 이탈 근거로 안 씀 (0 = 안 씀)
        self.state = "normal"
        self.since: int | None = None            # 처음 안 맞기 시작한 시각
        self.misses = 0
        self.last_idx = 0                        # 마지막으로 맞았던 위치 (aligner.items 순서)
        self.last_match: int | None = None       # 마지막으로 맞은 시각
        self.last_lyric = False                  # 마지막으로 맞은 큐가 가사였나
        self.last_heard: int | None = None       # 마지막으로 말소리가 들린 시각
        self.loud_at: int | None = None          # 마지막으로 소리가 있던 시각 (tick)

    @property
    def deviating(self) -> bool:
        return self.state == "deviating"

    def reset(self, idx: int = 0):
        self._set("normal")
        self.since, self.misses, self.last_idx, self.last_match, self.last_lyric = None, 0, idx, None, False

    def _set(self, state: str):
        if state != self.state:
            level = logging.INFO if "deviating" in (state, self.state) or state == "searching" else logging.DEBUG
            log.log(level, "이탈 상태: %s → %s", self.state, state)
            self.state = state

    def _clear(self, state: str):
        """의심을 지우고 상태만 바꾼다 (이탈 중이면 그대로 둔다 — 복귀 알림을 기다림)."""
        if not self.deviating:
            self.since, self.misses = None, 0
            self._set(state)

    def update(self, step: Step, idx: int, now_ms: int, hold: bool = False) -> Alert | None:
        """인식 결과 하나를 반영. idx = 이 단계 뒤 aligner.pos. hold = 노래 구간 등 알림 보류."""
        if step.matched:
            return self._matched(step, idx, now_ms, hold)

        if not step.heard:                      # 빈 결과 · 짧은 글자: 오래 이어지면 입력 없음
            quiet_since = now_ms if self.last_heard is None else self.last_heard
            if self.silence_ms and now_ms - quiet_since >= self.silence_ms:
                self._clear("no_input")
            return None
        self.last_heard = now_ms
        if hold or self._song_like(step):       # 노래 구간: 안 맞아도 이탈 근거로 안 씀
            self._clear("song")
            return None
        if self.deviating or self._near_miss(step):   # 인식이 조금 틀린 대사: 이탈 근거로 안 씀
            return None
        if self.since is None:
            self.since = now_ms
        self.misses += 1
        self._set("searching" if step.status == "lost" else "suspect")
        if self.misses >= self.min_misses and now_ms - self.since >= self.after_ms:
            self._set("deviating")
            return Alert(START_TYPE, self.since, None)
        return None

    def _near_miss(self, step: Step) -> bool:
        return (bool(self.near_score) and step.cand is not None and step.score >= self.near_score
                and 0 <= step.cand.order - step.cue.order <= 2)

    def _song_like(self, step: Step) -> bool:
        """추적기가 놓친 말이 가사와 꽤 비슷함 → 노래가 시작됐는데 아직 가사 큐로 못 옮긴 것으로 본다."""
        return (bool(self.song_score) and step.cand is not None and step.cand.type == "lyric"
                and step.score >= self.song_score)

    def _matched(self, step: Step, idx: int, now_ms: int, hold: bool) -> Alert | None:
        d = idx - self.last_idx
        skipped = self.skip_min and len(step.skipped) >= self.skip_min
        alert = None
        if self.deviating:
            if self.skip_min:
                kind = "skip" if skipped else "repeat" if d < 0 else "adlib"
            else:                               # 1차 방식: 이동 거리만으로
                kind = "skip" if d >= 2 else "repeat" if d < 0 else "adlib"
            alert = Alert(kind, self.since, step.cue.id)
        elif not self.last_lyric:
            # 노래 구간에서 나올 때는 추적기가 따라잡느라 크게 움직이므로 누락 · 반복으로 보지 않는다.
            # 대사에서 안 들린 대사를 건너뛰어 노래 첫 줄로 간 것은 누락으로 본다
            since = next(t for t in (self.since, self.last_match, now_ms) if t is not None)
            recent = self.last_match is not None and now_ms - self.last_match <= self.skip_recent_ms
            if skipped and recent and len(step.skipped) <= self.skip_max:
                alert = Alert("skip", since, step.cue.id)
            elif skipped:
                log.info("큰 이동 %d큐 (안 들린 대사 %d개): 알림 없음", d, len(step.skipped))
            elif self.repeat and d < 0 and step.again and not hold:
                alert = Alert("repeat", since, step.cue.id)
        if alert:
            log.info("이탈 %s: 복귀 #%s (%d큐 이동)", alert.deviation_type, alert.return_cue_id, d)
        self.since, self.misses, self.last_idx = None, 0, idx
        self.last_match = self.last_heard = now_ms
        self.last_lyric = step.cue.type == "lyric"
        self._set("song" if hold else "normal")
        return alert

    def tick(self, now_ms: int, level: float):
        """상태 스레드에서 1초마다: 소리가 silence_sec 넘게 거의 없으면 입력 없음 (알림은 보내지 않는다)."""
        if level > self.quiet_level or self.loud_at is None:
            self.loud_at = now_ms
        elif self.silence_ms and now_ms - self.loud_at >= self.silence_ms:
            self._clear("no_input")
