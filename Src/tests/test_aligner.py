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
