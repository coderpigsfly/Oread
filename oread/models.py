"""Model catalog and first-start download.

Models are never shipped in the repo. The list lives in models.yaml (and
your additions in data/models.yaml): where to download each, which files it
needs, its license, and what to expect.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import catalog
from .errors import SettingsError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SttModel:
    name: str
    kind: str             # how sherpa-onnx loads it
    url: str
    folder: str           # folder name inside the archive
    files: dict           # role -> file name inside the folder
    languages: tuple
    author: str
    license: str
    card: str             # model card with license details
    label: str = ""       # short name for the pages
    memory_mb: int = 0    # memory it takes once loaded (measured)
    notes: str = ""       # what to expect, in plain words
    settings: dict = field(default_factory=dict, hash=False, compare=False)   # starting settings


@cache
def all_models() -> dict[str, SttModel]:
    """Every speech model, from models.yaml (and data/models.yaml), read the first time it's asked for."""
    return {
        name: SttModel(name=name, kind=e["kind"], url=e["url"], folder=e["folder"],
                       files=dict(e["files"]), languages=tuple(e.get("languages") or ("en",)),
                       author=e.get("author", ""), license=e.get("license", ""), card=e.get("card", ""),
                       label=e.get("label") or name, memory_mb=int(e.get("memory_mb") or 0),
                       notes=e.get("notes", ""), settings=dict(e.get("settings") or {}))
        for name, e in catalog.load()["speech"].items()
    }


def get(name: str) -> SttModel:
    models = all_models()
    if name not in models:
        known = ", ".join(sorted(models))
        raise SettingsError(f"Unknown speech model '{name}'. Known (models.yaml): {known}")
    return models[name]


def model_dir(model: SttModel, models_root: Path) -> Path:
    return models_root / model.folder


def is_installed(model: SttModel, models_root: Path) -> bool:
    folder = model_dir(model, models_root)
    return all((folder / f).is_file() for f in model.files.values())


def ensure(model: SttModel, models_root: Path) -> Path:
    """Download and unpack the model if it isn't there yet."""
    folder = model_dir(model, models_root)
    if is_installed(model, models_root):
        return folder

    models_root.mkdir(parents=True, exist_ok=True)
    archive = models_root / (model.folder + ".tar.bz2.part")
    _LOG.info("Downloading %s (first start only) from %s", model.name, model.url)
    with urllib.request.urlopen(model.url) as response, open(archive, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, next_report = 0, 0.1
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total and done / total >= next_report:
                _LOG.info("  %d%% of %d MB", round(done / total * 100), total >> 20)
                next_report += 0.1

    _LOG.info("Unpacking %s", archive.name)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(models_root, filter="data")
    archive.unlink()

    if not is_installed(model, models_root):
        shutil.rmtree(folder, ignore_errors=True)
        raise SettingsError(f"Model {model.name} unpacked but required files are missing")
    _LOG.info("Model %s ready in %s", model.name, folder)
    return folder
