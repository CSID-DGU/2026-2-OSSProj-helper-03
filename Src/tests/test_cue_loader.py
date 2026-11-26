import json

import pytest

from engine.cue_loader import load_cues, parse_cues, to_jamo, to_ui_csv


def test_sample_csv_ui_format(sample_cues):
    assert len(sample_cues) == 30
    assert [c.id for c in sample_cues[:3]] == [101, 102, 103]
    assert sample_cues[0].type == "notice"
    assert sample_cues[2].type == "dialogue" and sample_cues[2].speaker == "민수"


def test_data_format_with_korean_types():
    src = "﻿cue_id,act,scene,type,speaker,text_ko\n1,1,1,대사,민수,안녕하세요.\n2,1,1,가사,민수,바람이 부네\n3,1,1,음향,,문 닫히는 소리\n"
    cues = parse_cues(src)
    assert [(c.id, c.order, c.type) for c in cues] == [(1, 1, "dialogue"), (2, 2, "lyric"), (3, 3, "sound")]


def test_unknown_type_reports_line():
    with pytest.raises(ValueError, match="3번째 줄"):
        parse_cues("id,order,type,speaker,text\n1,1,dialogue,a,b\n2,2,dance,a,b\n")


def test_unknown_columns():
    with pytest.raises(ValueError, match="열 구성"):
        parse_cues("num,line\n1,hello\n")


def test_to_ui_csv_round_trip(sample_cues):
    again = parse_cues(to_ui_csv(sample_cues))
    assert [(c.id, c.type, c.text) for c in again] == [(c.id, c.type, c.text) for c in sample_cues]


def test_jamo_ignores_symbols():
    assert to_jamo("안녕!") == to_jamo("안 녕.") == "ㅇㅏㄴㄴㅕㅇ"


def subtitle_json(contents, language=("kor", "eng")) -> str:
    return json.dumps({"language": list(language), "contents": contents,
                       "advertisements": [{"image_url": "https://example.com/ad.png"}]}, ensure_ascii=False)


def line(idx, kor=None, eng=None, **extra):
    subs = [{"lang": k, "text": v} for k, v in (("kor", kor), ("eng", eng)) if v is not None]
    return {"idx": idx, "subtitles": subs, **extra}


def test_subtitle_json_uses_idx_and_korean_text():
    """오롯플래닛 자막 파일: idx 가 큐 번호, kor 문장이 추적 대사, 순서는 파일 순서."""
    cues = parse_cues("﻿\n" + subtitle_json([line(1, "안녕하세요", "Hello"), line(2, "반갑습니다", "Nice to meet you")]))
    assert [(c.id, c.order, c.type, c.text) for c in cues] == [(1, 1, "dialogue", "안녕하세요"),
                                                              (2, 2, "dialogue", "반갑습니다")]
    assert cues[0].jamo == to_jamo("안녕하세요")


def test_subtitle_json_line_without_korean_is_not_tracked():
    """kor 문장이 비어 있는 줄(영어만 있는 안내 등)은 안내로 두어 위치 추적에 안 쓴다."""
    cues = parse_cues(subtitle_json([line(1, "안녕하세요"), line(2, eng="Intermission"), line(3, "")]))
    assert [(c.id, c.type) for c in cues] == [(1, "dialogue"), (2, "notice"), (3, "notice")]


def test_subtitle_json_optional_type_and_speaker():
    cues = parse_cues(subtitle_json([line(7, "바람이 부네", type="가사", speaker="민수"), line(8, type="blackout")]))
    assert [(c.id, c.type, c.speaker) for c in cues] == [(7, "lyric", "민수"), (8, "blackout", "")]


def test_subtitle_json_load_file(tmp_path):
    path = tmp_path / "show.json"
    path.write_text(subtitle_json([line(3, "세 시에 만나"), line(4, "좋아")]), encoding="utf-8-sig")
    assert [c.id for c in load_cues(path)] == [3, 4]


@pytest.mark.parametrize("source, message", [
    ('{"contents": [', "읽을 수 없습니다"),
    ('{"language": ["kor"]}', "contents"),
    (subtitle_json([line("1", "안녕")]), "1번째 자막: idx"),
    (subtitle_json([line(1, "안녕"), line(1, "또")]), r"이미 나온 idx\(1\)"),
    (subtitle_json([line(1, "안녕", type="dance")]), "알 수 없는 유형"),
    (subtitle_json([line(1, eng="Hello")], language=("eng",)), "kor 문장이 없습니다"),
])
def test_subtitle_json_errors(source, message):
    with pytest.raises(ValueError, match=message):
        parse_cues(source)


def test_server_reads_subtitle_json_from_screen():
    """화면이 고른 자막 파일 내용(cue_csv 칸)도 그대로 읽는다."""
    import server.main as srv

    cues, path, name = srv.read_cues({"cue_file": "show.json", "cue_csv": subtitle_json([line(5, "안녕")])}, "browser")
    assert [c.id for c in cues] == [5] and path is None and name == "show.json"
