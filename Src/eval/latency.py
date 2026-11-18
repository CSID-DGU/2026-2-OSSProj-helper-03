"""도달 지연 나눠 보기 (#40). 실시간 측정 기록에서, 배우가 큐를 시작한 뒤 화면에 그 큐가 뜨기까지를 세 부분으로 나눈다.

  python -m eval.latency --cues <큐.csv> --labels <라벨.txt> --run <기록.jsonl> [--run ...]

- 기록: eval/run_eval.py --realtime --save 결과 (<기록>.jsonl 과 같은 이름의 .summary.json 에 화면 타임라인이 있음)
- 조각 대기: 큐 시작 → 화면을 옮긴 인식 결과의 조각이 끝난 때 (조각 간격 · 말하는 데 걸린 시간)
- 인식: 그 조각을 음성인식에 보내고 답이 오기까지 (proc_sec)
- 나머지: 답이 온 뒤 화면 메시지를 보내기까지 (앞 조각 결과를 기다림 · 처리)
화면을 옮긴 결과 = 화면이 그 큐로 바뀐 때보다 먼저 처리가 끝난 결과 중 가장 늦게 끝난 것
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from engine.cue_loader import load_cues  # noqa: E402
from eval.metrics import evaluate, processing_order, read_labels, read_records  # noqa: E402


def breakdown(timeline, records, labels, cues) -> list[dict]:
    """큐마다 {cue, reach, wait, proc, rest}. 화면에 안 뜬 큐는 뺀다."""
    end = max([t for t, _ in labels] + [r["chunk_end"] for r in records]) + 15
    rep = evaluate(timeline, labels, cues, end)
    done = [(r["chunk_end"] + r.get("proc_sec", 0.0), r) for r in processing_order(records) if "error" not in r]
    start = {cid: t for t, cid in labels}
    rows = []
    for cid, reach in rep.reach.items():
        shown_at = start[cid] + reach
        before = [(d, r) for d, r in done if d <= shown_at + 0.05]
        if not before:
            continue
        d, r = max(before, key=lambda x: x[0])
        wait = r["chunk_end"] - start[cid]
        proc = r.get("proc_sec", 0.0)
        rows.append({"cue": cid, "reach": reach, "wait": wait, "proc": proc, "rest": max(0.0, shown_at - d)})
    return rows


def med(xs):
    return statistics.median(xs) if xs else float("nan")


def show(name: str, rows: list[dict], types: dict[int, str]):
    print(f"== {name} (큐 {len(rows)}개)")
    for kind in ("dialogue", "lyric", None):
        sel = [r for r in rows if kind is None or types.get(r["cue"]) == kind]
        if not sel:
            continue
        label = {"dialogue": "대사", "lyric": "가사", None: "전체"}[kind]
        print(f"  {label}: 도달 중앙 {med([r['reach'] for r in sel]):.2f}s = 조각 대기 {med([r['wait'] for r in sel]):.2f}s"
              f" + 인식 {med([r['proc'] for r in sel]):.2f}s + 나머지 {med([r['rest'] for r in sel]):.2f}s (각각 중앙값)")


def main(argv=None):
    p = argparse.ArgumentParser(description="도달 지연 나눠 보기")
    p.add_argument("--cues", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--run", action="append", required=True, help="실시간 측정 기록 JSONL (.summary.json 이 옆에 있어야 함)")
    args = p.parse_args(argv)
    cues = load_cues(args.cues)
    labels = read_labels(args.labels)
    types = {c.id: c.type for c in cues}
    for path in args.run:
        summary = json.loads(Path(path).with_suffix(".summary.json").read_text(encoding="utf-8"))
        timeline = [tuple(x) for x in summary["timeline"]]
        show(Path(path).stem, breakdown(timeline, read_records(path), labels, cues), types)


if __name__ == "__main__":
    main()
