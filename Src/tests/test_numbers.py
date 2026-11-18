import pytest

from engine.aligner import Aligner
from engine.cue_loader import parse_cues, syllables, to_jamo
from engine.numbers import read_numbers, sino


@pytest.mark.parametrize("text, read", [
    ("3시 30분", "세시 삼십분"),            # 시는 고유어, 분은 한자어
    ("3시간", "세시간"),
    ("13시", "십삼시"),                   # 시는 12까지만 고유어
    ("11월 13일에", "십일월 십삼일에"),
    ("6월", "유월"), ("10월", "시월"),
    ("2026년", "이천이십육년"),
    ("30만 원", "삼십만 원"), ("1만 원", "만 원"), ("1억", "일억"), ("1천만 원", "천만 원"), ("1,000원", "천원"),
    ("75달러", "칠십오달러"), ("3달", "세달"),
    ("3개월", "삼개월"), ("3개", "세개"),     # 긴 단위부터 맞춤
    ("4학년", "사학년"),
    ("20살", "스무살"), ("21살", "스물한살"), ("100살", "백살"),
    ("3번", "세번"), ("1번째", "첫번째"), ("11번째", "열한번째"), ("3번지", "삼번지"),
    ("2막 3장", "이막 삼장"), ("종이 3장", "종이 세장"),
    ("20대", "이십대"), ("차 2대", "차 두대"),
    ("50%", "오십퍼센트"), ("3.5", "삼점오"), ("3.05", "삼점영오"), ("007", "공공칠"),
    ("1, 2, 3", "하나, 둘, 셋"), ("1 2 3 4 5 6 7 8 9 10", "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열"),
    ("70 30", "칠십 삼십"),                 # 이어 세는 수가 아니면 한자어
    ("비가 오네.", "비가 오네."),
])
def test_read_numbers(text, read):
    assert read_numbers(text) == read


def test_sino():
    assert [sino(n) for n in (0, 15, 110, 1004, 10000, 11000, 120000000)] == \
        ["영", "십오", "백십", "천사", "만", "만천", "일억이천만"]


def test_digits_and_words_compare_the_same():
    """대본은 한글로, 음성인식은 숫자로 적어도 같은 자모로 비교한다. 음절 수는 읽는 소리로."""
    assert to_jamo("3시까지 와. 30분 넘으면 안 기다려.") == to_jamo("세 시까지 와. 삼십 분 넘으면 안 기다려.")
    assert syllables("3시 30분") == 5


def test_aligner_follows_line_heard_with_digits():
    cues = parse_cues("id,order,type,speaker,text\n"
                      "1,1,dialogue,가,오늘은 일찍 문을 닫자.\n"
                      "2,2,dialogue,나,세 시까지 꼭 와야 해. 삼십 분 넘으면 안 기다려.\n"
                      "3,3,dialogue,가,알았어. 스무 살 생일 선물 사 갈게.\n")
    al = Aligner(cues)
    al.update("오늘은 일찍 문을 닫자.", 3.0)
    step = al.update("3시까지 꼭 와야 해. 30분 넘으면 안 기다려.", 6.0)
    assert al.current.id == 2 and step.score == 100
    al.update("알았어. 20살 생일 선물 사 갈게.", 9.0)
    assert al.current.id == 3
