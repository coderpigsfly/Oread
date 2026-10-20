#!/usr/bin/env python3
"""Record yourself reading tests/phrases.txt, one phrase at a time.

    python3 tools/record_set.py --host <server address>   # also shows what Oread heard
    python3 tools/record_set.py --only 7                  # redo phrase 7
    python3 tools/record_set.py --start 10                # pick up at phrase 10

Clips are saved to tests/private/audio/ (never committed), and
tests/private/cases.yaml is rewritten so regress.py and bench.py use them.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import RATE, record  # noqa: E402
from wyoming_client import describe_speaker, transcribe_full  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PHRASES = ROOT / "tests" / "phrases.txt"
PRIVATE = ROOT / "tests" / "private"
AUDIO = PRIVATE / "audio"


def phrases() -> list[str]:
    return [line.strip() for line in PHRASES.read_text().splitlines() if line.strip()]


def clip_path(number: int) -> Path:
    return AUDIO / f"{number:02d}.wav"


def save(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def write_cases(all_phrases: list[str]) -> int:
    cases = []
    for number, text in enumerate(all_phrases, 1):
        if clip_path(number).exists():
            cases.append({
                "name": f"{number:02d} {text}",
                "audio": f"audio/{number:02d}.wav",
                "reference": text,
            })
    PRIVATE.mkdir(parents=True, exist_ok=True)
    header = "# Written by tools/record_set.py from tests/phrases.txt. Private: never committed.\n"
    (PRIVATE / "cases.yaml").write_text(header + yaml.safe_dump({"cases": cases}, sort_keys=False))
    return len(cases)


def main() -> None:
    p = argparse.ArgumentParser(description="Record the benchmark phrases")
    p.add_argument("--host", help="also send each clip to Oread and show what it heard")
    p.add_argument("--port", type=int, default=10310)
    p.add_argument("--start", type=int, default=1, help="phrase number to start at")
    p.add_argument("--only", type=int, help="record just this phrase number")
    p.add_argument("--seconds", type=float, default=10, help="longest recording")
    args = p.parse_args()

    all_phrases = phrases()
    numbers = [args.only] if args.only else range(args.start, len(all_phrases) + 1)
    print(f"{len(all_phrases)} phrases. Speak normally, the way you talk to your voice assistant.\n")

    for number in numbers:
        text = all_phrases[number - 1]
        while True:
            print(f"--- {number} of {len(all_phrases)}:  {text}")
            pcm = record(args.seconds, fixed=False)
            if args.host:
                try:
                    heard, ms, context = asyncio.run(transcribe_full(args.host, args.port, pcm, RATE))
                    print(f"    Oread heard: {heard!r}  ({ms:.0f} ms); {describe_speaker(context)}")
                except OSError as err:  # Oread down or still starting: keep recording anyway
                    print(f"    (couldn't reach Oread: {err.strerror or err}; the clip can still be kept)")
            choice = input("    Enter = keep, r = redo, q = quit: ").strip().lower()
            if choice == "r":
                continue
            if choice == "q":
                print(f"\nSaved {write_cases(all_phrases)} clips so far.")
                return
            save(clip_path(number), pcm)
            break

    print(f"\nDone. {write_cases(all_phrases)} clips in tests/private/.")
    print("Next: python3 tools/bench.py --host <server address>")


if __name__ == "__main__":
    main()
