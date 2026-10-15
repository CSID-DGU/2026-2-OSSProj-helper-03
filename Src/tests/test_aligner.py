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
    al = Aligner(sample_cues, strong=101)   # 긴 문장 즉시 이동은 끄고 확인 규칙만 본다
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
    al = Aligner(cues, ahead=1)
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
    al = Aligner(cues, ahead=1, lost_window=0)        # 0 = 끝까지 (개선 전)
    lose(al)
    al.update("내일 아침에 다시 만나요")
    al.update("내일 아침에 다시 만나요")
    assert al.current.id == 11
