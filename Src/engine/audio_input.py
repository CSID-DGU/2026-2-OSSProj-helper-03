"""② 오디오 입력. 두 가지가 같은 모양(frames · run · segment · now_audio · level · pos · done)이다.

- FileSource: 녹음 파일을 실제 시간 속도로 흘려보냄 (HELPER_INPUT=file, 기본)
- MicSource:  마이크 소리를 받아 최근 60초를 고리 버퍼에 둠 (HELPER_INPUT=mic, sounddevice)

마이크 확인:  python -m engine.audio_input --list   /   python -m engine.audio_input --test 3
"""
import argparse
import io
import logging
import queue
import sys
import threading
import time

import numpy as np
import soundfile as sf

SR = 16000
FRAME_SEC = 0.1

log = logging.getLogger("helper.audio")


def load_wav(path) -> np.ndarray:
    """16kHz 모노 float32 로 읽는다."""
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        raise ValueError(f"{path}: {sr}Hz. 16kHz 로 바꿔서 넣어 주세요 (예: ffmpeg -ar 16000 -ac 1)")
    return audio


def to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def to_wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, SR, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def level_of(frame: np.ndarray) -> float:
    """음량 막대용 0~1 (−60 dBFS → 0, 0 dBFS → 1)."""
    if len(frame) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(frame ** 2)))
    if rms < 1e-6:
        return 0.0
    return float(np.clip((20 * np.log10(rms) + 60) / 60, 0.0, 1.0))


class FileSource:
    """녹음 파일을 0.1초씩 실제 시간에 맞춰 내보낸다. speed > 1 이면 빨리 감기 (시험용)."""

    def __init__(self, audio: np.ndarray, speed: float = 1.0):
        self.audio = audio
        self.speed = speed
        self.duration = len(audio) / SR
        self.pos = 0.0          # 지금까지 흘려보낸 소리 길이 (초)
        self.level = 0.0
        self.done = threading.Event()
        self.stopped = threading.Event()
        self._t0 = None

    def now_audio(self) -> float:
        """시작 후 흐른 시간을 소리 시각으로 (빨리 감기 반영)."""
        return 0.0 if self._t0 is None else (time.perf_counter() - self._t0) * self.speed

    def frames(self):
        """PCM16 바이트 조각을 실제 속도로 내보내는 생성기 (스트리밍 엔진용)."""
        step = int(FRAME_SEC * SR)
        self._t0 = time.perf_counter()
        for i in range(0, len(self.audio), step):
            if self.stopped.is_set():
                break
            due = self._t0 + (i / SR) / self.speed
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            frame = self.audio[i:i + step]
            self.level = level_of(frame)
            self.pos = (i + len(frame)) / SR
            yield to_pcm16(frame)
        self.level = 0.0
        self.done.set()

    def run(self):
        """조각 방식 엔진용: 소비자 없이 재생 시계만 돌린다."""
        for _ in self.frames():
            pass

    def segment(self, start: float, end: float) -> np.ndarray:
        return self.audio[int(start * SR):int(end * SR)]

    def stop(self):
        self.stopped.set()


# ── 마이크 ──────────────────────────────────────────────────
def _sd():
    """sounddevice 는 마이크를 쓸 때만 불러온다 (테스트 · 파일 재생에는 필요 없음)."""
    try:
        import sounddevice
    except (ImportError, OSError) as ex:   # OSError: PortAudio 라이브러리가 없음
        raise RuntimeError(f"마이크 입력에는 sounddevice 가 필요합니다 (pip install sounddevice): {ex}") from ex
    return sounddevice


