"""Google Cloud Speech-to-Text V2.

- google        : 3초 조각 동기 인식. chirp_3(location us) + 대본 힌트가 1차 실험에서 가장 정확
- google_stream : 실시간 스트리밍. long(global) 은 중간 결과가 약 1초마다 와서 빠름
                  (chirp_3 스트리밍은 중간 결과가 없어 실시간에 부적합)
인증: 서비스 계정 키 JSON 경로를 GOOGLE_APPLICATION_CREDENTIALS 에 (역할: Cloud Speech 클라이언트)
"""
import json
import os

from ..audio_input import to_pcm16
from ..config import env, env_path
from .base import MissingConfig, STTEngine

# 대본 힌트(구문 세트)를 받는 모델. long 은 ko-KR 에서 400 "does not support speech_adaptation_boost"
HINT_MODELS = ("chirp_3", "short")


class GoogleEngine(STTEngine):
    key = "google"
    mode = "chunk"
    workers = 3    # chirp_3 는 요청당 1~2초(p95 2.2초)라 1.5초 간격이면 동시에 보내야 따라감
                   # (SpeechClient 는 gRPC 채널이라 스레드 사이에 같이 써도 됨)
    default_model, default_location = "chirp_3", "us"

    def __init__(self):
        self.cred = env_path("GOOGLE_APPLICATION_CREDENTIALS")
        self.project = env("GOOGLE_CLOUD_PROJECT")
        self.model = env("GOOGLE_STT_MODEL", self.default_model)
        self.location = env("GOOGLE_STT_LOCATION", self.default_location)
        self.label = f"{self.key}-{self.model}"
        self.client = None

    def check(self):
        if not self.cred or not self.cred.exists():
            raise MissingConfig(f"GOOGLE_APPLICATION_CREDENTIALS 키 파일이 없음: {self.cred}")
        if not self.project:
            self.project = json.loads(self.cred.read_text(encoding="utf-8")).get("project_id", "")
        if not self.project:
            raise MissingConfig("GOOGLE_CLOUD_PROJECT 를 정할 수 없음")

    def setup(self):
        from google.api_core.client_options import ClientOptions
        from google.cloud.speech_v2 import SpeechClient
        from google.cloud.speech_v2.types import cloud_speech

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(self.cred)
        opts = None if self.location == "global" else ClientOptions(
            api_endpoint=f"{self.location}-speech.googleapis.com")
        self.client = SpeechClient(client_options=opts)
        self.cs = cloud_speech
        self.recognizer = f"projects/{self.project}/locations/{self.location}/recognizers/_"

    def _config(self, hints=None):
        cs = self.cs
        cfg = cs.RecognitionConfig(
            explicit_decoding_config=cs.ExplicitDecodingConfig(
                encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000, audio_channel_count=1),
            language_codes=["ko-KR"], model=self.model)
        if hints and self.model in HINT_MODELS:
            phrases = [cs.PhraseSet.Phrase(value=p, boost=10) for p in _short_phrases(hints)]
            cfg.adaptation = cs.SpeechAdaptation(phrase_sets=[
                cs.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=cs.PhraseSet(phrases=phrases))])
        return cfg

    def transcribe(self, audio, hints=None):
        req = self.cs.RecognizeRequest(recognizer=self.recognizer, config=self._config(hints),
                                       content=to_pcm16(audio))
        res = self.client.recognize(request=req, timeout=15)
        return " ".join(r.alternatives[0].transcript.strip() for r in res.results if r.alternatives).strip()


class GoogleStreamEngine(GoogleEngine):
    key = "google_stream"
    mode = "stream"
    default_model, default_location = "long", "global"

    def stream(self, frames, hints_fn=None):
        cs = self.cs
        cfg = cs.StreamingRecognitionConfig(
            config=self._config(hints_fn() if hints_fn else None),
            streaming_features=cs.StreamingRecognitionFeatures(interim_results=True))

        def reqs():
            yield cs.StreamingRecognizeRequest(recognizer=self.recognizer, streaming_config=cfg)
            for f in frames:
                yield cs.StreamingRecognizeRequest(audio=f)

        for resp in self.client.streaming_recognize(requests=reqs()):
            # 한 응답 안에 확정된 앞부분 + 바뀔 수 있는 뒷부분이 따로 오므로 이어 붙인다
            rs = [r for r in resp.results if r.alternatives]
            if not rs:
                continue
            end = rs[-1].result_end_offset.total_seconds() if rs[-1].result_end_offset else None
            yield {"text": " ".join(r.alternatives[0].transcript.strip() for r in rs).strip(),
                   "final": all(r.is_final for r in rs), "audio_end": end}


def _short_phrases(hints: list[str], max_words: int = 3) -> list[str]:
    """긴 대사를 2~3어절씩 잘라 구문 힌트로."""
    out = []
    for h in hints:
        words = h.replace(",", " ").replace(".", " ").split()
        for i in range(0, len(words), max_words):
            p = " ".join(words[i:i + max_words]).strip(" !?…")
            if p and p not in out:
                out.append(p)
    return out[:20]
