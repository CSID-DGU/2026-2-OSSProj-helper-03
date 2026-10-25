from engine.aligner import Aligner


def dialogue(cues):
    return [c for c in cues if c.type == "dialogue"]


def test_follows_script_in_order(sample_cues):
    al = Aligner(sample_cues)
    for c in dialogue(sample_cues)[:6]:
        step = al.update(c.text)
        assert step.matched and al.current.id == c.id


def test_short_text_is_skipped(sample_cues):
    al = Aligner(sample_cues)
    step = al.update("네")
    assert step.status == "skip" and not step.heard


def test_far_jump_needs_confirmation(sample_cues):
    al = Aligner(sample_cues, strong=101, far=0)   # 긴 문장 즉시 이동 · 먼 이동 근거는 끄고 확인 규칙만 본다
    lines = dialogue(sample_cues)
    target = lines[8]
    first = al.update(target.text)
    assert first.status == "pending" and al.current.id != target.id
    second = al.update(target.text)
    assert second.status == "move" and al.current.id == target.id


def test_off_script_speech_is_a_miss(sample_cues):
    al = Aligner(sample_cues)
    al.update(dialogue(sample_cues)[0].text)
    step = al.update("아 오늘 비 진짜 많이 오네 여러분 우산 챙기셨어요")
    assert step.heard and not step.matched


def test_jump_to_and_hints(sample_cues):
    al = Aligner(sample_cues)
    target = dialogue(sample_cues)[5]
    assert al.jump_to(target.id)
    hints = al.hint_cues(3)
    assert hints[0].id == target.id and len(hints) == 4


def test_text_spanning_cues_moves_to_the_later_one(sample_cues):
    """한 조각에 대사 두 줄이 들어 있으면 뒤쪽(방금 말한) 큐로 간다 (anchor=end)."""
    al = Aligner(sample_cues)
    lines = dialogue(sample_cues)
    step = al.update(lines[0].text + " " + lines[1].text)
    assert step.matched and al.current.id == lines[1].id


def test_fast_exchange_moves_several_cues_at_once(sample_cues):
    """짧은 대사가 빠르게 오가 한 번에 3~4큐를 지나가도 확인 없이 바로 따라간다 (small_step=4)."""
    al = Aligner(sample_cues, strong=101)
    lines = dialogue(sample_cues)
    al.update(lines[0].text)
    step = al.update(lines[3].text)
    assert step.status == "move" and al.current.id == lines[3].id


def test_lost_prefers_nearest_repeat():
    """같은 대사가 대본에 두 번 있으면, 놓친 상태에서도 가까운 쪽으로 간다 (near_first)."""
    from engine.cue_loader import parse_cues
    rows = ["id,order,type,speaker,text"]
    words = ["처음 인사를 드립니다", "오늘은 날씨가 맑네요", "자 이제 해봅시다", "점심은 무엇을 먹을까",
             "저녁에는 비가 온대요", "우산을 챙겨야겠네요", "버스가 곧 도착합니다", "다음 역에서 내려요",
             "자 이제 해봅시다", "모두 수고하셨습니다"]
    rows += [f"{i},{i},dialogue,가,{w}" for i, w in enumerate(words, 1)]
    cues = parse_cues("\n".join(rows) + "\n")
    al = Aligner(cues, ahead=3)
    al.update("오늘은 날씨가 맑네요")
    for _ in range(3):                                 # 대본에 없는 말로 놓친 상태 만들기
        al.update("전혀 상관없는 이야기를 길게 합니다")
    assert al.lost
    al.update("자 이제 해봅시다")
    assert al.current.id == 3                          # 9번이 아니라 가까운 3번


def test_jump_over_unheard_lines_reports_skipped(sample_cues):
    """배우가 대사 두 줄을 건너뛰면, 지나친 두 줄이 Step.skipped 에 들어간다 (누락 근거)."""
    al = Aligner(sample_cues)
    lines = dialogue(sample_cues)
    al.update(lines[0].text)
    al.update(lines[1].text)
    step = al.update(lines[4].text)
    assert step.matched and al.current.id == lines[4].id
    assert [c.id for c in step.skipped] == [lines[2].id, lines[3].id]


def test_passing_heard_lines_is_not_a_skip(sample_cues):
    """한 조각에 여러 줄이 들어 있어 한 번에 지나가도, 들은 줄은 skipped 가 아니다."""
    al = Aligner(sample_cues)
    lines = dialogue(sample_cues)
    al.update(lines[0].text)
    step = al.update(" ".join(c.text for c in lines[1:4]))
    assert al.current.id == lines[3].id and step.skipped == ()


def test_going_back_to_a_heard_line_is_again(sample_cues):
    al = Aligner(sample_cues)
    lines = dialogue(sample_cues)
    for c in lines[:5]:
        al.update(c.text)
    al.update(lines[2].text)
    step = al.update(lines[2].text)               # 뒤로 가는 이동은 두 번 확인
    assert step.matched and al.current.id == lines[2].id and step.again


