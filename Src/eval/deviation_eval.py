"""이탈 감지 성능 측정. 저장된 인식 결과를 위치 추적기 + 이탈 감지기에 다시 넣어 본다 (몇 초).

  python -m eval.deviation_eval --cues <큐.csv> --run <결과.jsonl> [<정답.json>] [--run ...]

- 결과 JSONL: eval/run_eval.py --save 형식 ({"chunk_start", "chunk_end", "text", "proc_sec"})
- 정답 JSON:  {"duration_sec", "labels", "deviations": [{"type", "start_sec", "end_sec", "return_cue_id"}, ...]}
  start_sec = 이탈 시작 (애드리브 시작 · 건너뛴/반복한 지점), end_sec = 배우가 대본으로 돌아온 시각
  정답을 안 주면 이탈이 없는 녹음으로 본다 (알림은 모두 잘못된 알림)
- 시계: 조각 끝 + 인식에 걸린 시간 (실제로 화면에 알림이 가는 시각과 같게)

지표
- 찾음: 알림(시작 또는 복귀)이 [start_sec, end_sec + tol] 안에 처음 나옴. 유형 맞음 = 마지막 알림의 유형
- 감지 지연: 이탈 시작 → 첫 알림
- 복귀 표시 시간: 배우가 대본으로 돌아온 시각 → 복귀 알림
  복귀 큐 맞음: 알림의 복귀 큐가 정답 복귀 큐 ±1, 또는 알림 시각에 배우가 하던 큐(정답 JSON 의 labels) ±1
- 잘못된 알림 / 10분: 정답 구간에 안 걸린 알림 (시작 · 복귀가 같은 since 면 한 건)

설정 비교:  --set deviate_after_sec=3 (감지기)  --aset heard_score=50 (추적기)  --baseline (1차 감지기)
"""
import argparse
import json
import statistics
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from engine.aligner import Aligner  # noqa: E402
from engine.cue_loader import load_cues  # noqa: E402
from engine.deviation import BASELINE, DeviationDetector  # noqa: E402
from engine.pipeline import implausible  # noqa: E402
from eval.metrics import read_labels, read_records  # noqa: E402


def parse_kv(items: list[str]) -> dict:
    out = {}
    for kv in items:
        k, v = kv.split("=", 1)
        out[k] = v if not v.replace(".", "", 1).lstrip("-").isdigit() else (float(v) if "." in v else int(v))
    return out


def replay(cues, records, aligner_kw=None, detector_kw=None, song_hold=True):
    """파이프라인 _handle 과 같은 순서로 넣고 알림 [(시각초, Alert)] 과 상태 변화 [(시각초, 상태)] 를 돌려준다."""
    al = Aligner(cues, **(aligner_kw or {}))
    det = DeviationDetector(**(detector_kw or {}))
    alerts, states, prev_raw = [], [], ""
    for r in sorted(records, key=lambda r: r["chunk_end"]):
        raw = r.get("text") or ""
        text = "" if implausible(raw, prev_raw, r["chunk_end"] - r["chunk_start"]) else raw
        prev_raw = raw
        now = r["chunk_end"] + r.get("proc_sec", 0.0)
        step = al.update(text, r["chunk_end"])
        hold = song_hold and al.current.type == "lyric"
        alert = det.update(step, al.pos, int(now * 1000), hold=hold)
        if alert:
            alerts.append((now, alert))
        if not states or states[-1][1] != det.state:
            states.append((now, det.state))
    return alerts, states


def events_of(alerts) -> list[dict]:
    """since 가 같은 시작 · 복귀 알림을 한 건으로 묶는다."""
    ev: dict[int, dict] = {}
    for t, a in alerts:
        e = ev.setdefault(a.since, {"t0": t, "t_ret": None, "type": a.deviation_type, "ret": None})
        e["type"] = a.deviation_type
        if a.return_cue_id is not None and e["t_ret"] is None:
            e["t_ret"], e["ret"] = t, a.return_cue_id
    return sorted(ev.values(), key=lambda e: e["t0"])


