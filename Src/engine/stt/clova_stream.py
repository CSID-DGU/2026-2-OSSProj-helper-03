"""CLOVA Speech 실시간 스트리밍 (gRPC). 1차 실험에서 대사를 가장 잘 잡음 (노래는 약함).

키: 콘솔 → CLOVA Speech → Domain → 스트리밍 인식 도메인 → 빌더 실행 → 설정 → 연동 정보 Secret Key
문서: https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-grpc
"""
import json

from ..config import env
from .base import MissingConfig, STTEngine

HOST = "clovaspeech-gw.ncloud.com:50051"


class ClovaStreamEngine(STTEngine):
    key = "clova_stream"
    label = "clova-stream"
    mode = "stream"

    def __init__(self):
        self.secret = env("CLOVA_STREAM_SECRET")

    def check(self):
        if not self.secret:
            raise MissingConfig("CLOVA_STREAM_SECRET 가 .env 에 없음")

    def setup(self):
        import grpc

        from .clova_nest import nest_pb2, nest_pb2_grpc
        self.pb = nest_pb2
        self.stub = nest_pb2_grpc.NestServiceStub(grpc.secure_channel(HOST, grpc.ssl_channel_credentials()))

    def stream(self, frames, hints_fn=None):
        pb = self.pb
        # 말이 0.5초 끊기거나 5초가 차면 결과를 끊어서 보내도록
        config = {"transcription": {"language": "ko"},
                  "semanticEpd": {"skipEmptyText": True, "useWordEpd": False, "usePeriodEpd": True,
                                  "gapThreshold": 500, "durationThreshold": 5000}}

        def reqs():
            yield pb.NestRequest(type=pb.RequestType.CONFIG, config=pb.NestConfig(config=json.dumps(config)))
            for i, f in enumerate(frames):
                yield pb.NestRequest(type=pb.RequestType.DATA, data=pb.NestData(
                    chunk=f, extra_contents=json.dumps({"seqId": i, "epFlag": False})))

        for resp in self.stub.recognize(reqs(), metadata=(("authorization", f"Bearer {self.secret}"),)):
            data = json.loads(resp.contents)
            tr = data.get("transcription")
            if not tr:
                if data.get("config", {}).get("status") not in (None, "Success"):
                    raise RuntimeError(f"CLOVA 설정 실패: {resp.contents[:300]}")
                continue
            text = (tr.get("text") or "").strip()
            if text:
                e = tr.get("endTimestamp")
                yield {"text": text, "final": True, "audio_end": e / 1000 if e is not None else None}
