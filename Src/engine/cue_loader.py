"""① 큐 시트 로더 + 정규화.

두 가지 CSV 열 구성과 오롯플래닛 자막 파일(JSON)을 받는다.
- 화면(ui/src/cues.ts) 형식: id, order, type, speaker, text
- 1차 데이터 형식:          cue_id, act, scene, type, speaker, text_ko
- 자막 파일(JSON):           {"language": [...], "contents": [{"idx": 1, "subtitles": [{"lang": "kor", "text": ...}]}]}
                             (parse_subtitle_json 참고. 내용이 "{" 로 시작하면 자막 파일로 본다)
유형은 dialogue/lyric/sound/blackout/notice 또는 대사/가사/음향/암전/안내.
"""
import csv
import io
import json
import re
from dataclasses import dataclass

from jamo import h2j, j2hcj

from .numbers import read_numbers

TYPE_ALIASES = {
    "dialogue": "dialogue", "대사": "dialogue",
    "lyric": "lyric", "가사": "lyric",
    "sound": "sound", "음향": "sound",
    "blackout": "blackout", "암전": "blackout",
    "notice": "notice", "안내": "notice",
}
# 소리로 위치를 알 수 있는 큐
TRACK_TYPES = ("dialogue", "lyric")


@dataclass
class Cue:
    id: int
    order: int
    type: str       # dialogue / lyric / sound / blackout / notice
    speaker: str
    text: str
    jamo: str = ""  # 정규화 + 자모 분해 (추적용)
    scene: str = ""  # 막-장 ("1-2"). act · scene 열이 있을 때만 (놓친 뒤 다시 찾는 범위를 장면으로 제한)


def normalize(text: str) -> str:
    """숫자를 한글 읽기로 바꾸고(numbers.py, "3시" → "세시") 기호·공백을 빼서 한글·영문·숫자만 남긴다."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", read_numbers(text or ""))


def syllables(text: str) -> int:
    """한글 음절 수 (숫자는 읽는 소리로 셈: "3시 30분" = 5). 말하는 데 드는 시간 계산용."""
    return len(re.findall(r"[가-힣]", read_numbers(text or "")))


def to_jamo(text: str) -> str:
    return j2hcj(h2j(normalize(text)))


def parse_cues(source: str) -> list[Cue]:
    """CSV 또는 자막 파일(JSON) 문자열 → Cue 목록 (order 순). 형식이 틀리면 ValueError (줄 번호 포함)."""
    if source.lstrip("﻿ \t\r\n").startswith("{"):
        return parse_subtitle_json(source)
    rows = list(csv.DictReader(io.StringIO(source.lstrip("﻿"))))
    if not rows:
        raise ValueError("빈 파일입니다.")
    cols = set(rows[0].keys())
    if {"id", "order", "type", "text"} <= cols:
        id_col, order_col, text_col = "id", "order", "text"
    elif {"cue_id", "type", "text_ko"} <= cols:
        id_col, order_col, text_col = "cue_id", None, "text_ko"
    else:
        raise ValueError(f"알 수 없는 열 구성: {sorted(cols)}")

    cues = []
    for i, r in enumerate(rows):
        line = i + 2
        try:
            cid = int(r[id_col])
            order = int(r[order_col]) if order_col else i + 1
        except (TypeError, ValueError):
            raise ValueError(f"{line}번째 줄: 큐 번호가 숫자가 아닙니다.") from None
        ctype = TYPE_ALIASES.get((r.get("type") or "").strip())
        if ctype is None:
            raise ValueError(f'{line}번째 줄: 알 수 없는 유형 "{r.get("type")}"')
        text = (r.get(text_col) or "").strip()
        act, scene = (r.get("act") or "").strip(), (r.get("scene") or "").strip()
        cues.append(Cue(cid, order, ctype, (r.get("speaker") or "").strip(), text, to_jamo(text),
                        f"{act}-{scene}" if act or scene else ""))
    return sorted(cues, key=lambda c: c.order)


def parse_subtitle_json(source: str, lang: str = "kor") -> list[Cue]:
    """오롯플래닛 자막 파일(JSON) → Cue 목록 (#46).

    - idx 를 큐 번호로 쓴다. 송출 신호 index 의 subtitle_idx 와 같은 번호라 번호 연결표가 필요 없다
    - 순서는 파일에 적힌 순서. idx 가 겹치면 송출 번호가 헷갈려서 오류
    - 추적 대사는 lang(기본 kor) 문장. 그 언어 문장이 비어 있는 줄은 안내(notice)로 두어 추적하지 않는다
    - 자막 파일에는 유형과 화자가 없어서 대사(dialogue)로 본다. 줄에 type, speaker 칸이 있으면 그 값을 쓴다
      (우리가 더해 쓰는 칸. 가사 줄에 type 을 적어 두면 노래 구간에서 이탈 알림을 끈다)
    - 다른 언어 문장과 advertisements 는 위치 추적에 쓰지 않아 읽지 않는다
    """
    try:
        data = json.loads(source.lstrip("﻿"))
    except json.JSONDecodeError as e:
        raise ValueError(f"자막 파일(JSON)을 읽을 수 없습니다: {e.lineno}번째 줄 {e.msg}") from None
    contents = data.get("contents") if isinstance(data, dict) else None
    if not isinstance(contents, list) or not contents:
        raise ValueError('자막 파일에 "contents" 목록이 없습니다.')

    cues, seen = [], set()
    for i, item in enumerate(contents):
        n = i + 1
        idx = item.get("idx") if isinstance(item, dict) else None
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise ValueError(f"{n}번째 자막: idx가 숫자가 아닙니다.")
        if idx in seen:
            raise ValueError(f"{n}번째 자막: 앞에서 이미 나온 idx({idx})입니다.")
        seen.add(idx)
        subs = item.get("subtitles") or []
        text = next((str(s.get("text") or "").strip() for s in subs
                     if isinstance(s, dict) and s.get("lang") == lang), "")
        raw_type = str(item.get("type") or "").strip()
        ctype = TYPE_ALIASES.get(raw_type) if raw_type else ("dialogue" if text else "notice")
        if ctype is None:
            raise ValueError(f'{n}번째 자막 (idx {idx}): 알 수 없는 유형 "{raw_type}"')
        cues.append(Cue(idx, n, ctype, str(item.get("speaker") or "").strip(), text, to_jamo(text)))
    if not any(c.text for c in cues):
        raise ValueError(f"자막 파일에 {lang} 문장이 없습니다 (위치 추적에 쓰는 언어).")
    return cues


def load_cues(path) -> list[Cue]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return parse_cues(f.read())


def to_ui_csv(cues: list[Cue]) -> str:
    """화면 형식 CSV (id, order, type, speaker, text) 로 내보내기."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "order", "type", "speaker", "text"])
    for c in cues:
        w.writerow([c.id, c.order, c.type, c.speaker, c.text])
    return buf.getvalue()
