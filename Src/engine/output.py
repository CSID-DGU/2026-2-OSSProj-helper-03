"""⑧ 송출 연동 (#46). 오퍼레이터가 누른 송출을 오롯플래닛 관객 화면 신호로 바꿔 내보낸다.

오롯플래닛 신호 (11/24 받은 양식). 회차마다 채널 하나로 4가지를 보내고, 데이터는 subtitle_idx, rendered_text 두 칸
- index        : N번째 줄 표시. subtitle_idx = 자막 파일의 idx = 우리 큐 번호   ← 큐 송출 (cue.send, 한 번에 한 줄)
- emergence    : 긴급 문구 표시. rendered_text 에 글자                        ← 애드리브 임시 자막 (subtitle.send)
- advertisement: 광고 표시. rendered_text 에 이미지 주소                       ← 아직 화면에 버튼 없음
- blackout     : 화면 끄기(암전)                                              ← 유형이 암전인 큐를 송출할 때
관객 화면은 미리 받은 자막 파일에서 그 번호 줄을 찾아 관객이 고른 언어로 띄우므로, 언어와 상관없이 번호만 보낸다.

채널 (HELPER_OUTPUT)
- log (기본): 서버 로그와 회차 기록에만 남긴다. 전달 방식(채널 종류, 인증)이 정해지기 전까지 쓰는 가짜 채널
- off       : 신호를 만들지 않는다
실제 채널은 전달 방식이 정해지면 send(signal) 이 있는 클래스를 하나 더 만들어 CHANNELS 에 넣는다.

양식에 맞춰 정한 것 (#46)
- 관객 화면은 index 하나에 한 줄만 띄워서 송출 버튼 한 번에 한 줄만 보낸다. 짧은 대사는 화면이 '곧 나올 짧은 줄'로
  미리 보여 주고 오퍼레이터가 줄마다 누른다. 지나간 줄은 이미 말한 줄이라 보내지 않는다
- 암전 줄은 blackout(화면 끄기), 대본에 없는 애드리브 자막은 emergence(긴급 문구)
"""
import json
import logging
from dataclasses import dataclass

from .config import env

log = logging.getLogger("helper.output")

SIGNALS = ("index", "emergence", "advertisement", "blackout")


@dataclass(frozen=True)
class Signal:
    kind: str                       # SIGNALS 중 하나
    subtitle_idx: int | None = None
    rendered_text: str | None = None

    def data(self) -> dict:
        """오롯플래닛 신호 데이터 두 칸."""
        return {"subtitle_idx": self.subtitle_idx, "rendered_text": self.rendered_text}


def cue_signal(cue_id: int, cue_type: str | None = None) -> Signal:
    """큐 송출 → 신호. 암전 줄은 화면 끄기, 나머지(대사, 가사, 음향, 안내)는 그 줄 번호 표시."""
    if cue_type == "blackout":
        return Signal("blackout")
    return Signal("index", subtitle_idx=cue_id)


def text_signal(text: str) -> Signal:
    """애드리브 임시 자막 → 긴급 문구 표시."""
    return Signal("emergence", rendered_text=text)


class LogChannel:
    """가짜 채널. 보낸 신호를 서버 로그에 남기고 sent 에 모은다 (테스트에서 확인)."""
    name = "log"

    def __init__(self):
        self.sent: list[Signal] = []

    def send(self, signal: Signal):
        self.sent.append(signal)
        log.info("송출 신호 %s %s", signal.kind, json.dumps(signal.data(), ensure_ascii=False))


class OffChannel:
    name = "off"

    def send(self, signal: Signal):
        pass


CHANNELS = {"log": LogChannel, "off": OffChannel}


def make_channel(name: str | None = None):
    """HELPER_OUTPUT 으로 고른 채널. 모르는 이름이면 ValueError."""
    name = (name or env("HELPER_OUTPUT", "log") or "log").strip()
    if name not in CHANNELS:
        raise ValueError(f"모르는 송출 채널 HELPER_OUTPUT={name} (가능: {', '.join(CHANNELS)})")
    return CHANNELS[name]()
