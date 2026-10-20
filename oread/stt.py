"""Speech-to-text through sherpa-onnx."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import sherpa_onnx

from .errors import SettingsError
from .models import SttModel


class SpeechToText:
    def __init__(self, model: SttModel, folder: Path, num_threads: int, language: str = "en") -> None:
        self.model = model
        paths = {role: str(folder / name) for role, name in model.files.items()}
        make = sherpa_onnx.OfflineRecognizer
        if model.kind in ("nemo_transducer", "transducer"):
            extra = {"model_type": "nemo_transducer"} if model.kind == "nemo_transducer" else {}
            self._recognizer = make.from_transducer(num_threads=num_threads, **paths, **extra)
        elif model.kind == "moonshine":
            self._recognizer = make.from_moonshine(num_threads=num_threads, **paths)
        elif model.kind == "whisper":
            self._recognizer = make.from_whisper(
                num_threads=num_threads, language=language, task="transcribe", **paths
            )
        else:
            raise SettingsError(f"Model kind '{model.kind}' is not supported yet")

    def transcribe(self, pcm: bytes, rate: int, width: int, channels: int) -> str:
        """Turn raw PCM audio into text. Empty audio gives an empty string."""
        return self.transcribe_samples(to_float_mono(pcm, width, channels), rate)

    def transcribe_samples(self, samples: np.ndarray, rate: int) -> str:
        """The same, from float samples already made mono."""
        if samples.size == 0:
            return ""
        stream = self._recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        self._recognizer.decode_stream(stream)
        text = clean(stream.result.text)
        if text.isupper():  # some models answer in capitals; HA expects normal text
            text = text.capitalize()
        return text


def clean(text: str) -> str:
    """Drop non-speech markers some models emit, like Whisper's [BLANK_AUDIO]."""
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = " ".join(text.split())
    if text.startswith("(") and text.endswith(")"):  # e.g. "(silence)", "(music)"
        return ""
    return text


def to_float_mono(pcm: bytes, width: int, channels: int) -> np.ndarray:
    """PCM bytes -> float32 samples in [-1, 1], channels averaged to mono."""
    if width == 2:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(pcm, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        samples = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported sample width {width}")
    if channels > 1:
        usable = samples.size - samples.size % channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return samples
