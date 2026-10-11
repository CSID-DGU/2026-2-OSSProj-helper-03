"""설정. Src/.env 를 읽는다 (키 · 데이터 경로는 저장소에 넣지 않는다)."""
import os
from pathlib import Path

from dotenv import load_dotenv

SRC = Path(__file__).resolve().parents[1]   # Src/
load_dotenv(SRC / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    return int(env(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(env(name, str(default)))


def env_path(name: str) -> Path | None:
    """경로형 설정. 상대 경로는 Src/ 기준."""
    v = env(name)
    if not v:
        return None
    p = Path(v)
    return p if p.is_absolute() else SRC / p