def _scene_cues(with_scene: bool):
    from engine.cue_loader import parse_cues
    words = ["처음 인사를 드립니다", "오늘은 날씨가 맑네요", "점심은 무엇을 먹을까", "저녁에는 비가 온대요",
             "우산을 챙겨야겠네요", "버스가 곧 도착합니다", "다음 역에서 내려요", "모두 수고하셨습니다",
             "창문을 조금 열어 둘까", "커피를 한 잔 더 주세요", "내일 아침에 다시 만나요", "기차표를 미리 사 두었어"]
    if with_scene:   # 장면 셋: 1-1 (1~4), 1-2 (5~8), 2-1 (9~12)
        rows = ["cue_id,act,scene,type,speaker,text_ko"]
        rows += [f"{i},{1 if i <= 8 else 2},{1 if i <= 4 or i > 8 else 2},대사,가,{w}" for i, w in enumerate(words, 1)]
    else:
        rows = ["id,order,type,speaker,text"] + [f"{i},{i},dialogue,가,{w}" for i, w in enumerate(words, 1)]
    return parse_cues("\n".join(rows) + "\n")


def lose(al):
    al.update("오늘은 날씨가 맑네요")
    for _ in range(3):
        al.update("전혀 상관없는 이야기를 길게 합니다")
    assert al.lost


def test_lost_search_stays_in_scene_and_next_scene():
    cues = _scene_cues(True)
    assert cues[0].scene == "1-1" and cues[8].scene == "2-1"
    al = Aligner(cues, ahead=1, far=0)                 # 먼 이동 근거는 따로 시험
    lose(al)
    al.update("내일 아침에 다시 만나요")              # 2막 1장 (현재 장면 + 다음 장면 밖) → 못 감
    assert al.current.id == 2
    al.update("다음 역에서 내려요")                   # 다음 장면(1막 2장)은 찾는다
    al.update("다음 역에서 내려요")
    assert al.current.id == 7


def test_lost_search_window_without_scene_info():
    cues = _scene_cues(False)
    assert cues[0].scene == ""
    al = Aligner(cues, ahead=1, lost_window=4)
    lose(al)
    al.update("내일 아침에 다시 만나요")              # 11번: 4큐 창 밖
    assert al.current.id == 2
    al = Aligner(cues, ahead=1, lost_window=0, pace=0, far=0)   # 0 = 끝까지 (개선 전). 빠르기 · 먼 이동 확인은 따로 시험
    lose(al)
    al.update("내일 아침에 다시 만나요")
    al.update("내일 아침에 다시 만나요")
    assert al.current.id == 11


def test_stale_candidate_does_not_confirm_a_far_jump(sample_cues):
    """한참 전에 한 번 나온 큰 이동 후보는 버린다 (예전에는 1분 뒤 엉뚱한 말 한 번으로 10큐 넘게 튐)."""
    lines = dialogue(sample_cues)
    al = Aligner(sample_cues, strong=101, pace=0, far=0)
    al.update(lines[0].text, 3)
    assert al.update(lines[8].text, 6).status == "pending"
    for t in range(9, 33, 3):                          # 대본과 상관없는 말이 이어짐
        al.update("전혀 상관없는 이야기를 길게 합니다", t)
    step = al.update(lines[8].text, 33)                # 27초 뒤 다시: 새 후보로만 셈
    assert step.status == "pending" and al.current.id == lines[0].id
    al = Aligner(sample_cues, strong=101, pace=0, pending_sec=0, far=0)   # 개선 전: 오래된 후보로 이동
    al.update(lines[0].text, 3)
    al.update(lines[8].text, 6)
    for t in range(9, 33, 3):
        al.update("전혀 상관없는 이야기를 길게 합니다", t)
    assert al.update(lines[8].text, 33).status == "move"


def test_too_fast_jump_needs_one_more_confirmation(sample_cues):
    """지나칠 대사를 사람이 말할 수 없는 빠르기로 건너뛰면 긴 문장이라도 바로 안 가고, 확인을 한 번 더 받는다.
    오래 뒤처졌다가 따라잡는 이동(지나친 대사를 말할 시간이 있었음)은 그대로."""
    lines = dialogue(sample_cues)
    target = lines[10]
    al = Aligner(sample_cues, far=0)                   # 먼 이동 확인은 따로 시험
    al.update(lines[0].text, 3)
    assert al._too_fast(al.items.index(target))
    assert al.update(target.text, 4.5).status == "pending"        # 긴 문장 100점이어도 바로 안 감
    assert al.update(target.text, 6).status == "pending"          # 두 번으로는 부족
    assert al.update(target.text, 7.5).status == "move"
    al = Aligner(sample_cues, far=0)
    al.update(lines[0].text, 3)
    for t in range(6, 120, 3):                         # 2분 가까이 못 따라감 (지나친 대사를 말할 시간 충분)
        al.update("", t)
    assert not al._too_fast(al.items.index(target))
    assert al.update(target.text, 120).status == "move"           # 긴 문장이 확실히 맞으면 바로


