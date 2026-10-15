"""가짜 음성인식 + 30배속 재생으로 파이프라인 전체를 돌려 본다 (소리 · API 없이)."""
import threading
import time

import numpy as np
from conftest import FakeSTT

from engine.pipeline import Pipeline, implausible
from engine.stt import make_engine
from engine.stt.base import STTEngine


def run(cues, audio, texts, **kw):
    msgs = []
    stt = FakeSTT(texts)
    pipe = Pipeline(cues, audio, stt, msgs.append, speed=30, **kw)
    pipe.start()
    pipe.source.done.wait(timeout=10)     # 녹음 끝까지
    time.sleep(0.3)                        # 마지막 인식 처리
    pipe.stop()
    pipe.join(timeout=5)
    return msgs, stt


def test_status_continues_after_audio_ends(sample_cues):
    msgs = []
    pipe = Pipeline(sample_cues, np.zeros(16000 * 3, dtype="float32"), FakeSTT([]), msgs.append, speed=30)
    pipe.start()
    pipe.source.done.wait(timeout=5)
    time.sleep(2.2)                        # 녹음이 끝난 뒤에도 1초마다 상태가 와야 화면이 '응답 없음'을 띄우지 않음
    pipe.stop()
    pipe.join(timeout=5)
    after = [m for m in msgs if m["type"] == "input.status" and m["audio_level"] == 0]
    assert len(after) >= 2


def of(msgs, kind):
    return [m for m in msgs if m["type"] == kind]


def test_follows_and_sends_status(sample_cues, silence):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    msgs, stt = run(sample_cues, silence, [c.text for c in lines[:5]])
    pos = of(msgs, "position.update")
    assert [m["cue_id"] for m in pos] == [c.id for c in lines[:5]]
    assert all(0 <= m["confidence"] <= 1 for m in pos)
    assert of(msgs, "input.status")                       # 상태 메시지가 간다
    assert stt.hints_seen[0] and stt.hints_seen[0][0]     # 대본 힌트가 엔진에 들어간다


def test_deviation_start_and_return(sample_cues, silence):
    lines = [c for c in sample_cues if c.type == "dialogue"]
    off = ["아 오늘 비 진짜 많이 오네 여러분", "근데 이 차 너무 뜨거운데 정말로", "잠깐만 내가 무슨 말 하려고 했지"]
    texts = [lines[0].text, lines[1].text] + off + [lines[4].text]
    msgs, _ = run(sample_cues, silence, texts, deviate_after=0.1)
    alerts = of(msgs, "deviation.alert")
    assert len(alerts) == 2
    assert alerts[0]["return_cue_id"] is None
    assert alerts[1]["return_cue_id"] == lines[4].id and alerts[1]["since"] == alerts[0]["since"]
    assert alerts[1]["deviation_type"] == "skip"           # 2번째 줄 → 5번째 줄 = 건너뜀


def test_implausible_filter():
    assert implausible("가" * 30, "", 3)                   # 3초에 30음절
    assert implausible("우산 챙겨", "우산 챙겨", 3)              # 직전과 똑같음
    assert implausible("아 아 아 아", "", 3)                 # 같은 말 반복
    assert not implausible("빛이 다시 돌아올 거예요", "", 3)


def test_overlapping_chunks(sample_cues, silence):
    """3초 조각을 1.5초마다 보내면 인식 횟수가 두 배 가까이 되고, 조각 길이는 3초를 유지한다."""
    seen = []

    class Recorder(FakeSTT):
        def transcribe(self, audio, hints=None):
            seen.append(len(audio))
            return super().transcribe(audio, hints)

    msgs = []
    pipe = Pipeline(sample_cues, silence[:16000 * 12], Recorder([]), msgs.append, speed=30,
                    chunk_sec=3.0, hop_sec=1.5)
    pipe.start()
    pipe.source.done.wait(timeout=5)
    time.sleep(0.3)
    pipe.stop()
    pipe.join(timeout=5)
    assert len(seen) >= 7                                  # 12초 / 1.5초 = 8번 (3초 미만 첫 조각 포함)
    assert max(seen) == 16000 * 3                          # 조각 길이는 3초


