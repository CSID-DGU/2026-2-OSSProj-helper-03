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
