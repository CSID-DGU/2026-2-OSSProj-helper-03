"""① 큐 시트 로더 + 정규화.

두 가지 CSV 열 구성을 모두 받는다 (열 이름이 팀에서 확정될 때까지).
- 화면(ui/src/cues.ts) 형식: id, order, type, speaker, text
- 1차 데이터 형식:          cue_id, act, scene, type, speaker, text_ko
유형은 dialogue/lyric/sound/blackout/notice 또는 대사/가사/음향/암전/안내.
"""
import csv
import io
import re
from dataclasses import dataclass

from jamo import h2j, j2hcj

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
    """기호·공백을 빼고 한글·영문·숫자만 남긴다."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "")


def to_jamo(text: str) -> str:
    return j2hcj(h2j(normalize(text)))


def parse_cues(source: str) -> list[Cue]:
    """CSV 문자열 → Cue 목록 (order 순). 형식이 틀리면 ValueError (줄 번호 포함)."""
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
