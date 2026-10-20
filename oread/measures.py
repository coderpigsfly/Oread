"""How a clip sounds: the numbers that show a change at the device (gain, a noise gate, a filter).

Worked out for every request, with or without words, and kept two ways: in the clip's own record,
and in a per-device log (data/measures/<device>.jsonl) that outlives the clip, so a device's sound
has a history even after its clips are pruned or discarded. Numpy only; a few milliseconds a clip.

    speech_db     level of the loudest 30% of the clip (dB below full scale)
    noise_db      level of the quietest 20% (the room between words)
    gated_pct     share of the clip that is digital silence (a noise gate or suppression)
    peak_db       the highest sample
    clipped_pct   share of samples at full scale (too much gain)
    bands_db      the shape of the speech: each band's level against 300-1000 Hz
    brightness_hz the centre of the speech's sound (higher is brighter)
    clip_s        the clip's length
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from .metrics import drop_sample_lines

FRAME, HOP = 512, 256
BANDS = ((0, 150), (150, 300), (1000, 3000), (3000, 6000), (6000, 8000))
REFERENCE = (300, 1000)
SILENT_DB = -90.0     # a frame quieter than this is digital silence


def _db(power: float) -> float:
    return round(10 * float(np.log10(power + 1e-12)), 1)


def measure(samples: np.ndarray, rate: int) -> dict:
    """The numbers above for one clip (float samples, -1 to 1)."""
    out: dict = {"clip_s": round(samples.size / rate, 2) if rate else 0.0}
    if samples.size < FRAME:
        return out
    frames = np.lib.stride_tricks.sliding_window_view(samples, FRAME)[::HOP]
    power = (frames ** 2).mean(axis=1)
    loud = power >= np.percentile(power, 70)
    quiet = power <= np.percentile(power, 20)
    spectrum = np.abs(np.fft.rfft(frames[loud] * np.hanning(FRAME), axis=1)) ** 2
    mean = spectrum.mean(axis=0)
    freqs = np.fft.rfftfreq(FRAME, 1 / rate)

    def band(lo: float, hi: float) -> float:
        return float(mean[(freqs >= lo) & (freqs < hi)].sum())

    reference = band(*REFERENCE)
    out.update({
        "speech_db": _db(power[loud].mean()),
        "noise_db": _db(power[quiet].mean()),
        "gated_pct": round(100 * float(np.mean(10 * np.log10(power + 1e-12) < SILENT_DB)), 1),
        "peak_db": _db(float(np.abs(samples).max()) ** 2),
        "clipped_pct": round(100 * float(np.mean(np.abs(samples) > 0.98)), 2),
        "bands_db": {f"{lo}-{hi}": round(_db(band(lo, hi)) - _db(reference), 1)
                     for lo, hi in BANDS if lo < rate / 2},
        "brightness_hz": round(float((freqs * mean).sum() / max(mean.sum(), 1e-12))),
    })
    return out


class MeasureLog:
    """One line per request, per device: data/measures/<device>.jsonl. Never pruned with clips."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _file(self, device: str) -> Path:
        return self.folder / f"{device}.jsonl"

    def add(self, device: str, line: dict) -> None:
        with self._lock, self._file(device).open("a") as f:
            f.write(json.dumps(line) + "\n")

    def read(self, device: str, limit: int = 1000) -> list[dict]:
        path = self._file(device)
        if not path.exists():
            return []
        with self._lock:
            lines = path.read_text().splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]

    def forget_sample(self) -> int:
        """The sample household's lines out of every device's log."""
        with self._lock:
            return sum(drop_sample_lines(f) for f in self.folder.glob("*.jsonl"))

    def rename_device(self, old: str, new: str) -> None:
        with self._lock:
            old_file, new_file = self._file(old), self._file(new)
            if old_file.exists():
                with new_file.open("a") as out:
                    out.write(old_file.read_text())
                old_file.unlink()
