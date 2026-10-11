"""faster-whisper (로컬, 인터넷 · 키 없음)."""
from ..config import env, env_int
from .base import STTEngine


class WhisperEngine(STTEngine):
    key = "whisper"
    mode = "chunk"

    def __init__(self):
        self.model_name = env("WHISPER_MODEL", "small")
        self.threads = env_int("WHISPER_THREADS", 4)   # 송출 노트북 CPU를 다 쓰지 않게 제한
        self.vad = env("WHISPER_VAD", "1") != "0"
        self.label = f"whisper-{self.model_name}"
        self.model = None

    def setup(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(self.model_name, device="cpu", compute_type="int8", cpu_threads=self.threads)

    def transcribe(self, audio, hints=None):
        # temperature=0: 재시도로 처리 시간이 튀지 않게 / max_new_tokens: 반복 환각이 길어지지 않게
        # initial_prompt: 대본 힌트 (hotwords 는 3초 조각에서 같은 효과라 쓰지 않음)
        segs, _ = self.model.transcribe(
            audio, language="ko", beam_size=1, temperature=0.0, vad_filter=self.vad,
            condition_on_previous_text=False, without_timestamps=True, max_new_tokens=40,
            initial_prompt=" ".join(hints) if hints else None)
        return " ".join(s.text.strip() for s in segs).strip()
