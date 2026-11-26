"""고정 시험 세트 (#50). 저장된 인식 결과 묶음을 한 번에 다시 돌려 최종 보고서에 쓸 표를 만든다 (몇 초, 음성인식 비용 없음).

  python -m eval.suite <세트.json> [--aset key=value] [--set key=value] [--md 표.md]

세트 파일 (경로는 base 기준. base 가 없으면 세트 파일이 있는 폴더 기준):
  {"base": "C:/.../개발",
   "groups": [
     {"name": "이탈 녹음, 기본 설정", "cues": "개발데이터/1차_kuroi/kuroi_cues.csv",
      "runs": [{"results": "results/hint_back_1118/hb2_dev_a_c3h15x2.jsonl",
                "truth": "개발데이터/이탈시험/dev_a_truth.json", "audio": "개발데이터/이탈시험/dev_a.wav"}]},
     {"name": "숫자 대사만", "cues": "개발데이터/숫자대사/numbers_cues.csv", "labels": "개발데이터/숫자대사/numbers_labels.txt",
      "only_cues": [2, 4], "runs": [{"results": "results/numbers_1118/numbers_hints.jsonl"}]}]}

- results: eval/run_eval.py --save 로 저장한 인식 결과 (JSONL). 새로 잰 기록은 runs 에 더하면 된다
- truth: 이탈 정답 JSON (eval/deviation_eval.py 형식). 있으면 이탈 감지를 재고, 그 안의 labels 로 위치 추적도 잰다
- labels: 정답 라벨 (묶음 또는 기록마다). truth 가 없으면 이탈이 없는 녹음으로 보고 알림은 모두 잘못된 알림으로 센다
- audio: 녹음 파일. 소리 크기(loud)가 없는 예전 기록이면 이 파일에서 조각마다 다시 잰다 (추적기 dropout_guard 가 씀)
- only_cues: 이 큐들을 말하는 동안만 위치 추적을 센다 (예: 숫자가 든 대사만)

표의 열
- ±1큐 / 같은 큐: 0.5초마다 화면 큐가 정답 큐 ±1 안 / 정확히 같은 비율 (묶음 안 기록을 합친 값)
- 도달: 대사 시작 → 화면 표시 (중앙, p90). 못 나옴: 끝까지 그 큐(나 뒤 큐)에 못 감
- 안 보임: 화면에 한 번도 안 보인 큐 (뒤 큐로 건너뛰어 지나감. 짧은 대사를 놓치면 여기에 잡힘)
- 화면 안 보임: 보조 화면 송출 칸에 한 번도 안 보인 대사. 곧 나올 짧은 줄과 지나간 줄로 보인 줄은 본 것으로 셈
- 잘못 띄움: 지나간 줄로 보였는데 그 무렵(15초 안) 말하지 않은 줄
- 불확실 표시: 화면이 '불확실'을 띄운 시간 비율 (괄호 안은 그때 / 아닐 때 ±1큐). 표시가 틀린 화면을 가려내는지 본다
- 이탈 찾음, 유형 맞음, 복귀 큐 맞음, 감지 중앙: eval/deviation_eval.py 와 같은 기준 (복귀 뒤 10초까지 온 알림)
- 잘못된 알림: 정답 이탈에 안 걸린 알림 (괄호 안은 10분당)
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

from engine.cue_loader import load_cues
from eval.deviation_eval import parse_kv, score
from eval.deviation_eval import replay as replay_alerts
from eval.metrics import evaluate, read_labels, read_records
from eval.run_eval import replay as replay_timeline

COLUMNS = ("묶음", "기록", "길이", "±1큐", "같은 큐", "도달 중앙", "도달 p90", "못 나옴", "안 보임", "화면 안 보임",
           "잘못 띄움", "불확실 표시", "이탈 찾음", "유형 맞음", "복귀 큐 맞음", "감지 중앙", "잘못된 알림")


def fill_loud(records: list[dict], audio: Path | None, cache: dict) -> list[dict]:
    """소리 크기(loud)가 없는 예전 기록이면 녹음 파일에서 조각마다 다시 잰다."""
    if audio is None or all("loud" in r for r in records):
        return records
    from engine.audio_input import SR, load_wav
    from engine.pipeline import is_loud
    if audio not in cache:
        cache[audio] = load_wav(audio)
    x = cache[audio]
    return [r if "loud" in r else {**r, "loud": is_loud(x[int(r["chunk_start"] * SR):int(r["chunk_end"] * SR)])}
            for r in records]


def run_group(group: dict, base: Path, aligner_kw: dict, detector_kw: dict, cache: dict) -> dict:
    """묶음 하나를 다시 돌려 표 한 줄에 들어갈 값을 모은다."""
    cues = load_cues(base / group["cues"])
    only = set(group["only_cues"]) if group.get("only_cues") else None
    hit = same = samples = missed = unseen = screen = wrong = false = 0
    flagged = [0, 0, 0, 0]          # 불확실 [맞음, 표본], 아닐 때 [맞음, 표본]
    reach, rows, minutes, tracked = [], [], 0.0, False
    for run in group["runs"]:
        records = fill_loud(read_records(base / run["results"]), base / run["audio"] if run.get("audio") else None, cache)
        truth = json.load(open(base / run["truth"], encoding="utf-8")) if run.get("truth") else {}
        if truth.get("labels"):
            labels_path = (base / run["truth"]).parent / truth["labels"]
        elif run.get("labels") or group.get("labels"):
            labels_path = base / (run.get("labels") or group["labels"])
        else:
            labels_path = None
        labels = read_labels(labels_path) if labels_path else None
        end = max(r["chunk_end"] for r in records)
        minutes += (truth.get("duration_sec") or end) / 60
        if labels:
            passed: list = []
            conf: list = []
            rep = evaluate(replay_timeline(cues, records, aligner_kw, passed, conf), labels, cues, end, only=only,
                           passed=passed, conf=conf)
            n_unsure = round(rep.unsure * rep.samples)
            flagged[0] += round((rep.unsure_acc or 0.0) * n_unsure)
            flagged[1] += n_unsure
            flagged[2] += round((rep.sure_acc or 0.0) * (rep.samples - n_unsure))
            flagged[3] += rep.samples - n_unsure
            hit += round(rep.accuracy * rep.samples)
            same += round(rep.exact * rep.samples)
            samples += rep.samples
            reach += rep.reach.values()
            missed += rep.missed
            unseen += rep.unseen
            screen += rep.screen_unseen
            wrong += rep.wrong_passed
            tracked = True
        alerts, _ = replay_alerts(cues, records, aligner_kw, detector_kw)
        res = score(alerts, truth.get("deviations", []), cues, 10.0, labels)
        rows += res["rows"]
        false += len(res["false"])
    found = [r for r in rows if r["found"]]
    delays = sorted(reach)
    return {
        "name": group["name"], "runs": len(group["runs"]), "minutes": minutes,
        "accuracy": hit / samples if tracked and samples else None,
        "exact": same / samples if tracked and samples else None,
        "reach_median": delays[min(len(delays) - 1, len(delays) // 2)] if delays else None,   # eval.metrics 와 같은 방식
        "reach_p90": delays[min(len(delays) - 1, int(0.9 * len(delays)))] if delays else None,
        "missed": missed if tracked else None, "unseen": unseen if tracked else None,
        "screen_unseen": screen if tracked else None, "wrong_passed": wrong if tracked else None,
        "unsure": flagged[1] / samples if tracked and samples else None,
        "unsure_acc": flagged[0] / flagged[1] if flagged[1] else None,
        "sure_acc": flagged[2] / flagged[3] if flagged[3] else None,
        "deviations": len(rows), "found": len(found),
        "type_ok": sum(r["type_ok"] for r in found), "ret_ok": sum(r["ret_ok"] for r in found),
        "detect_median": statistics.median(r["delay"] for r in found) if found else None,
        "false": false,
    }


def row_text(g: dict) -> list[str]:
    pct = lambda v: "-" if v is None else f"{v:.1%}"  # noqa: E731
    sec = lambda v: "-" if v is None else f"{v:.1f}초"  # noqa: E731
    dev = g["deviations"]
    return [g["name"], str(g["runs"]), f"{g['minutes']:.1f}분", pct(g["accuracy"]), pct(g["exact"]),
            sec(g["reach_median"]), sec(g["reach_p90"]), "-" if g["missed"] is None else str(g["missed"]),
            *("-" if g[k] is None else str(g[k]) for k in ("unseen", "screen_unseen", "wrong_passed")),
            "-" if g["unsure"] is None else f"{g['unsure']:.0%} ({pct(g['unsure_acc'])} / {pct(g['sure_acc'])})",
            f"{g['found']}/{dev}" if dev else "-", f"{g['type_ok']}/{g['found']}" if dev else "-",
            f"{g['ret_ok']}/{g['found']}" if dev else "-", sec(g["detect_median"]) if dev else "-",
            f"{g['false']}건 ({10 * g['false'] / g['minutes']:.1f})" if g["minutes"] else str(g["false"])]


def markdown(groups: list[dict]) -> str:
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(row_text(g)) + " |" for g in groups]
    return "\n".join(lines) + "\n"


def run(set_path, aligner_kw: dict | None = None, detector_kw: dict | None = None) -> list[dict]:
    set_path = Path(set_path)
    spec = json.load(open(set_path, encoding="utf-8"))
    base = Path(spec["base"]) if spec.get("base") else set_path.parent
    cache: dict = {}
    return [run_group(g, base, aligner_kw or {}, detector_kw or {}, cache) for g in spec["groups"]]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="고정 시험 세트를 한 번에 다시 돌려 표를 만든다 (#50)")
    p.add_argument("set", help="세트 파일 (JSON)")
    p.add_argument("--aset", action="append", default=[], help="추적기 설정 key=value")
    p.add_argument("--set", dest="dset", action="append", default=[], help="감지기 설정 key=value")
    p.add_argument("--md", help="표를 이 Markdown 파일로도 저장")
    args = p.parse_args(argv)
    table = markdown(run(args.set, parse_kv(args.aset), parse_kv(args.dset)))
    print(table)
    if args.md:
        Path(args.md).write_text(table, encoding="utf-8")


if __name__ == "__main__":
    main()
