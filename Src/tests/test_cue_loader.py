import pytest

from engine.cue_loader import parse_cues, to_jamo, to_ui_csv


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