# ── 동시 인식 요청 (느린 엔진) ───────────────────────────────
def clock_audio(sec: float) -> np.ndarray:
    """샘플 값 = 시각(초) / 100 인 가짜 소리. 가짜 음성인식이 조각 끝 시각을 알 수 있게."""
    return (np.arange(int(sec * 16000)) / 16000 / 100).astype("float32")


class SlowSTT(STTEngine):
    """조각 끝 시각마다 정해 둔 글자를 정해 둔 시간 뒤에 돌려준다 (동시에 여러 번 불려도 됨)."""
    key = label = "slow"
    mode = "chunk"

    def __init__(self, texts: dict[float, str], delay):
        self.texts, self.delay = texts, delay
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def transcribe(self, audio, hints=None):
        end = round(float(audio[-1]) * 100 * 2) / 2     # 0.5초 단위
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay(end))
        with self.lock:
            self.active -= 1
        return self.texts.get(end, "")


def run_slow(cues, stt, workers, sec=9.0):
    """10배속, 3초 조각을 1.5초마다. 인식 스레드가 남은 결과까지 처리하고 끝날 때까지 기다린다."""
    msgs = []
    pipe = Pipeline(cues, clock_audio(sec), stt, msgs.append, speed=10, chunk_sec=3.0, hop_sec=1.5,
                    stt_workers=workers)
    pipe.start()
    for th in pipe.threads:
        if th.name.endswith("_chunk_loop"):
            th.join(timeout=5)
    pipe.stop()
    pipe.join(timeout=5)
    return pipe, [m["transcript"] for m in of(msgs, "position.update")]


def test_concurrent_requests_keep_up_in_order(sample_cues):
    """인식이 간격보다 느려도(2.5초 > 1.5초) 동시에 보내면 조각을 건너뛰지 않고, 결과는 조각 순서대로."""
    lines = [c.text for c in sample_cues if c.type == "dialogue"]
    ends = [1.5 * (i + 1) for i in range(6)]            # 9초 녹음 → 조각 끝 1.5, 3, ..., 9초
    texts = dict(zip(ends, lines))

    pipe, shown = run_slow(sample_cues, SlowSTT(texts, lambda end: 0.25), workers=1)
    assert pipe.stats["skipped"] > 0 and len(pipe.records) < len(ends)    # 하나씩이면 밀려서 건너뜀
    assert shown == sorted(shown, key=lines.index)

    stt = SlowSTT(texts, lambda end: 0.25)
    pipe, shown = run_slow(sample_cues, stt, workers=3)
    assert stt.peak >= 2                                                   # 실제로 동시에 보냄
    assert [r["chunk_end"] for r in pipe.records] == ends
    assert pipe.stats == {"skipped": 0, "late": 0}
    assert shown == lines[:6]                                              # 처리는 조각 순서대로


def test_late_result_is_dropped(sample_cues):
    """앞 조각이 유난히 느려 뒤 조각이 먼저 끝나면 앞 조각 결과는 버린다 (화면이 느린 요청을 기다리지 않음)."""
    lines = [c.text for c in sample_cues if c.type == "dialogue"]
    ends = [1.5 * (i + 1) for i in range(6)]
    texts = dict(zip(ends, lines))
    pipe, shown = run_slow(sample_cues, SlowSTT(texts, lambda end: 0.6 if end == 3.0 else 0.05), workers=3)
    assert pipe.stats["late"] == 1
    assert [r["chunk_end"] for r in pipe.records if r.get("late")] == [3.0]
    assert shown == [texts[e] for e in ends if e != 3.0]                   # 늦게 온 3초 조각은 안 씀


def test_workers_default_and_env(sample_cues, silence, monkeypatch):
    """동시 요청 수: Pipeline 인자 > HELPER_STT_WORKERS > 엔진 기본값 (로컬 whisper 1)."""
    monkeypatch.delenv("HELPER_STT_WORKERS", raising=False)
    assert make_engine("whisper").workers == 1
    assert make_engine("google").workers > 1
    monkeypatch.setenv("HELPER_STT_WORKERS", "2")
    assert make_engine("whisper").workers == 2
    assert Pipeline(sample_cues, silence, FakeSTT([]), print).workers == 1
    assert Pipeline(sample_cues, silence, FakeSTT([]), print, stt_workers=4).workers == 4