def _chunks(*parts: str):
    """겹친 조각처럼: 같은 말이 앞뒤 조각에 두 번씩 들어간다."""
    out = []
    for p in parts:
        out += [p, p]
    return out


def test_one_line_adlib_matching_a_far_line_does_not_jump(sample_cues):
    """애드리브 한마디가 20큐 뒤 짧은 대사(#127 "무슨 말인데요?")와 똑같아도 그리로 튀지 않는다.
    배우가 대본으로 돌아오면(#109) 그대로 따라간다. (예전: 겹친 조각에 두 번 들어가 확인 두 번 → 20큐 건너뜀)"""
    byid = {c.id: c for c in sample_cues}
    al = Aligner(sample_cues, start_id=108)
    t = 0.0
    for text in _chunks(byid[127].text, byid[127].text, "그러니까 내 말은", byid[127].text):
        t += 1.5
        step = al.update(text, t)
        assert al.current.id == 108, (text, step)
    assert al.update(byid[109].text, t + 1.5).matched and al.current.id == 109
    old = Aligner(sample_cues, start_id=108, far=0)                # 예전: 놓침 3번 뒤 확인 두 번으로 20큐를 건너뜀
    for i, text in enumerate(_chunks(byid[127].text, byid[127].text, byid[127].text)):
        old.update(text, 1.5 * (i + 1))
    assert old.current.id == 127


def test_far_lines_heard_right_away_wait_for_the_operator(sample_cues):
    """말소리를 계속 듣고 있었는데 20큐 뒤 대사(#127 → #128)가 이어서 나오면, 애드리브인지 정말 건너뛴 것인지 모르므로
    따라가지 않고 그 자리에 머문다 (이탈 알림이 뜨고, 정말 건너뛰었으면 오퍼레이터가 위치를 맞춤)."""
    byid = {c.id: c for c in sample_cues}
    al = Aligner(sample_cues, start_id=108)
    t = 0.0
    for text in _chunks(byid[127].text, byid[127].text + " " + byid[128].text, byid[128].text):
        t += 1.5
        al.update(text, t)
        assert al.current.id == 108
    assert al.jump_to(128) and al.update(byid[128].text, t + 1.5).matched and al.current.id == 128
    old = Aligner(sample_cues, start_id=108, far=0)                # 예전: 그대로 따라감
    for i, text in enumerate(_chunks(byid[127].text, byid[127].text + " " + byid[128].text, byid[128].text)):
        old.update(text, 1.5 * (i + 1))
    assert old.current.id == 128


def _long_line_cues():
    from engine.cue_loader import parse_cues
    words = ["처음 인사를 드립니다", "오늘은 날씨가 맑네요", "점심은 무엇을 먹을까", "저녁에는 비가 온대요",
             "우산을 챙겨야겠네요", "버스가 곧 도착합니다", "다음 역에서 내려요", "모두 수고하셨습니다",
             "오늘 밤에는 바람이 아주 많이 불고 비도 내린다고 들었어요", "커피를 한 잔 더 주세요"]
    rows = ["id,order,type,speaker,text"] + [f"{i},{i},dialogue,가,{w}" for i, w in enumerate(words, 1)]
    return words, parse_cues("\n".join(rows) + "\n")


def test_catches_up_after_recognition_gap():
    """인식 글자가 한동안 없었으면(인터넷 · 마이크 끊김) 배우는 그사이 대본을 이어 갔으므로, 멀리 있는 대사를
    충분히(약 16음절 넘게) 들으면 따라잡는다. 끊김 없이 바로 같은 말이 나오면 머문다."""
    words, cues = _long_line_cues()
    al = Aligner(cues)
    al.update(words[0], 1.5)
    for t in (3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0):       # 10초 넘게 인식 글자 없음 (그동안 2~8번 대사)
        al.update("", t)
    al.update(words[8], 13.5)
    al.update(words[8], 15.0)
    assert al.current.id == 9
    al = Aligner(cues)
    al.update(words[0], 1.5)
    for t in (3.0, 4.5, 6.0):
        al.update(words[8], t)
    assert al.current.id == 1


def test_parse_settings():
    from engine.aligner import parse_settings
    assert parse_settings("") == {}
    assert parse_settings("ahead=10, lost_window=20,pace=6.5,anchor=mid") ==         {"ahead": 10, "lost_window": 20, "pace": 6.5, "anchor": "mid"}
    import pytest
    with pytest.raises(ValueError):
        parse_settings("ahaed=10")
