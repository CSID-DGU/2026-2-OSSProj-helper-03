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
5차 (먼 대사로 튀지 않게):
- "무슨 말인데요?" 같은 흔한 한마디 애드리브가 20큐 뒤 대사와 같으면, 겹친 조각(3초를 1.5초마다)에 같은 말이
  두 번 들어가 확인 두 번이 채워져서 20큐를 건너뛰었다. 한번 멀리 튀면 뒤로는 back 큐만 찾으므로 스스로 못 돌아온다.
- 공연은 대본 순서대로 가므로, 앞으로 far 큐 넘게 가는 이동은 '따라잡기'만 한다 (_caught_up).
  최근 몇 초 동안 그 근처 대본을 far_jamo 자모(약 16음절) 넘게 '한 줄씩 들었고' (_heard_near), 그중
  ① 서로 다른 대사를 far_lines 줄 넘게 들었거나 (배우가 거기서 대본을 이어 가고 있음. 노래 · 인식 끊김으로
     뒤처졌다가 따라잡는 경우. 애드리브 한마디는 한 줄과만 맞는다), 또는
  ② 지나칠 대사 중 못 들은 것을, 최근 quiet_sec 초 동안 인식 글자가 없던 시간(인터넷 · 마이크 끊김, 인식 실패)에
     배우가 다 말할 수 있었을 때 (pace). 이때는 근처 대본을 far_jamo 의 quiet_part(절반)만 들어도 됨
  말소리를 계속 듣고 있었는데 멀리 있는 대사 한두 줄과 비슷한 말이 나오면, 아무리 비슷해도 애드리브 · 우연으로 보고
  그 자리에 머문다 (이탈 알림이 뜨고, 배우가 정말 크게 건너뛰었으면 오퍼레이터가 대본 줄을 눌러 맞춤)
- ② 만으로 했더니 실시간 측정에서 구글 한도 초과로 13초 끊긴 뒤 노래 구간(가사는 들려도 잘 안 맞음)에서
  #18~#28 을 순서대로 들으면서도 못 따라가 공연 녹음 정확도가 62 → 23% 였다 (끊긴 시간이 헛이동 한 번에 지워진 것도).
  ① 을 넣고 끊긴 시간을 최근 30초로 세니 59%, ② 의 근거를 절반으로 낮추니 61.5% (애드리브로 튀는 비율은 그대로)
- 저장된 공연 · 이탈 녹음에는 4큐 넘는 이동이 없어서 평소 추적은 그대로
6차 (줄 끝에서 다음 줄로 미리 넘어가지 않게):
- 현재 위치를 '맞은 구간의 끝'이 아니라 '구간 안에서 실제로 같은(3자모 넘게 이어진) 마지막 글자'로 본다 (anchor="matched").
  partial_ratio 의 구간은 인식 글자 길이만큼이라, 인식 글자에 대본에 없는 글자가 섞이면("따라" → "따라서", 줄 끝 뒤 애드리브 첫마디)
  구간이 다음 줄 첫 글자까지 넘쳐 줄을 다 말한 순간 다음 줄로 넘어갔다. 그 뒤 애드리브가 오면 말하지 않은 다음 줄이 계속 보였다.
  마이크 발표 시험 4번 모두 애드리브 동안 제자리. 저장 기록 5벌 정확도 −0.1 ~ −1.1점 (미리 넘어간 것이 우연히 ±1큐에 맞던 몫),
  도달 지연 중앙값 · 이탈 감지는 그대로. HELPER_ALIGN=anchor=end 면 예전과 같음
