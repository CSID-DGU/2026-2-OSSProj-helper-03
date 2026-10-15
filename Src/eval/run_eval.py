"""위치 추적 성능 측정. 공연 데이터 · 라벨은 저장소 밖 경로로 준다.

1) 저장된 인식 결과 다시 돌리기 (소리 · API 없이, 몇 초):
   python -m eval.run_eval --cues <큐.csv> --labels <라벨.txt> --results <결과.jsonl> [...]
   결과 JSONL 한 줄: {"chunk_start", "chunk_end", "text", "proc_sec"} (개발 폴더 run_stt.py 형식)

2) 실제 음성인식으로 처음부터 (대본 힌트가 추적 위치를 따라 바뀌므로 이쪽이 실제와 같음):
   python -m eval.run_eval --cues <큐.csv> --labels <라벨.txt> --audio <녹음.wav> --engine whisper
   인식 글자는 --save 로 남겨 두면 다음부터 1) 로 빨리 비교할 수 있다

3) 실시간 (--realtime): 실제 Pipeline 을 녹음 길이만큼 실제 시간으로 돌려 화면에 보인 그대로 잰다
   (인식 처리 시간 · 동시 요청 · 밀려서 건너뛴 조각이 모두 반영됨). --workers 로 동시 요청 수
   python -m eval.run_eval --cues ... --labels ... --audio <녹음.wav> --engine google --hop 1.5 --realtime --workers 2
   --save 를 주면 요청별 기록(JSONL)과 요약(.summary.json: 설정 · 지표 · 화면 타임라인)을 남긴다

추적기 설정 비교:  --set accept=70 --set ahead=10  (여러 번 가능),  --baseline 은 개선 전 설정
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from engine.aligner import BASELINE, Aligner  # noqa: E402
from engine.cue_loader import load_cues  # noqa: E402
from engine.pipeline import implausible  # noqa: E402
from eval.metrics import evaluate, read_labels  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="위치 추적 성능 측정")
    p.add_argument("--cues", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--results", nargs="*", default=[], help="저장된 인식 결과 JSONL")
    p.add_argument("--audio", help="녹음 파일 (실제 음성인식으로 측정)")
    p.add_argument("--engine", default="whisper")
    p.add_argument("--no-hints", action="store_true")
    p.add_argument("--chunk", type=float, default=3.0)
    p.add_argument("--hop", type=float, default=0.0, help="조각 간격 (0 = 조각 길이와 같음)")
    p.add_argument("--save", help="실제 음성인식 결과를 JSONL 로 저장할 경로")
    p.add_argument("--set", action="append", default=[], help="추적기 설정 덮어쓰기 key=value")
    p.add_argument("--baseline", action="store_true", help="개선 전 추적기 설정으로")
    p.add_argument("--realtime", action="store_true", help="실제 Pipeline 을 실시간으로 돌려 측정")
    p.add_argument("--workers", type=int, default=0, help="동시 인식 요청 수 (0 = HELPER_STT_WORKERS · 엔진 기본값)")
    p.add_argument("--speed", type=float, default=1.0, help="--realtime 재생 속도 (1 = 실제 시간)")
    return p.parse_args(argv)


def aligner_kwargs(args) -> dict:
    kw = dict(BASELINE) if args.baseline else {}
    for kv in args.set:
        k, v = kv.split("=", 1)
        kw[k] = type(BASELINE.get(k, 0.0))(v) if k in BASELINE else float(v)
    return kw


def replay(cues, records, kw) -> list[tuple[float, int]]:
    """인식 글자를 시간 순서대로 추적기에 넣어 타임라인을 만든다 (파이프라인과 같은 걸러내기)."""
    al = Aligner(cues, **kw)
    timeline, prev_raw = [], ""
    for r in sorted(records, key=lambda r: r["chunk_end"]):
        if r.get("late"):     # 실시간 기록에서 늦어서 버린 결과
            continue
        raw = r.get("text") or ""
        text = "" if implausible(raw, prev_raw, r["chunk_end"] - r["chunk_start"]) else raw
        prev_raw = raw
        before = al.current.id
        al.update(text)
        if al.current.id != before:
            timeline.append((r["chunk_end"] + r.get("proc_sec", 0.0), al.current.id))
    return timeline


def live(cues, audio_path, args, kw) -> tuple[list[tuple[float, int]], list[dict]]:
    """실제 음성인식 (실시간 속도로 기다리지 않고 바로바로). 대본 힌트는 추적 위치에서 만든다."""
    from engine.audio_input import SR, load_wav
    from engine.stt import make_engine

    stt = make_engine(args.engine)
    stt.check()
    stt.setup()
    audio = load_wav(audio_path)
    al = Aligner(cues, **kw)
    timeline, records, prev_raw = [], [], ""
    hop = args.hop or args.chunk
    end = min(hop, args.chunk)
    while end <= len(audio) / SR + 1e-6:
        seg = audio[int(max(0.0, end - args.chunk) * SR):int(end * SR)]
        hints = None if args.no_hints else ([c.text for c in al.hint_cues()] or None)
        t0 = time.perf_counter()
        try:
            raw = stt.transcribe(seg, hints)
        except Exception as ex:
            print(f"  인식 실패 {end:.0f}s: {ex}")
            raw = ""
        proc = time.perf_counter() - t0
        records.append({"chunk_start": max(0.0, end - args.chunk), "chunk_end": end, "text": raw,
                        "proc_sec": round(proc, 3)})
        text = "" if implausible(raw, prev_raw, min(args.chunk, end)) else raw
        prev_raw = raw
        before = al.current.id
        al.update(text)
        if al.current.id != before:
            timeline.append((end + proc, al.current.id))
        end += hop
    return timeline, records


def realtime(cues, audio_path, args, kw) -> tuple[list[tuple[float, int]], list[dict], dict]:
    """실제 Pipeline 을 실시간으로 돌린다. 화면 타임라인 = position.update 를 보낸 순간의 재생 시계."""
    from engine.audio_input import load_wav
    from engine.pipeline import Pipeline
    from engine.stt import make_engine

    stt = make_engine(args.engine)
    stt.check()
    stt.setup()
    timeline, shown_ms = [], []
    pipe = None

    def emit(msg):
        if msg["type"] != "position.update" or pipe is None:
            return
        shown_ms.append(msg["latency_ms"])
        if not timeline or timeline[-1][1] != msg["cue_id"]:
            timeline.append((round(pipe.source.now_audio(), 3), msg["cue_id"]))

    pipe = Pipeline(cues, load_wav(audio_path), stt, emit, hints=not args.no_hints, chunk_sec=args.chunk,
                    hop_sec=args.hop or None, speed=args.speed, stt_workers=args.workers or None)
    if kw:
        pipe.aligner = Aligner(cues, **kw)
    print(f"  실시간: {stt.label}, 조각 {args.chunk:g}s/{pipe.hop_sec:g}s, 동시 요청 {pipe.workers}, "
          f"약 {pipe.source.duration / args.speed:.0f}초 걸림")
    pipe.start()
    work = [th for th in pipe.threads if "heartbeat" not in th.name]   # 재생 · 인식 스레드가 끝날 때까지
    while any(th.is_alive() for th in work):
        next(th for th in work if th.is_alive()).join(30)
        print(f"  ... {pipe.source.now_audio():.0f}s, 화면 큐 {timeline[-1][1] if timeline else '-'}")
    pipe.stop()
    pipe.join(timeout=3)
    records = sorted(getattr(pipe, "records", []), key=lambda r: r["chunk_end"])
    stats = dict(getattr(pipe, "stats", {}), sent=len(records), workers=pipe.workers,
                 failed=sum("error" in r for r in records), shown_ms=shown_ms)
    return timeline, records, stats


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def show_realtime(stats, records, rep) -> dict:
    """요청 처리 시간 · 건너뛴 조각 · 화면 지연을 출력하고 요약으로 돌려준다."""
    proc = [r["proc_sec"] for r in records if "proc_sec" in r]
    shown = stats["shown_ms"]
    sent_sec = sum(r["chunk_end"] - r["chunk_start"] for r in records)
    if proc:
        print(f"  요청 {stats['sent']}번 (동시 {stats['workers']}): 처리 평균 {sum(proc) / len(proc):.2f}s"
              f"  중앙 {pct(proc, .5):.2f}s  p95 {pct(proc, .95):.2f}s  최대 {max(proc):.2f}s"
              f"  보낸 소리 {sent_sec / 60:.1f}분")
    print(f"  밀려서 안 보낸 조각 {stats.get('skipped', 0)}  늦어서 버린 결과 {stats.get('late', 0)}"
          f"  실패 {stats['failed']}")
    if shown:
        print(f"  조각 끝 → 화면 표시 지연 중앙 {pct(shown, .5) / 1000:.2f}s  p90 {pct(shown, .9) / 1000:.2f}s")
    return {"accuracy": rep.accuracy, "dialogue": rep.by_type["dialogue"], "lyric": rep.by_type["lyric"],
            "reach_median": rep.reach_median, "reach_p90": rep.reach_p90, "missed": rep.missed,
            "back": rep.back, "big_jumps": rep.big_jumps,
            "proc_avg": sum(proc) / len(proc) if proc else None, "proc_p50": pct(proc, .5),
            "proc_p95": pct(proc, .95), "proc_max": max(proc) if proc else None,
            "shown_p50_ms": pct(shown, .5), "shown_p90_ms": pct(shown, .9), "sent_audio_sec": sent_sec}


def show(name, rep):
    md = f"{rep.reach_median:.1f}" if rep.reach_median is not None else "-"
    p9 = f"{rep.reach_p90:.1f}" if rep.reach_p90 is not None else "-"
    print(f"{name[:44]:44} ±1큐 {100 * rep.accuracy:5.1f}%  대사 {100 * rep.by_type['dialogue']:5.1f}%"
          f"  가사 {100 * rep.by_type['lyric']:5.1f}%  도달 중앙 {md:>5}s p90 {p9:>5}s  못감 {rep.missed:2}"
          f"  뒤로 {rep.back}  큰점프 {rep.big_jumps}")


def main(argv=None):
    args = parse_args(argv)
    cues = load_cues(args.cues)
    labels = read_labels(args.labels)
    kw = aligner_kwargs(args)
    end_sec = labels[-1][0] + 15
    for path in args.results:
        records = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        end_sec = max(end_sec, max(r["chunk_end"] for r in records))
        show(Path(path).stem, evaluate(replay(cues, records, kw), labels, cues, end_sec))
    if args.audio:
        if args.realtime:
            timeline, records, stats = realtime(cues, args.audio, args, kw)
        else:
            timeline, records = live(cues, args.audio, args, kw)
        end_sec = max(end_sec, records[-1]["chunk_end"] if records else 0)
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tag = f"{args.engine}{'' if args.no_hints else '+힌트'} {args.chunk:g}s/{(args.hop or args.chunk):g}s"
        tag += f" 실시간 동시{stats['workers']}" if args.realtime else ""
        tag += " (개선 전)" if args.baseline else ""
        rep = evaluate(timeline, labels, cues, end_sec)
        show(tag, rep)
        if args.realtime:
            summary = show_realtime(stats, records, rep)
            if args.save:
                info = {"engine": args.engine, "hints": not args.no_hints, "chunk": args.chunk,
                        "hop": args.hop or args.chunk, "workers": stats["workers"], "speed": args.speed,
                        "sent": stats["sent"], "skipped": stats.get("skipped", 0), "late": stats.get("late", 0),
                        "failed": stats["failed"], **summary, "timeline": timeline}
                Path(args.save).with_suffix(".summary.json").write_text(
                    json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