def list_devices() -> list[dict]:
    """입력 장치 목록 (index, name, hostapi, channels, rate, default)."""
    sd = _sd()
    apis = sd.query_hostapis()
    default_in = sd.default.device[0]
    return [{"index": i, "name": d["name"], "hostapi": apis[d["hostapi"]]["name"],
             "channels": d["max_input_channels"], "rate": int(d["default_samplerate"]),
             "default": i == default_in}
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def find_device(spec: str | int | None) -> int | None:
    """HELPER_MIC_DEVICE: 비우면 기본 장치(None), 숫자면 번호, 아니면 이름 일부 (대소문자 무시, 처음 맞는 것)."""
    if spec is None or str(spec).strip() == "":
        return None
    spec = str(spec).strip()
    if spec.isdigit():
        return int(spec)
    for d in list_devices():
        if spec.lower() in d["name"].lower():
            return d["index"]
    raise ValueError(f"마이크 '{spec}' 를 찾을 수 없음 (python -m engine.audio_input --list 로 확인)")


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    """rate → 16kHz 간단 변환 (이동 평균으로 높은 소리를 줄이고 선형 보간). 0.1초 조각 단위로 부른다."""
    if rate == SR or len(x) == 0:
        return x
    k = int(round(rate / SR))
    if k > 1:   # 접힘(aliasing) 줄이기
        x = np.convolve(x, np.ones(k, dtype="float32") / k, mode="same")
    n = int(round(len(x) * SR / rate))
    return np.interp(np.arange(n) * (rate / SR), np.arange(len(x)), x).astype("float32")


class MicSource:
    """마이크 소리를 0.1초씩 받아 최근 buffer_sec 초를 고리 버퍼에 둔다. FileSource 와 같은 모양.

    소리 시각(now_audio · pos · segment)은 시작 후 받은 소리 길이 (초). 끝이 없으므로 duration = inf,
    done 은 stop() 뒤에 켜진다. 16kHz 로 못 열면 장치 기본 주파수로 열고 직접 바꾼다.
    """

    speed = 1.0

    def __init__(self, device: str | int | None = None, buffer_sec: float = 60.0):
        self.device = device
        self.duration = float("inf")
        self.pos = 0.0
        self.level = 0.0
        self.rate = SR             # 실제로 연 주파수
        self.name = ""             # 실제로 연 장치 이름
        self.overflows = 0         # 소리를 놓친 횟수 (처리가 밀림)
        self.done = threading.Event()
        self.stopped = threading.Event()
        self._buf = np.zeros(int(buffer_sec * SR), dtype="float32")
        self._n = 0                # 지금까지 받은 샘플 수
        self._lock = threading.Lock()
        self._q: queue.Queue = queue.Queue()
        self._stream = None

    # ── 고리 버퍼 (sounddevice 없이 테스트할 수 있게 따로) ──
    def _push(self, frame: np.ndarray):
        """16kHz float32 소리를 버퍼 끝에 붙인다."""
        frame = np.asarray(frame, dtype="float32").reshape(-1)
        cap = len(self._buf)
        with self._lock:
            n0 = self._n
            if len(frame) > cap:
                n0, frame = n0 + len(frame) - cap, frame[-cap:]
            i = n0 % cap
            first = min(len(frame), cap - i)
            self._buf[i:i + first] = frame[:first]
            self._buf[:len(frame) - first] = frame[first:]
            self._n = n0 + len(frame)
            self.pos = self._n / SR
        self.level = level_of(frame)

    def segment(self, start: float, end: float) -> np.ndarray:
        """소리 시각 [start, end) 초. 버퍼에서 밀려난 앞부분 · 아직 안 들어온 뒷부분은 빠진다."""
        cap = len(self._buf)
        with self._lock:
            a = max(int(start * SR), self._n - cap, 0)
            b = min(int(end * SR), self._n)
            if b <= a:
                return np.zeros(0, dtype="float32")
            return self._buf[np.arange(a, b) % cap]

    def now_audio(self) -> float:
        """지금까지 받은 소리 길이 (초). 조각 방식은 이 시각까지 소리가 버퍼에 들어온 뒤 인식한다."""
        return self.pos

    # ── 장치 ──
    def open(self):
        """입력 스트림을 만든다 (아직 받지는 않음). 장치 · 주파수 문제를 회차 시작 때 바로 알 수 있게 따로 둠."""
        if self._stream is not None:
            return
        sd = _sd()
        dev = find_device(self.device)
        info = sd.query_devices(dev, "input")

        def callback(indata, frames, t, status):
            if status.input_overflow:
                self.overflows += 1
            self._q.put(indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0].copy())

        last = None
        for rate in dict.fromkeys((SR, int(info["default_samplerate"]))):
            try:
                self._stream = sd.InputStream(device=dev, samplerate=rate, channels=1, dtype="float32",
                                              blocksize=int(rate * FRAME_SEC), callback=callback)
            except Exception as ex:   # 16kHz 를 거절하는 장치 → 기본 주파수로 다시
                last = ex
                continue
            self.rate, self.name = rate, info["name"]
            log.info("마이크 열림: %s (%dHz%s)", self.name, rate, "" if rate == SR else " → 16kHz 로 바꿈")
            return
        raise RuntimeError(f"마이크를 열 수 없음 ({info['name']}): {last}")

    def frames(self):
        """PCM16 0.1초 조각을 받는 대로 내보내는 생성기 (스트리밍 엔진용). stop() 까지 계속."""
        try:
            self.open()
            self._stream.start()
            while not self.stopped.is_set():
                try:
                    block = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                frame = resample(block, self.rate)
                self._push(frame)
                yield to_pcm16(frame)
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as ex:
                    log.warning("마이크 닫기 실패: %s", ex)
            self._stream = None
            self.level = 0.0
            self.done.set()

    def run(self):
        """조각 방식 엔진용: 소비자 없이 버퍼만 채운다."""
        for _ in self.frames():
            pass

    def stop(self):
        self.stopped.set()


def _cli(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="마이크 확인 (소리는 저장하지 않음)")
    p.add_argument("--list", action="store_true", help="입력 장치 목록")
    p.add_argument("--test", type=float, metavar="SEC", help="몇 초 받아서 음량 보기")
    p.add_argument("--device", help="장치 번호 또는 이름 일부 (없으면 HELPER_MIC_DEVICE, 그것도 없으면 기본 장치)")
    args = p.parse_args(argv)
    if args.list or not args.test:
        for d in list_devices():
            mark = "*" if d["default"] else " "
            print(f"{mark} {d['index']:3}  {d['name']}  [{d['hostapi']}, {d['channels']}ch, {d['rate']}Hz]")
        print("* = 기본 장치. HELPER_MIC_DEVICE 에 번호나 이름 일부를 적는다")
    if args.test:
        from .config import env
        mic = MicSource(args.device if args.device is not None else env("HELPER_MIC_DEVICE") or None)
        mic.open()
        print(f"받는 중: {mic.name} ({mic.rate}Hz) {args.test:g}초")
        levels = []
        for _ in mic.frames():
            levels.append(mic.level)
            if len(levels) % 5 == 0:
                print(f"  {mic.pos:4.1f}s  음량 {mic.level:.2f}  {'#' * int(mic.level * 40)}")
            if mic.pos >= args.test:
                mic.stop()
        peak = float(np.abs(mic.segment(0, mic.pos)).max(initial=0.0))
        print(f"평균 음량 {np.mean(levels):.2f}, 최대 {max(levels):.2f}, 최대 진폭 {peak:.3f}, 놓침 {mic.overflows}")


if __name__ == "__main__":
    _cli()
