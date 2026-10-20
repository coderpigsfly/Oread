#!/usr/bin/env python3
"""Check the voice detector's settings against your saved clips before turning trimming on.

Trimming (trim_silence on a device) skips a clip with no speech and cuts the quiet after the
last speech. This reads every saved clip (read-only) and says which ones the current detector
settings would skip, and how much of each it would keep. A clip assigned to a person should
never be skipped: if one is, lower the detector's threshold (Settings, Models tab) and run it again.

    docker compose exec oread python tools/trim_check.py
    docker compose exec oread python tools/trim_check.py --device tablet
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from oread import catalog, settings as settings_mod  # noqa: E402
from oread.trim import Trimmer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", help="only this device's clips")
    parser.add_argument("--clips", help="the clips folder (default: Oread's data/clips)")
    args = parser.parse_args()
    cfg = settings_mod.load()
    folder = Path(args.clips) if args.clips else cfg["paths"]["data"] / "clips"
    listed = catalog.load()
    name = listed["defaults"]["vad"]
    trimmer = Trimmer(name, listed["vad"][name], cfg["paths"]["models"])
    print(f"Voice detector {name}: {trimmer.settings}")

    skipped_assigned, skipped, kept, total = [], [], [], 0
    for meta_path in sorted(folder.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        if args.device and meta.get("device") != args.device:
            continue
        audio = meta_path.with_suffix(".wav")
        if not audio.is_file():
            continue
        with wave.open(str(audio), "rb") as w:
            rate = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        total += 1
        left = trimmer.trim(samples, rate)
        if left.size == 0:
            (skipped_assigned if meta.get("profile") else skipped).append(meta)
        else:
            kept.append(left.size / max(samples.size, 1))

    print(f"{total} clips read")
    print(f"  skipped as no speech: {len(skipped) + len(skipped_assigned)}")
    for meta in skipped_assigned + skipped:
        who = f"assigned to {meta['profile']}" if meta.get("profile") else "not assigned"
        print(f"    {meta['id']} ({who}): \"{meta.get('transcript', '')}\"")
    if kept:
        print(f"  the rest keep {np.mean(kept) * 100:.0f}% of their length on average")
    if skipped_assigned:
        print(f"\n{len(skipped_assigned)} clip(s) assigned to a person would be skipped: lower the threshold.")
        sys.exit(1)
    print("\nNo clip assigned to a person is skipped.")


if __name__ == "__main__":
    main()
