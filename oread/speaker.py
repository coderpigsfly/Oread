"""Voiceprints: turn a clip of speech into a fixed-length list of numbers
describing how the voice sounds (not what was said).

The voiceprint model never changes or retrains. What "learns" is the set of
clips assigned to each profile (see store.py).
"""

from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np
import sherpa_onnx

from . import catalog
from .errors import SettingsError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeakerModel:
    name: str
    file: str             # saved as models/speaker/<file>
    url: str
    author: str
    license: str
    card: str
    label: str = ""
    memory_mb: int = 0
    notes: str = ""
    settings: dict = field(default_factory=dict, hash=False, compare=False)   # starting settings


@cache
def all_models() -> dict[str, SpeakerModel]:
    """Every voice model, from models.yaml (and data/models.yaml), read the first time it's asked for."""
    return {
        name: SpeakerModel(name=name, file=e["file"], url=e["url"], author=e.get("author", ""),
                           license=e.get("license", ""), card=e.get("card", ""),
                           label=e.get("label") or name, memory_mb=int(e.get("memory_mb") or 0),
                           notes=e.get("notes", ""), settings=dict(e.get("settings") or {}))
        for name, e in catalog.load()["voice"].items()
    }


def get(name: str) -> SpeakerModel:
    models = all_models()
    if name not in models:
        known = ", ".join(sorted(models))
        raise SettingsError(f"Unknown voice model '{name}'. Known (models.yaml): {known}")
    return models[name]


def ensure(model: SpeakerModel, models_root: Path) -> Path:
    """Download the model file (tens of MB) if it isn't there yet."""
    path = models_root / "speaker" / model.file
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    _LOG.info("Downloading voiceprint model %s (first start only)", model.name)
    urllib.request.urlretrieve(model.url, part)
    part.rename(path)
    return path


class Voiceprinter:
    def __init__(self, model: SpeakerModel, path: Path, num_threads: int) -> None:
        self.model = model
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(path), num_threads=num_threads, provider="cpu"
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def voiceprint(self, samples: np.ndarray, rate: int) -> np.ndarray | None:
        """Unit-length voiceprint, or None when the clip is too short to tell."""
        if samples.size == 0:
            return None
        stream = self._extractor.create_stream()
        stream.accept_waveform(rate, samples)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            return None
        return unit(np.array(self._extractor.compute(stream), dtype=np.float32))


def unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector
