"""Trimming the quiet after speech, before speech-to-text.

The voice detector (the default under vad: in models.yaml) finds where speech is. A device
with trim_silence on gets two things from it: a clip with no speech at all skips the decode
(the transcript is empty, as when nothing is heard), and the quiet after the last speech is
cut, keeping keep_after_speech seconds. The start is never cut: speech-to-text needs the
lead-in. Voice ID and the saved clip always get the full audio.

The detector is a helper: if it can't load or fails, the full clip is decoded as before.
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path

import numpy as np
import sherpa_onnx

_LOG = logging.getLogger(__name__)
RATE = 16000            # the rate the detector listens at


class Trimmer:
    def __init__(self, name: str, entry: dict, models_root: Path) -> None:
        self.name = name
        self.entry = entry
        self.settings = dict(entry.get("settings") or {})
        self.path = models_root / entry["file"]
        self._vad = None
        self._lock = threading.Lock()   # one detector, used by one request at a time

    def _load(self):
        if self._vad is None:
            if not self.path.is_file():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                part = self.path.with_suffix(".part")
                _LOG.info("Downloading the voice detector %s (first use only)", self.name)
                urllib.request.urlretrieve(self.entry["url"], part)
                part.rename(self.path)
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = str(self.path)
            config.silero_vad.threshold = float(self.settings["threshold"])
            config.silero_vad.min_silence_duration = float(self.settings["min_silence_duration"])
            config.silero_vad.min_speech_duration = float(self.settings["min_speech_duration"])
            config.sample_rate = RATE
            self._window = config.silero_vad.window_size
            self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=120)
        return self._vad

    def speech_end(self, samples: np.ndarray, rate: int) -> float | None:
        """Seconds into the clip where the last speech ends; None when there's no speech."""
        if rate != RATE and samples.size:
            at = np.arange(0, samples.size, rate / RATE)
            samples = np.interp(at, np.arange(samples.size), samples).astype(np.float32)
        with self._lock:
            vad = self._load()
            vad.reset()
            for i in range(0, samples.size, self._window):
                vad.accept_waveform(samples[i:i + self._window])
            vad.flush()
            end = None
            while not vad.empty():
                end = (vad.front.start + len(vad.front.samples)) / RATE
                vad.pop()
        return end

    def trim(self, samples: np.ndarray, rate: int) -> np.ndarray:
        """The clip up to keep_after_speech seconds after the last speech; empty when there's none."""
        end = self.speech_end(samples, rate)
        if end is None:
            return samples[:0]
        keep = end + float(self.settings.get("keep_after_speech", 0.6))
        return samples[:int(keep * rate)]
