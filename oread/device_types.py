"""Device types: kinds of listening device (a Voice PE, an Android tablet, a laptop).

The list is device-types.yaml (shipped examples) with data/device-types.yaml
(yours) on top, the same way as models.yaml. A type in your file with a new
name is added; one with a shipped name replaces that entry whole; one marked
`removed: true` hides a shipped type. The Devices page adds types, renames
their labels and removes unused ones, saving to data/device-types.yaml; you
can also edit that file by hand and restart.

Each type has a label people read and an optional note. It can also give
starting settings for every device of that type, in the same `stt` and
`speaker` sections as settings.yaml (the page sets the two models); a device's
own settings still win.
"""

from __future__ import annotations

import copy
import re
import threading
from pathlib import Path

import yaml

from .errors import OreadError, SettingsError
from . import models, settings as settings_mod, speaker

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")
_SETTING_KEYS = {"stt", "speaker"}
_HEADER = ("# Your device types, kept by the Devices page (you can edit it by hand too).\n"
           "# Applied on top of device-types.yaml: a new name adds a type, a shipped\n"
           "# name replaces that type, and `removed: true` hides a shipped type.\n")


class DeviceTypeError(OreadError):
    pass


class DeviceTypes:
    def __init__(self, data_dir: Path, shipped: Path | None = None) -> None:
        self.shipped_file = shipped or settings_mod.APP_DIR / "device-types.yaml"
        self.file = data_dir / "device-types.yaml"
        self._lock = threading.Lock()
        self.shipped = self._read(self.shipped_file, required=True)
        self.mine = self._read(self.file, required=False)

    # ---------- reading ----------

    def _read(self, path: Path, required: bool) -> dict:
        if not path.exists():
            if required:
                raise SettingsError(f"{path} is missing; it lists the device types")
            return {}
        loaded = yaml.safe_load(path.read_text()) or {}
        types = loaded.get("types") or {}
        if not isinstance(types, dict):
            raise SettingsError(f"{path}: 'types' should be a list of names, each with a label")
        out = {}
        for name, entry in types.items():
            name = str(name)
            entry = dict(entry or {})
            if not NAME.match(name):
                raise SettingsError(f"{path}: type name '{name}' should be 1-30 lowercase letters, "
                                    "digits, - or _")
            if not entry.get("removed"):
                self._check_models(entry, f"{path}: type '{name}'")
            out[name] = entry
        return out

    @staticmethod
    def _check_models(entry: dict, where: str) -> None:
        stt_model = (entry.get("stt") or {}).get("model")
        speaker_model = (entry.get("speaker") or {}).get("model")
        try:
            if stt_model:
                models.get(stt_model)
            if speaker_model:
                speaker.get(speaker_model)
        except SettingsError as err:
            raise SettingsError(f"{where}: {err}") from err

    def all(self) -> dict[str, dict]:
        """Every type in use: name -> entry (label, note, stt, speaker)."""
        with self._lock:
            merged = {**copy.deepcopy(self.shipped)}
            for name, entry in self.mine.items():
                if entry.get("removed"):
                    merged.pop(name, None)
                else:
                    merged[name] = copy.deepcopy(entry)
            return merged

    def settings_map(self) -> dict[str, dict]:
        """name -> the settings a type gives its devices (what settings.devices() layers in)."""
        return {name: {k: v for k, v in entry.items() if k in _SETTING_KEYS}
                for name, entry in self.all().items()}

    def view(self, used_by: dict[str, list[str]]) -> list[dict]:
        """For the pages: each type with its label, note, models and the devices using it."""
        out = []
        for name, entry in sorted(self.all().items(), key=lambda kv: (kv[1].get("label") or kv[0]).lower()):
            out.append({
                "name": name,
                "label": entry.get("label") or name,
                "note": entry.get("note") or "",
                "stt_model": (entry.get("stt") or {}).get("model") or "",
                "speaker_model": (entry.get("speaker") or {}).get("model") or "",
                "shipped": name in self.shipped,
                "used_by": used_by.get(name, []),
            })
        return out

    # ---------- changing ----------

    def add(self, name: str, label: str, note: str | None, stt_model: str | None,
            speaker_model: str | None) -> dict:
        name = (name or "").strip().lower()
        if not NAME.match(name):
            raise DeviceTypeError("Type names are 1-30 lowercase letters, digits, - or _")
        if name in self.all():
            raise DeviceTypeError(f"There's already a type named '{name}'", 409)
        entry = {"label": _label(label, name)}
        if note and note.strip():
            entry["note"] = note.strip()[:200]
        if stt_model:
            entry["stt"] = {"model": stt_model}
        if speaker_model:
            entry["speaker"] = {"model": speaker_model}
        try:
            self._check_models(entry, f"Type '{name}'")
        except SettingsError as err:
            raise DeviceTypeError(str(err)) from err
        with self._lock:
            self.mine[name] = entry
            self._save()
        return self.one(name)

    def relabel(self, name: str, label: str | None, note: str | None) -> dict:
        current = self.all().get(name)
        if current is None:
            raise DeviceTypeError(f"No type named '{name}'", 404)
        if label is not None:
            current["label"] = _label(label, name)
        if note is not None:
            if note.strip():
                current["note"] = note.strip()[:200]
            else:
                current.pop("note", None)
        with self._lock:
            self.mine[name] = current      # a shipped type gets your copy, which then wins
            self._save()
        return self.one(name)

    def remove(self, name: str, used_by: list[str]) -> None:
        if name not in self.all():
            raise DeviceTypeError(f"No type named '{name}'", 404)
        if used_by:
            raise DeviceTypeError(f"'{name}' is still used by {', '.join(used_by)}; change their "
                                  "type or remove them first", 409)
        with self._lock:
            if name in self.shipped:
                self.mine[name] = {"removed": True}
            else:
                self.mine.pop(name, None)
            self._save()

    def one(self, name: str) -> dict:
        return next(t for t in self.view({}) if t["name"] == name)

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(_HEADER + yaml.safe_dump({"types": self.mine}, sort_keys=False, allow_unicode=True))
        tmp.replace(self.file)


def _label(label: str | None, name: str) -> str:
    label = (label or "").strip()
    if not label:
        raise DeviceTypeError(f"Give the type '{name}' a label people will recognise, "
                              "like “Kitchen speaker”")
    if len(label) > 60:
        raise DeviceTypeError("Keep the label to 60 characters or fewer")
    return label
