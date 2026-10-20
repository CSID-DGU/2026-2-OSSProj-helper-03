"""⑦ 회차 기록: 한 회차 동안 인식 글자 · 추적 위치 · 이탈 알림을 JSONL 로 남긴다 (한 줄 = 한 사건).

공연이 끝난 뒤 어디서 놓쳤는지 되짚거나, 실제 마이크 회차를 측정 도구로 다시 돌려 보는 데 쓴다
(eval/run_eval.py --results 에 그대로 넣을 수 있음: "stt" 줄이 저장된 인식 결과 형식과 같다).

줄 종류 (kind)
- start : 회차 정보 (큐 파일 · 소리 원천 · 음성인식 · 설정)
- stt   : 인식 요청 하나 (chunk_start · chunk_end · text · proc_sec · hints, late · error)
- step  : 추적기 판단 (status · cue · cand · score · text)
- alert : 이탈 알림 (deviation_type · since · return_cue_id)
- settings : 화면에서 바꾼 설정 / error : 스트리밍 끊김
- end   : 회차 끝 (요청 수 · 건너뜀 · 늦어서 버림 · 실패)
모든 줄에 wall (기록 시각, epoch ms). 대본 · 인식 글자가 들어 있으므로 저장소에 올리지 않는다 (logs/ 는 .gitignore)
"""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path


class SessionLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()   # 인식 스레드 · 서버 스레드에서 같이 부름

    @classmethod
    def open_in(cls, folder: Path, show_id: str = "") -> "SessionLog":
        """folder/날짜_시각_공연ID.jsonl 로 새 기록을 연다."""
        name = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = re.sub(r"[^\w-]+", "_", show_id).strip("_")
        return cls(Path(folder) / (f"{name}_{tag}.jsonl" if tag else f"{name}.jsonl"))

    def __call__(self, kind: str, **fields):
        line = json.dumps({"kind": kind, "wall": int(time.time() * 1000), **fields}, ensure_ascii=False)
        with self._lock:
            if not self._f.closed:
                self._f.write(line + "\n")
                self._f.flush()     # 서버가 갑자기 꺼져도 그때까지는 남게

    def close(self):
        with self._lock:
            self._f.close()
