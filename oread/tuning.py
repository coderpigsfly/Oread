"""Device knobs that can be changed while Oread runs (who spoke, and trimming the quiet).

A device's starting values come from its voice model's settings
(models.yaml), settings.yaml, its type and the device. Changes made for a
device while running are saved to data/tuning.yaml and applied on top at
every start, so they survive restarts and never touch those files.
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml

from .errors import OreadError

KNOBS = {
    # name: (lowest, highest)
    "min_training_seconds": (0.5, 10.0),
    "unknown_below": (0.0, 1.0),
    "match_above": (0.0, 1.0),
    "phrase_from": (0.0, 1.0),
    "phrase_to": (0.0, 1.0),
}
CHOICES = {
    "phrase_mode": ("off", "shadow", "on"),
}
SWITCHES = {"publish_speaker", "trim_silence", "hears_own_speaker"}


class TuningError(OreadError):
    pass


class Tuning:
    def __init__(self, runtimes: dict, path: Path) -> None:
        self.runtimes = runtimes  # device name -> DeviceRuntime
        self.path = path
        self._lock = threading.Lock()
        self._saved: dict = {}
        if path.exists():
            self._saved = yaml.safe_load(path.read_text()) or {}
        for device, values in (self._saved.get("devices") or {}).items():
            if device in runtimes:
                self._apply(runtimes[device], values)

    def minimum(self, device: str) -> float:
        runtime = self.runtimes.get(device)
        if runtime is not None:
            return runtime.min_training_seconds
        # a clip from a device that no longer exists: use the strictest current value
        return max((r.min_training_seconds for r in self.runtimes.values()), default=2.0)

    def current(self) -> dict:
        return {
            name: {
                "stt_model": r.stt.model.name,
                "speaker_model": r.voiceprinter.model.name,
                **{knob: getattr(r, knob) for knob in (*KNOBS, *CHOICES, *SWITCHES)},
                "set_for_this_device": sorted((self._saved.get("devices") or {}).get(name, {})),
            }
            for name, r in self.runtimes.items()
        }

    def update(self, device: str | None, values: dict) -> dict:
        values = {k: v for k, v in values.items() if v is not None}
        if not values:
            raise TuningError("Nothing to change: give at least one value")
        for knob, value in list(values.items()):
            if knob in SWITCHES:
                if not isinstance(value, bool):
                    raise TuningError(f"{knob} must be true or false")
                continue
            if knob in CHOICES:
                value = str(value).lower()
                if value not in CHOICES[knob]:
                    raise TuningError(f"{knob} must be one of: {', '.join(CHOICES[knob])}")
                values[knob] = value
                continue
            value = values[knob] = float(value)
            low, high = KNOBS[knob]
            if not low <= value <= high:
                raise TuningError(f"{knob} must be between {low} and {high}")
        targets = [device] if device else list(self.runtimes)
        for name in targets:
            if name not in self.runtimes:
                raise TuningError(f"No device named '{name}'")
            r = self.runtimes[name]
            unknown = values.get("unknown_below", r.unknown_below)
            match = values.get("match_above", r.match_above)
            if unknown > match:
                raise TuningError(
                    f"{name}: unknown_below ({unknown}) can't be higher than match_above ({match})")
            p_from = values.get("phrase_from", r.phrase_from)
            p_to = values.get("phrase_to", r.phrase_to)
            if p_from > p_to:
                raise TuningError(
                    f"{name}: phrase_from ({p_from}) can't be higher than phrase_to ({p_to})")
        with self._lock:
            saved = self._saved.setdefault("devices", {})
            for name in targets:
                self._apply(self.runtimes[name], values)
                saved.setdefault(name, {}).update(values)
            self._write()
        return self.current()

    def reset(self, device: str | None) -> None:
        """Forget changes made while running; settings.yaml values return after a restart."""
        with self._lock:
            saved = self._saved.setdefault("devices", {})
            for name in [device] if device else list(saved):
                saved.pop(name, None)
            self._write()

    def reapply(self, device: str, runtime) -> None:
        """Put this device's while-running changes back on top of a freshly built runtime."""
        self._apply(runtime, (self._saved.get("devices") or {}).get(device) or {})

    def rename_device(self, old: str, new: str) -> None:
        with self._lock:
            saved = self._saved.setdefault("devices", {})
            if old in saved:
                saved[new] = saved.pop(old)
                self._write()

    def remove_device(self, name: str) -> None:
        with self._lock:
            if (self._saved.get("devices") or {}).pop(name, None) is not None:
                self._write()

    @staticmethod
    def _apply(runtime, values: dict) -> None:
        for knob, value in values.items():
            if knob in KNOBS:
                setattr(runtime, knob, float(value))
            elif knob in CHOICES and value in CHOICES[knob]:
                setattr(runtime, knob, value)
            elif knob in SWITCHES and isinstance(value, bool):
                setattr(runtime, knob, value)

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "# Speaker settings changed while Oread runs; applied on top of settings.yaml.\n"
            + yaml.safe_dump(self._saved, sort_keys=True))
        tmp.replace(self.path)
