#!/usr/bin/env python3
"""Run Oread's test cases against a running Oread. Run after every change.

    python3 tools/regress.py                 # Oread on this machine
    python3 tools/regress.py --host <addr>   # Oread elsewhere

Cases live in tests/cases.yaml. Household voice clips stay in tests/private/
(never in git); cases there are picked up automatically from
tests/private/cases.yaml when that file exists.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import wave
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wyoming_client import transcribe  # noqa: E402


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("'", "")).split())


def load_audio(case: dict, base: Path) -> tuple[bytes, int, int, int]:
    if "silence" in case:
        rate = 16000
        return bytes(int(case["silence"] * rate) * 2), rate, 2, 1
    with wave.open(str(base / case["audio"]), "rb") as w:
        pcm, rate, width, channels = w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()
    convert = case.get("convert")
    if convert:  # check Oread copes with other rates and stereo
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        new_rate = convert.get("rate", rate)
        if new_rate != rate:
            positions = np.linspace(0, len(samples) - 1, int(len(samples) * new_rate / rate))
            samples = np.interp(positions, np.arange(len(samples)), samples)
            rate = new_rate
        new_channels = convert.get("channels", channels)
        if new_channels == 2 and channels == 1:
            samples = np.repeat(samples, 2)
            channels = 2
        pcm = samples.astype("<i2").tobytes()
    return pcm, rate, width, channels


def check(case: dict, heard: str) -> str | None:
    """None when the case passes, otherwise what went wrong."""
    got = normalize(heard)
    if "expect" in case:
        want = normalize(case["expect"])
        if got != want:
            return f"expected {want!r}"
    for word in case.get("expect_words", []):
        if normalize(word) not in got.split():
            return f"missing word {word!r}"
    if case.get("expect_empty") and got:
        return "expected nothing"
    return None


async def run(host: str, port: int) -> int:
    files = [ROOT / "tests" / "cases.yaml", ROOT / "tests" / "private" / "cases.yaml"]
    failures = total = 0
    for file in files:
        if not file.exists():
            continue
        for case in yaml.safe_load(file.read_text())["cases"]:
            total += 1
            pcm, rate, width, channels = load_audio(case, file.parent)
            heard, ms = await transcribe(host, port, pcm, rate, width, channels)
            problem = check(case, heard)
            mark = "PASS" if problem is None else "FAIL"
            print(f"{mark}  {case['name']}  ({ms:.0f} ms)")
            if problem:
                failures += 1
                print(f"      heard {heard!r}; {problem}")
    print(f"\n{total - failures} of {total} passed")
    return 1 if failures else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Run Oread's test cases")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=10310)
    args = p.parse_args()
    sys.exit(asyncio.run(run(args.host, args.port)))


if __name__ == "__main__":
    main()