def score(alerts, truth: list[dict], cues, tol: float = 10.0, labels=None) -> dict:
    order = {c.id: i for i, c in enumerate(c for c in cues if c.type in ("dialogue", "lyric"))}
    lab_t = [t for t, _ in labels or []]

    def near(a, b):
        return a in order and b in order and abs(order[a] - order[b]) <= 1

    def acting(t):   # 알림 시각에 배우가 하던 큐
        k = bisect_right(lab_t, t) - 1
        return labels[k][1] if k >= 0 else None

    events, used, rows = events_of(alerts), set(), []
    for d in truth:
        hit = next((k for k, e in enumerate(events)
                    if k not in used and d["start_sec"] <= e["t0"] <= d["end_sec"] + tol), None)
        row = {"truth": d, "found": hit is not None}
        if hit is not None:
            used.add(hit)
            e = events[hit]
            row.update(delay=e["t0"] - d["start_sec"], type_ok=e["type"] == d["type"], got_type=e["type"],
                       ret=e["ret"], ret_time=None if e["t_ret"] is None else e["t_ret"] - d["end_sec"],
                       ret_ok=e["ret"] is not None and (near(e["ret"], d["return_cue_id"])
                                                        or near(e["ret"], acting(e["t_ret"]))))
        rows.append(row)
    false = [e for k, e in enumerate(events) if k not in used]
    return {"rows": rows, "false": false}


def show_run(name, res, duration):
    print(f"== {name} ({duration:.0f}초)")
    for r in res["rows"]:
        d = r["truth"]
        head = f"  {d.get('id', ''):3} {d['type']:6} {d['start_sec']:6.1f}~{d['end_sec']:6.1f}s 복귀 #{d['return_cue_id']:<3}"
        if not r["found"]:
            print(head + " → 못 찾음")
            continue
        rt = "-" if r["ret_time"] is None else f"{r['ret_time']:+.1f}s"
        print(head + f" → 알림 +{r['delay']:.1f}s {r['got_type']:6}{'' if r['type_ok'] else '(X)'}"
                     f" 복귀 #{r['ret']} {'' if r['ret_ok'] else '(X)'} 복귀 표시 {rt}")
    for e in res["false"]:
        print(f"  잘못된 알림 {e['t0']:6.1f}s {e['type']} 복귀 #{e['ret']}")


def summary(results, label=""):
    rows = [r for res, _ in results for r in res["rows"]]
    minutes = sum(dur for _, dur in results) / 60
    n_false = sum(len(res["false"]) for res, _ in results)
    by = {}
    for r in rows:
        k = r["truth"]["type"]
        f, n = by.get(k, (0, 0))
        by[k] = (f + r["found"], n + 1)
    found = [r for r in rows if r["found"]]
    delays = [r["delay"] for r in found]
    rets = [r["ret_time"] for r in found if r["ret_time"] is not None]
    med = lambda xs: f"{statistics.median(xs):.1f}s" if xs else "-"  # noqa: E731
    parts = [f"{k} {f}/{n}" for k, (f, n) in sorted(by.items())]
    worst = f" (최대 {max(rets):.1f}s)" if rets else ""
    if rows:
        print(f"{label}찾음 {len(found)}/{len(rows)} ({', '.join(parts)})  유형 맞음 {sum(r['type_ok'] for r in found)}"
              f"  복귀 큐 맞음 {sum(r['ret_ok'] for r in found)}  감지 지연 중앙 {med(delays)}"
              f"  복귀 표시 중앙 {med(rets)}{worst}")
    print(f"{label}잘못된 알림 {n_false}건 / {minutes:.1f}분 = {10 * n_false / minutes:.1f}건/10분")


def main(argv=None):
    p = argparse.ArgumentParser(description="이탈 감지 성능 측정")
    p.add_argument("--cues", required=True)
    p.add_argument("--run", nargs="+", action="append", required=True, metavar="결과.jsonl [정답.json]")
    p.add_argument("--set", action="append", default=[], help="감지기 설정 key=value")
    p.add_argument("--aset", action="append", default=[], help="추적기 설정 key=value")
    p.add_argument("--baseline", action="store_true", help="1차 감지기 설정으로")
    p.add_argument("--tol", type=float, default=10.0, help="복귀 뒤 이만큼까지 온 알림도 찾은 것으로 (초)")
    p.add_argument("-v", "--verbose", action="store_true", help="상태 변화도 출력")
    args = p.parse_args(argv)
    cues = load_cues(args.cues)
    dkw = {**(BASELINE if args.baseline else {}), **parse_kv(args.set)}
    akw = parse_kv(args.aset)
    results = []
    for run in args.run:
        records = read_records(run[0])
        truth = json.load(open(run[1], encoding="utf-8")) if len(run) > 1 else {}
        labels = read_labels(Path(run[1]).parent / truth["labels"]) if truth.get("labels") else None
        duration = truth.get("duration_sec") or max(r["chunk_end"] for r in records)
        alerts, states = replay(cues, records, akw, dkw)
        res = score(alerts, truth.get("deviations", []), cues, args.tol, labels)
        show_run(Path(run[0]).stem, res, duration)
        if args.verbose:
            print("  상태: " + "  ".join(f"{t:.1f}s {s}" for t, s in states))
        results.append((res, duration))
    summary(results)


if __name__ == "__main__":
    main()
