"""Load settings.yaml and work out each device's settings.

Levels, each overriding only what it names: the device's model (its own
settings in models.yaml), then `defaults` (how every device behaves), then
the device's type, then the device itself. Which model a device uses comes
from the device, else its type, else `defaults:` in models.yaml.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import SettingsError

APP_DIR = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "max_concurrent": 2, "port_range": [10310, 10339],
               "allowed_clients": []},
    "api": {"port": 10311, "tls": "household", "tls_names": [], "cert_file": "", "key_file": ""},
    "home_assistant": {"url": "", "token_key": "home-assistant", "timeout_s": 0.5},
    "wepwawet": {"url": "", "token_key": "wepwawet", "timeout_s": 10},
    "review": {"max_unassigned": 200},
    "stats": {"keep_days": 400},   # Stats, where the time goes: how long each request's steps are kept (logs/time-steps.jsonl)
    # an assistant's voice learned from her text-to-speech: once it has this many real clips of her (the
    # router's echoes), its voiceprint is made from those alone (the clean lines sound too unlike the room)
    "assistant_voice": {"real_clips_first": 5},
    # how every device behaves, whatever its models; the models and their own
    # settings (threads, thresholds) are in models.yaml
    "defaults": {
        "stt": {"trim_silence": False},
        "speaker": {"min_training_seconds": 2, "phrase_mode": "shadow", "publish_speaker": False,
                    "hears_own_speaker": False},   # the patch: a device whose mic hears its own speaker
    },
    "devices": {"default": {"port": 10310}},
    "paths": {"models": "models", "data": "data", "logs": "logs", "keys": "keys"},
    "logging": {"level": "INFO", "keep_requests": 10000},
}

# keys on a device entry that describe the device itself, not its settings
_DEVICE_KEYS = {"type", "port", "assistant_device", "ha_device"}   # ha_device: its old name


@dataclass(frozen=True)
class Device:
    name: str
    type: str | None
    port: int
    settings: dict  # the merged result of all three levels
    assistant_device: str | None = None   # its device in the voice assistant, whose settings each clip records


def merge(base: dict, extra: dict | None) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Read settings; OREAD_SETTINGS can point at another file."""
    path = Path(path or os.environ.get("OREAD_SETTINGS", APP_DIR / "settings.yaml"))
    loaded = yaml.safe_load(path.read_text()) if path.exists() else {}
    loaded = loaded or {}
    # your own changes: data/settings.yaml on top (paths can't move the data folder itself)
    data_dir = Path((loaded.get("paths") or {}).get("data") or DEFAULTS["paths"]["data"])
    local = (data_dir if data_dir.is_absolute() else APP_DIR / data_dir) / "settings.yaml"
    if local.exists():
        mine = yaml.safe_load(local.read_text()) or {}
        mine.pop("paths", None)
        devices = mine.pop("devices", None)
        loaded = merge(loaded, mine)
        if devices:
            loaded["devices"] = devices
    settings = merge(DEFAULTS, {k: v for k, v in loaded.items() if k != "devices"})
    settings["devices"] = loaded.get("devices") or DEFAULTS["devices"]
    for key, rel in settings["paths"].items():
        p = Path(rel)
        settings["paths"][key] = p if p.is_absolute() else APP_DIR / p
    return settings


def devices(settings: dict) -> list[Device]:
    """Each device with its final settings, checked for clashes."""
    out: list[Device] = []
    seen_ports: dict[int, str] = {}
    types = settings.get("device_types") or {}   # filled in from device-types.yaml (device_types.py)
    for name, entry in settings["devices"].items():
        entry = entry or {}
        kind = entry.get("type")
        if kind is not None and kind not in types:
            raise SettingsError(f"Device '{name}' has type '{kind}', which isn't a device type "
                                "(device-types.yaml or data/device-types.yaml)")
        if "port" not in entry:
            raise SettingsError(f"Device '{name}' needs a port")
        port = int(entry["port"])
        if port in seen_ports:
            raise SettingsError(f"Devices '{seen_ports[port]}' and '{name}' both use port {port}")
        if port == int(settings.get("api", {}).get("port", 10311)):
            raise SettingsError(f"Device '{name}' uses port {port}, which is the API port")
        seen_ports[port] = name
        merged = merge(settings["defaults"], types.get(kind) if kind else None)
        merged = merge(merged, {k: v for k, v in entry.items() if k not in _DEVICE_KEYS})
        out.append(Device(name=name, type=kind, port=port, settings=with_model_settings(merged),
                          assistant_device=entry.get("assistant_device") or entry.get("ha_device") or None))
    return out


def with_model_settings(merged: dict) -> dict:
    """Put each model's own settings (models.yaml) underneath what the levels above chose."""
    from . import catalog
    models = catalog.load()
    out = dict(merged)
    for section, kind in (("stt", "speech"), ("speaker", "voice")):
        chosen = dict(merged.get(section) or {})
        name = chosen.get("model") or models["defaults"][kind]
        if name not in models[kind]:
            raise SettingsError(f"Unknown {kind} model '{name}'. Known (models.yaml): "
                                f"{', '.join(sorted(models[kind]))}")
        out[section] = merge(models[kind][name]["settings"], {**chosen, "model": name})
    return out
