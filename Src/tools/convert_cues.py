"""큐 CSV 를 화면(ui) 형식(id, order, type, speaker, text)으로 바꾼다.

  python tools/convert_cues.py <입력.csv> <출력.csv>

1차 데이터(cue_id, act, scene, type, speaker, text_ko)를 화면 시작 패널에서 불러오려면 필요.
열 이름이 팀에서 하나로 정해지면 없어도 되는 임시 도구.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from engine.cue_loader import load_cues, to_ui_csv  # noqa: E402


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    cues = load_cues(sys.argv[1])
    Path(sys.argv[2]).write_text(to_ui_csv(cues), encoding="utf-8")
    print(f"큐 {len(cues)}개 → {sys.argv[2]}")


if __name__ == "__main__":
    main()