7차 (반복 · 누락 감지 보완, #39):
- 대본 힌트에 지나간 hint_back(2)줄도 넣는다. 힌트가 현재 + 다음 3줄뿐이라 소리가 애매하면 음성인식이 다음 줄을
  그대로 베꼈고(누락 A3: 잘린 27 · 28번을 적어서 들은 것으로 처리), 배우가 되돌아가 말한 줄은 힌트에 없어 빈 결과가
  나왔다(반복 B1). 실시간 측정(이탈 녹음 2개 + 원본 2번, 11/18): 이탈 9건 중 7 → 8건, 유형 맞음 6 → 8,
  잘못된 알림 14.6분에 1 → 0건. dev_a 를 한 번 더 재도 같았다 (A3 은 힌트가 퍼져서 다음 줄을 덜 베낌).
  원본 ±1큐 정확도 평균 87.4 → 87.7%, 도달 p90 4.7 → 3.9초. 남은 A4 는 되돌아간 줄을 힌트에 넣어도 음성인식이 빈 결과
- 해 봤지만 뺀 것: 끝까지 들었던 줄을 겹치지 않는 조각에서 처음부터 다시 들으면 반복으로 보기 (A4 는 잡지만 노래 ·
  침묵 구간에서 지금 줄 힌트를 베낀 글자에 걸려 잘못된 반복 알림이 11분에 14건), 지나친 줄은 겹치는 두 조각에서 들려야
  들은 것으로 보기 (줄이 조각 맨 앞에 걸리고 앞 조각이 빈 결과면 정상도 한 번만 들려서 잘못된 누락 알림 · 반복을 놓침)
8차 (힌트 베끼기 · 인식 끊김에 덜 속게. 빠른 설정 2.5/1초에서 이탈 감지가 줄던 것):
- echo_filter: 근처 대사(지나간 줄 ~ 다음 줄)가 원문 그대로 대본을 거슬러 가는 순서로 들어 있으면 힌트를 이어 붙여 베낀
  것으로 본다. 아직 안 온 줄(다음 대사)의 원문을 먼저 지우고, 남은 글자에도 두 줄 넘게 거꾸로 들어 있으면 통째로 버린다
  (원본 녹음 끝 무음에서 지금 줄 56, 지나간 줄 55 · 53 의 원문을 힌트 순서대로 이어 적어 냄)
- end_check: 앞으로 새 줄로 넘어간 근거가 그 조각 하나뿐이면, 소리가 END_OVERLAP 초 넘게 겹치는 다음 조각(빈 결과는 빼고)에도
  그 줄이 있는지 본다. 없으면 힌트를 베낀 글자로 보고(소리가 애매하면 다음 대사를 그대로 적어 냄) 안 들린 줄로 센다 (누락 A1)
- dropout_guard: 지나친 줄 중 안 들린 대사를, 마지막으로 위치를 확인한 뒤 소리는 컸는데(loud) 인식이 비어 있던 시간 동안
  사람이 다 말할 수 있었으면 누락으로 세지 않는다 (원본 녹음 잘못된 누락 알림). 배우가 쉬는 동안(A1 은 -40dBFS)과 말하는데
  인식이 빈 경우(-21 ~ -24dBFS)를 소리 크기로 가른다. 소리 크기를 모르면(loud=None) 세지 않는다
- repeat_confirm: 앞 줄로 돌아갈 후보가 나온 뒤, 그 앞 줄에서 시작해 지금 줄로 이어지는 말이나 긴 줄(RESTART_JAMO 넘게)을
  처음부터 다시 하는 말을, 지금 줄을 마지막으로 들은 조각과 소리가 안 겹치는 조각에서 들으면 반복으로 본다 (Step.again).
  추적기가 지금 줄에 머물러도 반복을 알 수 있다 (반복 A4 · B3). 7차에서 뺀 '처음부터 다시'를 돌아갈 후보가 있을 때로 좁힌 것.
  이어지는 말은 돌아갈 줄을 지금 줄보다 먼저 들었을 때만 본다 (두 줄을 한 조각에서 처음 같이 들었으면 힌트를 베껴 앞질러 감)
  저장된 인식 기록으로 다시 돌린 결과 (11/18): 빠른 설정(2.5/1초, 같은 요청 2번) 이탈 9건 중 5 → 8건, 기본 설정(3/1.5초)
  7 → 8건, 잘못된 알림은 둘 다 0건 그대로. 다른 설정으로 잰 기록도 찾은 수는 같거나 늘고 잘못된 알림 0건 그대로.
  원본 녹음 22벌 76분 잘못된 알림 11 → 8건, ±1큐 정확도 평균 87.3 → 87.4%, 도달 지연 그대로
9차 (화면에 한 번도 안 뜨는 줄, 11/19):
- 고정 시험 세트의 '안 보임' 40건 중 16건은 화면의 짧은 대사 묶어 보이기로 뜨는 줄이었고, 남은 24건은 빠른 주고받기
  (6 ~ 11음절을 1.1초 안에 말함, 한 조각에 다음 줄까지 들어가 바로 뒤 줄로 감) 10건, 노래 12건, 이탈 바로 뒤 2건.
  거의 다 한 줄을 건너뛰고 바로 다음 줄로 간 경우라, 지나친 줄 중 말한 것으로 보이는 줄을 Step.passed 로 알려 준다.
  화면은 이 줄을 지금 줄 앞에 함께 띄운다 (지나간 줄 함께 띄우기). 작은 이동(small_step 이하)만 (크게 건너뛴 이동은 잘못 튄
  것일 수 있음). 대사는 누락 근거가 없고 최근 인식 글자로 줄 자모의 HEARD_PART 넘게 들었어야 한다. 앞 줄과 같은 낱말만 겹쳐도
  heard_score 는 넘어서, 말하지 않은 줄이 붙었다 (대사 입력 시험). 가사는 노래 인식이 약해서 누락 근거만 없으면 넣는다
- 빠른 주고받기에서 두 사람이 겹쳐 말한 조각(2.5초에 29 ~ 30음절)이 너무 빠른 말로 걸러져서, 그 줄들을 못 들은 것으로 보고
  잘못된 누락 알림이 났다 (빠른 설정 원본 녹음의 1건). 거르기 기준을 초당 10 → 12음절로 (engine/pipeline.py)
- 저장된 인식 기록으로 다시 돌린 결과 (eval/suite.py 의 '화면 안 보임', '잘못 띄움'): 고정 시험 세트 원본과 이탈 녹음 6벌에서
  안 보임 40 → 38건, 휴대폰 자막에 못 뜬 대사는 짧은 대사 묶어 보이기만으로 22건, 지나간 줄까지 1건. 말하기 전에 띄운 줄 2건.
  원본 녹음 22벌 76분: 안 보임 255 → 화면 안 보임 64건, 띄운 지나간 줄 193줄 중 27줄이 말하기 전 (대부분 노래에서 추적기가
  앞서 간 경우). 빠른 설정 원본 녹음은 잘못된 알림 1 → 0건, ±1큐 94.1 → 95.1%. 이탈 감지는 그대로
"""
import inspect
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from itertools import accumulate

from rapidfuzz import fuzz
from rapidfuzz.distance import Indel, Levenshtein

from .cue_loader import TRACK_TYPES, Cue, syllables, to_jamo

# 먼 이동 근거: 대사 자모 중 인식 글자와 HEARD_BLOCK 자모 넘게 이어서 같은 부분이 HEARD_PART 넘으면 그 줄을 들은 것으로.
# 실제 인식 기록에서 말한 대사는 81% 가 넘고, 상관없는 대사는 대본에 같은 줄이 또 있을 때(1.9%)만 넘었다
HEARD_BLOCK, HEARD_PART = 4, 0.6
# 지금 줄을 처음부터 다시 하는 것으로 반복을 볼 때 줄의 최소 자모 수 (약 7음절). 이보다 짧은 줄은 한 조각에 통째로 들어감
RESTART_JAMO = 18
# 새 줄을 확인할 다음 조각은 그 줄로 넘어간 조각과 이만큼(초) 넘게 겹쳐야 함 (덜 겹치면 그 줄 소리가 이미 지나갔을 수 있음)
END_OVERLAP = 1.0

# 개선 전(엔진 서버 첫 버전) 설정. 평가(eval/run_eval.py --baseline)에서 비교용으로 쓴다.
BASELINE = dict(min_jamo=6, accept=65.0, back=3, ahead=15, small_step=2, confirm=2, lost_after=3,
                strong=85.0, strong_jamo=10, anchor="mid", widen=0, near_first=0, scene_limit=0, lost_window=0,
                prefer_near=0, pending_sec=0.0, pace=0.0, far=0)


@dataclass
class Step:
    status: str            # skip / move / stay / pending / miss / lost
    cue: Cue               # 이 단계 뒤 현재 위치
    score: float = 0.0     # 0~100
    cand: Cue | None = None  # 이번 인식이 가리킨 큐 (받아들였는지와 별개)
    skipped: tuple[Cue, ...] = ()  # 이번 이동으로 지나친 대사 중 최근 인식 글자에 없던 것 (누락 근거)
    again: bool = False    # 이미 들었던 앞 큐로 되돌아감 (반복 근거)
    passed: tuple[Cue, ...] = ()   # 이번 이동으로 지나친 줄 중 누락 근거가 없는 것 (화면이 지금 줄 앞에 함께 띄움)

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
                 strong=85.0, strong_jamo=10, anchor="matched", widen=0, near_first=1,
                 scene_limit=1, lost_window=30, recent=3, heard_score=60.0, prefer_near=1,
                 pending_sec=9.0, pace=8.0, far=4, far_jamo=40, far_lines=2, quiet_sec=30.0, quiet_part=0.5,
                 hint_back=2, dropout_guard=1, end_check=1, repeat_confirm=1, echo_filter=1):
        self.items = [c for c in cues if c.type in track_types and c.jamo]
        if not self.items:
            raise ValueError("추적할 큐(대사·가사)가 없습니다.")
        self.starts, s = [], 0
        for c in self.items:
            self.starts.append(s)
            s += len(c.jamo)
        self.text = "".join(c.jamo for c in self.items)
        # 큐까지 누적 음절 수 (지나친 대사를 말하는 데 드는 최소 시간 계산용)
        self.syl = [0, *accumulate(syllables(c.text) for c in self.items)]
        self.min_jamo, self.accept = min_jamo, accept
        self.back, self.ahead, self.small_step = back, ahead, small_step
        self.confirm, self.lost_after = confirm, lost_after
        self.strong, self.strong_jamo = strong, strong_jamo
        self.anchor = anchor          # 인식 글자가 맞은 구간의 어디를 현재 위치로 볼지: mid(가운데) / end(끝) / matched(실제로 같은 마지막 글자)
        self.widen = int(widen)       # 안 맞는 결과가 이어질 때마다 앞쪽 탐색 범위를 이만큼씩 넓힘
        self.near_first = int(near_first)  # 놓친 상태에서 먼저 가까운 범위를 찾고, 없을 때만 끝까지
        self.lost_hi = self._lost_ranges(int(scene_limit), int(lost_window))
        self.recent: deque[str] = deque(maxlen=int(recent))  # 최근 인식 글자 (자모) — 지나친 대사를 들었는지 확인
        self.heard_score = heard_score
        self.heard: set[int] = set()  # 들었던 큐 (위치로 확인했거나, 지나칠 때 최근 인식 글자에 있던 것)
        self.prefer_near = int(prefer_near)
        self.pending_sec = pending_sec  # 큰 이동 후보는 이 시간(초) 안에 다시 나와야 인정 (0 = 끝없이 기다림)
        self.pace = pace                # 사람이 말할 수 있는 가장 빠른 속도 (음절/초). 0 = 안 봄
        self.far = int(far)             # 앞으로 이만큼 넘게 가는 이동은 따라잡기일 때만 (0 = 안 봄)
        self.far_jamo = far_jamo        # 따라잡기 근거: 후보 근처에서 들은 대사들의 자모 수 합
        self.far_lines = int(far_lines)  # 후보 근처에서 서로 다른 대사를 이만큼 넘게 들었으면 따라잡기 (0 = 안 봄)
        self.quiet_sec = quiet_sec      # 인식 글자가 없던 시간을 최근 이만큼(초)만 센다
        self.quiet_part = quiet_part    # 끊긴 시간으로 따라잡을 때는 far_jamo 의 이만큼만 들으면 됨
        self.gaps: deque[tuple[float, float, bool | None]] = deque(maxlen=64)   # 인식 글자가 없던 조각 (소리 끝 시각, 길이, 소리가 컸나)
        self.hint_back = int(hint_back)  # 대본 힌트에 넣을 지나간 줄 수 (반복한 줄을 알아듣게)
        self.dropout_guard = int(dropout_guard)   # 인식이 비어 있던 동안 지나친 줄은 누락으로 안 셈
        self.end_check = int(end_check)           # 새 줄로 넘어간 근거를 겹치는 다음 조각으로 확인
        self.repeat_confirm = int(repeat_confirm)  # 돌아갈 후보 뒤 앞 줄부터 이어 말하거나 지금 줄을 다시 하면 반복
        self.echo_filter = int(echo_filter)       # 힌트를 통째로 베낀 결과(대본을 거슬러 가는 원문 이어 붙이기)는 버림
        self.chunk_start = 0.0           # 지금 보는 인식 결과의 조각 시작 시각
        self.seen: dict[int, tuple[float, float, int]] = {}   # 줄별 (처음 · 마지막으로 들은 조각의 끝 시각, 들은 가장 먼 자모 위치)
        self.check_end: tuple[int, float] | None = None  # 다음 조각으로 확인할 새 줄, 그 줄로 넘어간 조각의 끝 시각
        self.suspect: set[int] = set()   # 겹치는 다음 조각에 없던 줄 (힌트를 베낀 것으로 봄)
        self.back_cands: list[tuple[int, float]] = []    # 앞 줄로 돌아갈 후보 (위치, 소리 끝 시각)
        self.clock = 0.0              # 마지막 인식 글자의 소리 끝 시각
        self.at: float | None = None  # 마지막으로 위치를 확인한 소리 시각
        self.stale = 0                # 마지막으로 위치를 확인한 뒤 지난 인식 횟수 (빈 결과 포함)
        self.pos = 0
        self.pending: list[tuple[int, float]] = []   # 큰 이동 후보 (위치, 소리 끝 시각), 나온 순서
        self.said: deque[tuple[float, str]] = deque(maxlen=16)   # 최근 인식 자모 (소리 끝 시각, 자모): 먼 이동 근거
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
        self.gaps.clear()             # 오퍼레이터가 맞췄으므로 그 전 끊김으로 따라잡지 않음
        self.check_end, self.back_cands = None, []
        self.suspect.clear()          # 오퍼레이터가 맞춘 위치부터 새로 판단
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
        """대본 힌트: 현재 큐 + 다음 n 큐 + 지나간 hint_back 큐. 놓친 상태에서는 힌트에 묶이지 않게 비운다.
        지나간 줄은 가까운 것부터 맨 뒤에 둔다 (구문 힌트 개수 제한에 걸리면 지나간 줄부터 빠짐)."""
        if self.lost:
            return []
        back = self.items[max(0, self.pos - self.hint_back):self.pos]
        return self.items[self.pos:self.pos + 1 + n_next] + back[::-1]

    def _search(self, t: str, lo: int, hi: int) -> tuple[int, float, tuple[int, int]]:
        """(현재 위치가 될 큐, 점수, 대본 글자열에서 맞은 구간 [시작, 끝))."""
        a = self.starts[lo]
        b = self.starts[hi] if hi < len(self.items) else len(self.text)
        al = fuzz.partial_ratio_alignment(t, self.text[a:b])
        start, end = al.dest_start, al.dest_end
        if self.anchor == "mid":
            at = a + (al.dest_start + al.dest_end) // 2
        else:   # 맞은 구간의 끝 = 배우가 방금 말한 곳 (한 조각에 큐가 여러 개일 때 덜 늦음)
            if self.anchor == "matched":   # 구간 안에서 실제로 같은 글자만 (우연히 같은 낱자는 빼고)
                ops = [op for op in Levenshtein.opcodes(t, self.text[a + al.dest_start:a + al.dest_end])
                       if op.tag == "equal" and op.dest_end - op.dest_start >= 3]
                if ops:
                    start, end = al.dest_start + ops[0].dest_start, al.dest_start + ops[-1].dest_end
            at = a + max(al.dest_start, end - 1)
        return bisect_right(self.starts, at) - 1, al.score, (a + start, a + max(start + 1, end))

    def _too_fast(self, idx: int) -> bool:
        """현재 위치 → idx 사이 대사를, 마지막 확인 뒤 지난 시간 동안 사람이 다 말할 수 없었나."""
        if not self.pace or self.at is None or idx <= self.pos + 1:
            return False
        need = (self.syl[idx] - self.syl[self.pos + 1]) / self.pace
        return self.clock - self.at < need

    def update(self, text: str, end: float | None = None, start: float | None = None,
               loud: bool | None = None) -> Step:
        """인식 글자 하나를 반영. end / start = 그 조각 소리의 끝 / 시작 시각 (초). end 를 안 주면 한 번에 1초씩
        흐른 것으로 본다. start 를 안 주면 앞 결과와 소리가 겹치지 않는 것으로 본다 (대사 입력 · 스트리밍 · 시험처럼
        결과 하나가 따로 들은 말일 때). 겹쳐 보내는 조각 방식은 파이프라인이 조각 시작 시각을 넘긴다.
        loud = 그 조각 소리가 컸나 (말소리 크기). 빈 결과가 인식 끊김인지 배우가 쉰 것인지 가르는 데 쓴다."""
        end = self.clock + 1.0 if end is None else end
        self.chunk_start = end if start is None else start
        dt, self.clock = max(0.0, end - self.clock), end
        if self.pending_sec:   # 오래된 큰 이동 후보는 버린다 (한참 뒤 엉뚱한 말 한 번으로 튀지 않게)
            self.pending = [p for p in self.pending if end - p[1] <= self.pending_sec]
            self.back_cands = [p for p in self.back_cands if end - p[1] <= self.pending_sec]
        t = to_jamo(text)
        if self.echo_filter:
            t, dumped = self._strip_echo(t)
            if dumped:
                self.stale += 1
                return Step("skip", self.current)   # 힌트를 통째로 베낌: 들은 말로 쓰지 않음
        self._check_new_line(t)
        if len(t) < self.min_jamo:
            self.stale += 1
            self.gaps.append((end, dt, loud))
            return Step("skip", self.current)
        self.stale += 1
        self.recent.append(t)
        self.said.append((end, t))
        far = max([self.pos] + [p[0] for p in self.pending])
        lo = max(0, self.pos - self.back)
        near_hi = min(len(self.items), far + self.ahead + self.widen * (self.stale - 1) + 1)
        if self.lost:   # 공연은 대체로 앞으로 가므로 현재 위치 조금 앞부터 끝까지
            idx, score, span = -1, 0.0, None
            if self.near_first:   # 반복 후렴 · 같은 대사가 있으면 가까운 쪽을 먼저
                idx, score, span = self._search(t, lo, near_hi)
            if score < self.accept:
                idx, score, span = self._search(t, lo, max(near_hi, self.lost_hi[self.pos]))
        else:
            idx, score, span = self._search(t, lo, near_hi)
        if self.prefer_near and not 0 <= idx - self.pos <= self.small_step:
            n_idx, n_score, n_span = self._search(t, self.pos, min(len(self.items), self.pos + self.small_step + 1))
            if n_score >= score:      # 가까운 곳도 똑같이 맞음 (같은 대사가 두 번) → 가까운 쪽
                idx, score, span = n_idx, n_score, n_span
        cand = self.items[idx]
        if score < self.accept:
            self.miss += 1
            return Step("lost" if self.lost else "miss", self.current, score, cand)

        self.miss = 0
        d = idx - self.pos
        fast = self._too_fast(idx)
        if 0 <= d <= self.small_step:   # 자연스러운 진행
            return self._move(idx, score, cand, span)
        # 큰 이동(뒤로 가거나 많이 건너뜀): 대기 후보와 같은 곳이거나 그 바로 뒤로 이어지면 인정.
        # 말할 수 없는 빠르기로 건너뛰면 한 번 더. 멀리 앞으로는 따라잡기일 때만
        self.pending = [p for p in self.pending if -1 <= idx - p[0] <= self.small_step + 1] + [(idx, end)]
        if d < 0:                       # 앞 줄로 돌아갈 후보는 따로 기억 (반복 확인, repeat_confirm)
            self.back_cands.append((idx, end))
        if self.far and d > self.far and not self._caught_up(idx):
            return Step("pending", self.current, score, cand)
        if (d > 0 and not fast and score >= self.strong and len(t) >= self.strong_jamo) \
                or len(self.pending) >= self.confirm + fast:   # 긴 문장이 확실히 맞음 / 확인됨
            return self._move(idx, score, cand, span)
        return Step("pending", self.current, score, cand)

    def _caught_up(self, idx: int) -> bool:
        """멀리 앞(idx)으로 가도 되나: 지나칠 대사 중 못 들은 것을 배우가 인식 글자가 없던 동안 다 말할 수 있었고,
        그 근처 대본을 들었다."""
        jamo, lines = self._heard_near(idx)
        if jamo >= self.far_jamo and self.far_lines and lines > self.far_lines:
            return True
        if jamo < self.far_jamo * self.quiet_part:
            return False
        texts = self._texts(-1.0 if self.at is None else self.at)   # 마지막으로 위치를 확인한 뒤 들은 말
        unheard = sum(self.syl[i + 1] - self.syl[i] for i in range(self.pos + 1, idx)
                      if _covered(self.items[i].jamo, texts) < HEARD_PART)
        need = unheard / self.pace if self.pace else 0.0
        return self.quiet >= need

    @property
    def quiet(self) -> float:
        """최근 quiet_sec 초 동안 인식 글자가 없던 시간 (초)."""
        return sum(dt for e, dt, _ in self.gaps if self.clock - e < self.quiet_sec)

    def _texts(self, since: float) -> list[str]:
        """since 초 뒤에 끝난 인식 자모 (같은 글자는 한 번)."""
        return list(dict.fromkeys(t for e, t in self.said if e > since))

    def _heard_near(self, idx: int) -> tuple[int, int]:
        """큰 이동 후보 근처(바로 앞 대사들 ~ 바로 다음)에서 최근 pending_sec 초 인식 글자로 들은 대사들의 (자모 수 합, 줄 수).
        한 줄이 조각(3초) 경계에 걸려 나뉘어 들려도(그 조각은 다른 곳에 맞거나 안 맞음) 맞은 부분을 합쳐 보고,
        같은 한마디를 여러 번 들어도 한 줄로만 센다."""
        texts = self._texts(self.clock - self.pending_sec if self.pending_sec else -1.0)
        lo = max(self.pos + self.small_step + 1, idx - self.small_step)
        heard = [c for c in self.items[lo:idx + 2] if len(c.jamo) >= self.min_jamo and _covered(c.jamo, texts) >= HEARD_PART]
        return sum(len(c.jamo) for c in heard), len(heard)

    def _move(self, idx: int, score: float, cand: Cue, span: tuple[int, int] | None = None) -> Step:
        prev, since = self.pos, self.at
        again = (idx < prev and idx in self.heard) or self._repeat_confirmed(span, prev)
        if again:
            self.back_cands = []
        self._mark_seen(span, again)
        if idx != prev:
            self.suspect.discard(idx)          # 다시 그 줄로 왔으면 새 근거로 다시 판단 (반복으로 되돌아온 줄 등)
        new_line = idx > prev and idx not in self.heard
        self.pos, self.pending, self.stale, self.at = idx, [], 0, self.clock
        if idx - prev > self.far:     # 따라잡았으면 그 끊김은 다 썼음
            self.gaps.clear()
        skipped = []
        if self.end_check and idx > prev and prev in self.suspect and self.items[prev].type == "dialogue":
            skipped.append(self.items[prev])  # 지금 줄로 넘어온 근거가 힌트 베끼기였음: 그 줄도 안 들린 것
        got = "".join(self.recent)
        for i in range(prev + 1, idx):        # 지나친 큐: 최근 인식 글자에 비슷한 부분이 있으면 들은 것으로
            c = self.items[i]
            if len(c.jamo) < self.min_jamo:   # 너무 짧은 큐는 판단 안 함
                continue
            if i not in self.suspect and fuzz.partial_ratio(c.jamo, got) >= self.heard_score:
                if idx - prev <= self.small_step:   # 크게 건너뛴 이동은 잘못 튄 것일 수 있어 지나친 큐를 기억하지 않음
                    self.heard.add(i)
            elif c.type == "dialogue":
                skipped.append(c)
        if skipped and self.dropout_guard and self._dropout_covers(skipped, since):
            skipped = []                      # 인식이 비어 있던 동안 말했을 수 있음: 누락으로 안 셈
        passed = ()
        if 1 < idx - prev <= self.small_step:   # 자연스러운 진행에서 화면에 안 뜨고 지나간 줄 (지나간 줄 함께 띄우기)
            gone, texts = {c.id for c in skipped}, list(self.recent)
            # 대사는 줄 자모의 HEARD_PART 넘게 들었어야 함 (앞 줄과 같은 낱말만 겹쳐도 heard_score 는 넘음).
            # 가사는 노래 인식이 약해서, 아주 짧은 줄은 판단할 수 없어서 누락 근거만 없으면 넣는다
            passed = tuple(c for c in self.items[prev + 1:idx] if c.id not in gone and (
                c.type != "dialogue" or len(c.jamo) < self.min_jamo or _covered(c.jamo, texts) >= HEARD_PART))
        self.heard.add(idx)
        if self.end_check and new_line:
            self.check_end = (idx, self.clock)
        return Step("move" if idx != prev else "stay", self.current, score, cand, tuple(skipped), again, passed)

    def _check_new_line(self, t: str):
        """지난번에 새로 넘어간 줄을, 소리가 겹치는 이번 조각 글자로 확인한다 (end_check). 빈 결과면 다음 조각까지 기다리고,
        이번 조각이 그 조각과 END_OVERLAP 초 넘게 겹치지 않으면 판단하지 않는다."""
        if self.check_end is None:
            return
        line, at = self.check_end
        if self.chunk_start > at - END_OVERLAP + 1e-6:   # 그 조각과 조금만 겹치면 그 줄이 이미 지나갔을 수 있음
            self.check_end = None
            return
        if len(t) < self.min_jamo:
            return
        self.check_end = None
        if fuzz.partial_ratio(self.items[line].jamo, t) < self.heard_score:
            self.suspect.add(line)
            self.heard.discard(line)

    def _dropout_covers(self, skipped: list[Cue], since: float | None) -> bool:
        """안 들린 대사를, since(마지막으로 위치를 확인한 때) 뒤 인식 글자가 없던 시간 동안 사람이 다 말할 수 있었나
        (pace 음절/초). 위치를 한 번도 확인하기 전(공연 시작 전 무음)은 보지 않는다."""
        if not self.pace or since is None:
            return False
        syl = sum(syllables(c.text) for c in skipped)
        quiet = sum(dt for e, dt, loud in self.gaps if e > since and loud)
        return quiet >= syl / self.pace

    def _reversed_lines(self, t: str) -> list[int]:
        """근처 대사(지나간 줄 ~ 다음 줄) 중 원문 그대로(자모가 통째로) 들어 있는 줄을 글자 속 순서대로. 대본을 거슬러 가는
        곳이 없으면 빈 목록."""
        lo, hi = max(0, self.pos - self.hint_back - 1), min(len(self.items), self.pos + 5)
        found = sorted((t.find(c.jamo), i) for i, c in enumerate(self.items[lo:hi], lo)
                       if len(c.jamo) >= self.min_jamo and c.jamo in t)
        lines = [i for _, i in found]
        return lines if any(b < a for a, b in zip(lines, lines[1:])) else []

    def _strip_echo(self, t: str) -> tuple[str, bool]:
        """힌트 베끼기 거르기 (echo_filter). 근처 대사가 원문 그대로 대본을 거슬러 가는 순서로 들어 있으면 힌트를 이어 붙여
        베낀 것으로 보고, 먼저 아직 안 온 줄(지금 줄 뒤)의 원문을 지운다 (진짜 말에 다음 대사 힌트가 붙어 나온 경우는
        진짜 말만 남음). 남은 글자에도 원문 두 줄 넘게 거꾸로 들어 있으면 통째로 베낀 것: (글자, True).
        예: 지금 줄 56 에서 56 · 55 · 53번 원문이 힌트 순서대로 나옴 → 통째로 버림
            지금 줄 28 에서 29 · 30 · 27번 원문 순서로 나옴 (27번으로 되돌아감) → 29 · 30 을 지우고 27 만 남김"""
        if len(t) < 2 * self.min_jamo:
            return t, False
        lines = self._reversed_lines(t)
        if not lines:
            return t, False
        for i in lines:
            if i > self.pos:
                t = t.replace(self.items[i].jamo, "")
        return t, len(self._reversed_lines(t)) >= 2

    def _repeat_confirmed(self, span: tuple[int, int] | None, prev: int) -> bool:
        """앞 줄로 돌아갈 후보가 있는데, 이번 말이 그 앞 줄에서 시작해 지금 줄로 이어지거나 지금 줄을 처음부터 다시 한다
        (지금 줄을 마지막으로 들은 조각과 소리가 안 겹치는 조각에서)."""
        if not self.repeat_confirm or span is None or prev not in self.seen:
            return False
        cands = [p for p, _ in self.back_cands if p < prev and self.items[p].type == "dialogue" and p in self.heard]
        if not cands:
            return False
        first, last_end, far = self.seen[prev]
        if self.chunk_start < last_end - 1e-6:
            return False
        line = bisect_right(self.starts, span[0]) - 1
        if min(cands) <= line < prev:        # 앞 줄에서 시작해 지금 줄로 이어짐
            # 돌아갈 줄을 지금 줄보다 먼저 들었어야 함. 두 줄을 한 조각에서 처음 같이 들었으면 힌트를 베껴 앞질러 간 것일
            # 수 있다 (노래 끝에 다음 대사 두 줄이 붙어 나온 뒤 배우가 그 두 줄을 차례로 말함: 잘못된 반복 알림)
            return span[1] > self.starts[prev] and any(self.seen.get(p, (0.0,))[0] < first for p in cands)
        # 지금 줄을 처음부터 다시: 긴 줄의 앞부분만 다시 들릴 때만. 짧은 줄은 한 조각에 통째로 들어가서, 늦게 인식된
        # 같은 말이나 힌트를 베낀 글자도 '다시 함'처럼 보인다 (원본 녹음 잘못된 반복 알림)
        c = self.items[prev]
        n = len(c.jamo)
        head = span[0] - self.starts[prev]
        return (line == prev and c.type == "dialogue" and n >= RESTART_JAMO and head <= 0.25 * n
                and span[1] - self.starts[prev] <= 0.7 * n and far >= 0.6 * n)

    def _mark_seen(self, span: tuple[int, int] | None, restart: bool):
        """맞은 구간이 걸친 줄마다 처음 · 마지막으로 들은 조각의 끝 시각과 가장 먼 위치를 적는다. 반복이면 그 줄부터 새로 센다."""
        if span is None:
            return
        first = bisect_right(self.starts, span[0]) - 1
        last = bisect_right(self.starts, span[1] - 1) - 1
        if restart:
            for i in [k for k in self.seen if k >= first]:
                del self.seen[i]
        for i in range(first, last + 1):
            far = min(span[1], self.starts[i] + len(self.items[i].jamo)) - self.starts[i]
            first_end, _, old = self.seen.get(i, (self.clock, 0.0, 0))
            self.seen[i] = (first_end, self.clock, max(old, far))


def _covered(jamo: str, texts: list[str]) -> float:
    """대사 자모 중 인식 글자 어느 하나와 HEARD_BLOCK 자모 넘게 이어서 같은 부분의 비율."""
    hit = set()
    for t in texts:
        for op in Indel.opcodes(jamo, t):
            if op.tag == "equal" and op.src_end - op.src_start >= HEARD_BLOCK:
                hit.update(range(op.src_start, op.src_end))
    return len(hit) / len(jamo)


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
