#!/usr/bin/env python3
"""Measure the model Oread is running on every clip, and compare models.

    python3 tools/bench.py --host <server address>   # run every clip, save results
    python3 tools/bench.py --matrix                  # compare all models measured so far
    python3 tools/bench.py --misses                  # what each model got wrong, by phrase

Routine: run bench, change stt.model in the server's settings.yaml,
restart Oread, run bench again; then --matrix.

Uses cases that carry a `reference` (the exact words spoken): the public
clip in tests/cases.yaml and your recordings in tests/private/cases.yaml.
Results go to tests/private/bench.jsonl (private: they hold your words).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regress import load_audio, normalize  # noqa: E402
from wyoming_client import transcribe  # noqa: E402

from wyoming.client import AsyncTcpClient  # noqa: E402
from wyoming.info import Describe, Info  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "tests" / "private" / "bench.jsonl"
CASE_FILES = [ROOT / "tests" / "cases.yaml", ROOT / "tests" / "private" / "cases.yaml"]


def word_errors(reference: str, heard: str) -> tuple[int, int]:
    """(word edits needed, words in reference): the basis of word error rate."""
    ref, hyp = normalize(reference).split(), normalize(heard).split()
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1], len(ref)


async def model_name(host: str, port: int) -> str:
    async with AsyncTcpClient(host, port) as client:
        await client.write_event(Describe().event())
        while True:
            event = await client.read_event()
            if event is None:
                return "unknown"
            if Info.is_type(event.type):
                info = Info.from_event(event)
                return info.asr[0].models[0].name if info.asr and info.asr[0].models else "unknown"


async def run(host: str, port: int) -> None:
    model = await model_name(host, port)
    run_id = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Model: {model}\n")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    total_err = total_words = exact = count = 0
    with open(RESULTS, "a") as out:
        for file in CASE_FILES:
            if not file.exists():
                continue
            for case in yaml.safe_load(file.read_text())["cases"]:
                if "reference" not in case:
                    continue
                pcm, rate, width, channels = load_audio(case, file.parent)
                audio_s = len(pcm) / (rate * width * channels)
                heard, ms = await transcribe(host, port, pcm, rate, width, channels)
                errors, words = word_errors(case["reference"], heard)
                right = errors == 0
                count += 1
                exact += right
                total_err += errors
                total_words += words
                print(f"{'ok  ' if right else 'MISS'} {ms:5.0f} ms  {case['name']}")
                if not right:
                    print(f"           heard {heard!r}")
                out.write(json.dumps({
                    "run": run_id, "model": model, "case": case["name"],
                    "reference": case["reference"], "heard": heard,
                    "errors": errors, "words": words, "ms": round(ms), "audio_s": round(audio_s, 2),
                }) + "\n")
    if count:
        print(f"\n{exact} of {count} exactly right; word error rate "
              f"{100 * total_err / max(total_words, 1):.1f}%")
    else:
        print("No cases with a reference yet. Record some: python3 tools/record_set.py")


def latest_runs() -> dict[str, list[dict]]:
    """Each model's most recent run."""
    if not RESULTS.exists():
        sys.exit("No results yet. Run: python3 tools/bench.py --host <server address>")
    rows = [json.loads(line) for line in RESULTS.read_text().splitlines() if line.strip()]
    newest: dict[str, str] = {}
    for r in rows:
        newest[r["model"]] = max(newest.get(r["model"], ""), r["run"])
    runs: dict[str, list[dict]] = {}
    for r in rows:
        if r["run"] == newest[r["model"]]:
            runs.setdefault(r["model"], []).append(r)
    return runs


def matrix() -> None:
    runs = latest_runs()
    print(f"{'model':32} {'exact':>7} {'WER':>6} {'avg ms':>7} {'ms per s':>9}")
    for model, rows in sorted(runs.items(), key=lambda kv: sum(r["errors"] for r in kv[1])):
        errors = sum(r["errors"] for r in rows)
        words = sum(r["words"] for r in rows)
        exact = sum(r["errors"] == 0 for r in rows)
        avg_ms = sum(r["ms"] for r in rows) / len(rows)
        per_s = sum(r["ms"] for r in rows) / max(sum(r["audio_s"] for r in rows), 0.01)
        print(f"{model:32} {exact:>3}/{len(rows):<3} {100 * errors / max(words, 1):5.1f}% "
              f"{avg_ms:7.0f} {per_s:9.0f}")
    print("\nexact = phrases heard word for word; WER = word error rate (lower is better);")
    print("ms per s = milliseconds of work per second of speech. Memory: see the server's logs/requests.jsonl.")


def misses() -> None:
    runs = latest_runs()
    by_case: dict[str, dict[str, str]] = {}
    for model, rows in runs.items():
        for r in rows:
            if r["errors"]:
                by_case.setdefault(r["case"], {})[model] = r["heard"]
    if not by_case:
        print("Every model got every phrase right.")
    for case, heard in sorted(by_case.items()):
        print(case)
        for model, text in sorted(heard.items()):
            print(f"    {model:30} {text!r}")


def main() -> None:
    p = argparse.ArgumentParser(description="Benchmark Oread's speech-to-text models")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=10310)
    p.add_argument("--matrix", action="store_true", help="compare all models measured so far")
    p.add_argument("--misses", action="store_true", help="show what each model got wrong")
    args = p.parse_args()
    if args.matrix:
        matrix()
    elif args.misses:
        misses()
    else:
        t0 = time.perf_counter()
        asyncio.run(run(args.host, args.port))
        print(f"({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    main()
