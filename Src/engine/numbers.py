"""① 큐 시트 로더의 정규화: 숫자를 한글 읽기로 바꾼다 (#47).

대본은 "세 시"처럼 한글로 적는데 음성인식(chirp_3)은 "3시", "30만 원", "11월 13일"처럼 숫자로 적는 일이 많다.
대사와 인식 글자를 비교하기 전에 둘 다 같은 한글 읽기로 바꾼다. 화면에 보이는 대본 글자는 그대로 둔다.

- 기본은 한자어 수: 3분 → 삼분, 2026년 → 이천이십육년, 30만 원 → 삼십만 원, 1만 → 만, 6월 → 유월, 10월 → 시월
- 뒤에 고유어 단위(NATIVE_COUNTERS)가 오면 고유어 수: 3시 → 세시, 20살 → 스무살, 2명 → 두명, 1번째 → 첫번째.
  99까지만 (100명 → 백명), 시는 12까지 (13시 → 십삼시), 대는 10의 배수면 나이대 (20대 → 이십대)
- 1 2 3 처럼 1씩 늘며 이어 세는 10 이하의 수는 하나 둘 셋, "2막 3장"은 이막 삼장
- 0으로 시작하면 한 자씩 (007 → 공공칠), 소수점은 점 (3.5 → 삼점오), %는 퍼센트, 1,000의 쉼표는 뺀다
같은 단위를 두 가지로 읽는 경우(3번 = 세 번 / 삼 번, 3장 = 세 장 / 삼 장)는 대사에서 더 흔한 쪽(세 번, 세 장)으로 읽는다.
단위는 NATIVE_COUNTERS, SINO_COUNTERS 에 더하면 된다 (수 뒤 글자와 가장 길게 맞는 단위를 쓴다).
"""
import re

SINO_DIGITS = "영일이삼사오육칠팔구"
SMALL_UNITS = ("", "십", "백", "천")
BIG_UNITS = ("", "만", "억", "조", "경")
NATIVE_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")    # 단위 앞 (한 개, 두 명)
COUNT_ONES = ("", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉")   # 홀로 셀 때 (하나, 둘)
NATIVE_TENS = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")

# 고유어 수로 읽는 단위 (앞의 수가 1 ~ 99일 때)
NATIVE_COUNTERS = ("시", "시간", "살", "개", "명", "번", "번째", "마리", "잔", "권", "장", "대", "벌", "켤레", "가지",
                   "군데", "사람", "병", "그릇", "송이", "채", "척", "통", "바퀴", "걸음", "달", "차례", "끼", "쌍",
                   "자루", "모금", "알")
# 고유어 단위와 앞 글자가 같지만 한자어 수로 읽는 단위
SINO_COUNTERS = ("개월", "개국", "개년", "달러", "시즌", "번지", "번길")
_COUNTERS = sorted([(c, True) for c in NATIVE_COUNTERS] + [(c, False) for c in SINO_COUNTERS],
                   key=lambda x: -len(x[0]))

_NUM = re.compile(r"(?<![0-9.])([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?(\s*%)?")
_SEP = r"(?:\s*,\s*|\.?\s+)"
_SEQ = re.compile(rf"(?<![\w.,])[0-9]{{1,2}}(?:{_SEP}[0-9]{{1,2}})+(?![\w%]|[.,][0-9])")
_ACT_SCENE = re.compile(r"([0-9]+)(\s*막\s*)([0-9]+)(\s*장)")


def sino(n: int) -> str:
    """한자어 수: 15 → 십오, 2026 → 이천이십육, 10000 → 만, 120000000 → 일억이천만."""
    if n == 0:
        return "영"
    if n >= 10 ** 20:
        return digits(str(n))
    out = []
    for big in BIG_UNITS:
        n, group = divmod(n, 10000)
        if group:
            s = ""
            for p in (3, 2, 1, 0):
                d = group // 10 ** p % 10
                if d:
                    s += ("" if d == 1 and p else SINO_DIGITS[d]) + SMALL_UNITS[p]   # 십, 백, 천 앞의 일은 안 읽음
            out.append(("" if big == "만" and group == 1 else s) + big)            # 만 (일만이라고 하지 않음)
        if not n:
            break
    return "".join(reversed(out))


def native(n: int, counting: bool = False) -> str:
    """고유어 수 (1 ~ 99). 단위 앞 꼴(한, 두, 세, 스무) 또는 홀로 셀 때 꼴(하나, 둘, 셋, 스물)."""
    tens, ones = divmod(n, 10)
    if n == 20 and not counting:
        return "스무"
    return NATIVE_TENS[tens] + (COUNT_ONES if counting else NATIVE_ONES)[ones]


def digits(s: str) -> str:
    """한 자씩: 007 → 공공칠."""
    return "".join("공" if c == "0" else SINO_DIGITS[int(c)] for c in s)


def _native_for(n: int, counter: str) -> str | None:
    """고유어 단위 앞의 수. 고유어로 읽지 않는 경우는 None."""
    if not 1 <= n <= 99 or (counter == "시" and n > 12) or (counter == "대" and n % 10 == 0):
        return None
    if counter == "번째" and n == 1:
        return "첫"
    return native(n)


def _read(m: re.Match) -> str:
    whole, frac, pct = m.group(1).replace(",", ""), m.group(2), m.group(3)
    rest = m.string[m.end():]
    after = rest.lstrip()
    n = int(whole)
    if frac is not None:                                   # 3.5 → 삼점오
        s = sino(n) + "점" + digits(frac).replace("공", "영")
    elif len(whole) > 1 and whole[0] == "0":               # 007 → 공공칠
        s = digits(whole)
    elif not pct and rest[:1] in ("십", "백", "천", "만"):     # 1만 → 만, 30만 → 삼십만
        s = "" if n == 1 else sino(n)
    elif not pct and after.startswith("월"):                 # 6월 → 유월, 10월 → 시월
        s = {6: "유", 10: "시"}.get(n) or sino(n)
    else:
        s = None
        if not pct:
            for counter, is_native in _COUNTERS:
                if after.startswith(counter):
                    s = _native_for(n, counter) if is_native else None
                    break
        s = s or sino(n)
    if pct:
        s += pct.replace("%", "퍼센트")
    return s


def _count(m: re.Match) -> str:
    """1 2 3 처럼 1씩 늘며 이어 세는 10 이하의 수 → 하나 둘 셋. 아니면 그대로 (뒤에서 한자어 수로)."""
    nums = [int(x) for x in re.findall(r"[0-9]+", m.group(0))]
    if not all(1 <= v <= 10 for v in nums) or any(b != a + 1 for a, b in zip(nums, nums[1:])):
        return m.group(0)
    return re.sub(r"[0-9]+", lambda d: native(int(d.group(0)), counting=True), m.group(0))


def read_numbers(text: str) -> str:
    """글자 속 숫자를 한글 읽기로 바꾼다. 숫자가 없으면 그대로."""
    if not text or not re.search(r"[0-9]", text):
        return text
    text = _ACT_SCENE.sub(lambda m: sino(int(m[1])) + m[2] + sino(int(m[3])) + m[4], text)
    text = _SEQ.sub(_count, text)
    return _NUM.sub(_read, text)
