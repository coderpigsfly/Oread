"""Listening devices: one Wyoming port each, managed while Oread runs.

On the first start the device list comes from settings.yaml. Once a device
is added, renamed or removed on the Devices page, the whole list is saved to
data/devices.yaml, and from then on that file is the device list (so
settings.yaml stays as in git and a pull never overwrites your devices).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
import wave
from functools import partial
from pathlib import Path

import numpy as np
import yaml
from wyoming.info import AsrModel, AsrProgram, Attribution, Info
from wyoming.server import AsyncTcpServer

from .errors import OreadError, SettingsError
from . import __version__, catalog, metrics, models, phrases, settings as settings_mod, speaker
from .device_types import DeviceTypes
from .handler import DeviceRuntime, SttHandler
from .stt import SpeechToText
from .trim import Trimmer

_LOG = logging.getLogger("oread.devices")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")


class DeviceError(OreadError):
    pass


def build_info(model: models.SttModel) -> Info:
    return Info(asr=[AsrProgram(
        name="oread",
        description="Oread speech-to-text and speaker ID (sherpa-onnx)",
        attribution=Attribution(name="Oread", url="https://github.com/coderpigsfly/oread"),
        installed=True,
        version=__version__,
        models=[AsrModel(
            name=model.name,
            description=f"{model.name} ({model.license})",
            attribution=Attribution(name=model.author, url=model.card),
            installed=True,
            version=None,
            languages=list(model.languages),
        )],
    )])


class Loader:
    """Loads each model once; devices that share a model share one copy."""

    def __init__(self, models_root: Path) -> None:
        self.models_root = models_root
        self.stt: dict = {}
        self.voiceprinters: dict = {}
        self.trimmers: dict = {}

    def stt_for(self, cfg: dict) -> SpeechToText:
        model = models.get(cfg["model"])
        threads = int(cfg["num_threads"])
        language = str(cfg.get("language") or "en")
        key = (model.name, threads, language)
        if key not in self.stt:
            folder = models.ensure(model, self.models_root)
            t0 = time.perf_counter()
            self.stt[key] = SpeechToText(model, folder, threads, language)
            _LOG.info("Loaded %s in %.1f s (memory now %.0f MB)",
                      model.name, time.perf_counter() - t0, metrics.rss_mb())
        return self.stt[key]

    def trimmer(self) -> Trimmer:
        """The default voice detector with its settings (loaded on first use, then shared)."""
        listed = catalog.load()
        name = listed["defaults"]["vad"]
        entry = listed["vad"][name]
        key = (name, tuple(sorted(entry["settings"].items())))
        if key not in self.trimmers:
            self.trimmers.clear()   # settings changed: the old one goes
            self.trimmers[key] = Trimmer(name, entry, self.models_root)
        return self.trimmers[key]

    def voiceprinter_for(self, cfg: dict) -> speaker.Voiceprinter:
        model = speaker.get(cfg["model"])
        threads = int(cfg["num_threads"])
        key = (model.name, threads)
        if key not in self.voiceprinters:
            path = speaker.ensure(model, self.models_root)
            self.voiceprinters[key] = speaker.Voiceprinter(model, path, threads)
            _LOG.info("Loaded voiceprint model %s (memory now %.0f MB)",
                      model.name, metrics.rss_mb())
        return self.voiceprinters[key]


def _mode(value, device: str) -> str:
    value = str(value).lower()
    if value not in phrases.MODES:
        raise SettingsError(f"Device '{device}': phrase_mode must be one of {', '.join(phrases.MODES)}")
    return value


def wav_voiceprint(printer: speaker.Voiceprinter, path: Path):
    with wave.open(str(path), "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return printer.voiceprint(samples, w.getframerate())


class DeviceManager:
    def __init__(self, cfg: dict, store, limit: asyncio.Semaphore, access, publisher=None,
                 device_types: DeviceTypes | None = None) -> None:
        self.cfg = cfg
        if cfg.get("device_types"):
            _LOG.warning("device_types in settings.yaml is no longer read; device types live in "
                         "data/device-types.yaml now (or add them on the Devices page)")
        self.device_types = device_types or DeviceTypes(cfg["paths"]["data"])
        self.publisher = publisher
        self.store = store
        self.habits = phrases.Habits(store)
        self.limit = limit
        self.access = access
        self.loader = Loader(cfg["paths"]["models"])
        self.file = cfg["paths"]["data"] / "devices.yaml"
        self.host = cfg["server"]["host"]
        self.port_range = tuple(int(p) for p in cfg["server"]["port_range"])
        self.api_port = int(cfg["api"]["port"])
        self.entries: dict[str, dict] = {}       # name -> {type, port, ...} as saved
        self.runtimes: dict[str, DeviceRuntime] = {}
        self.types: dict[str, str | None] = {}
        self.ports: dict[str, int] = {}
        self.servers: dict[str, AsyncTcpServer] = {}
        self.tuning = None                         # set by main once Tuning exists
        self._lock = asyncio.Lock()
        if self.file.exists():
            self.entries = (yaml.safe_load(self.file.read_text()) or {}).get("devices") or {}
            self.source = "data/devices.yaml (managed on the Devices page)"
        else:
            self.entries = copy.deepcopy(cfg["devices"])
            self.source = "settings.yaml"

    # ---------- building ----------

    def _resolve(self, entries: dict) -> list[settings_mod.Device]:
        cfg = dict(self.cfg)
        cfg["devices"] = entries
        cfg["device_types"] = self.device_types.settings_map()
        return settings_mod.devices(cfg)

    def _runtime(self, device: settings_mod.Device) -> DeviceRuntime:
        s = device.settings
        stt = self.loader.stt_for(s["stt"])
        return DeviceRuntime(
            name=device.name,
            info=build_info(stt.model),
            stt=stt,
            voiceprinter=self.loader.voiceprinter_for(s["speaker"]),
            unknown_below=float(s["speaker"]["unknown_below"]),
            match_above=float(s["speaker"]["match_above"]),
            min_training_seconds=float(s["speaker"]["min_training_seconds"]),
            phrase_from=float(s["speaker"]["phrase_from"]),
            phrase_to=float(s["speaker"]["phrase_to"]),
            phrase_mode=_mode(s["speaker"]["phrase_mode"], device.name),
            publish_speaker=bool(s["speaker"].get("publish_speaker", False)),
            trimmer=self.loader.trimmer(),
            trim_silence=bool(s["stt"].get("trim_silence", False)),
            hears_own_speaker=bool(s["speaker"].get("hears_own_speaker", False)),
            assistant_device=device.assistant_device,
        )

    def load_all(self) -> None:
        """Load models for every device (before anything listens)."""
        for device in self._resolve(self.entries):
            self._check_port(device.port, device.name)
            self.runtimes[device.name] = self._runtime(device)
            self.types[device.name] = device.type
            self.ports[device.name] = device.port

    def rebuild_profiles(self) -> None:
        for printer in self.loader.voiceprinters.values():
            t0 = time.perf_counter()
            self.store.rebuild(printer.model.name, partial(wav_voiceprint, printer))
            _LOG.info("Profiles ready for %s in %.1f s", printer.model.name, time.perf_counter() - t0)

    async def start_all(self) -> None:
        for name in list(self.runtimes):
            await self._start(name)
            if self.publisher:   # each device's Home Assistant settings, read ahead of its first clip
                self.publisher.device_settings(self.runtimes[name].assistant_device)

    async def _start(self, name: str) -> None:
        runtime = self.runtimes[name]
        server = AsyncTcpServer(self.host, self.ports[name])
        handler = partial(SttHandler, runtime, self.store, self.limit, self.cfg["paths"]["logs"],
                          self.access, self.habits, self.publisher)
        await server.start(handler)
        self.servers[name] = server
        _LOG.info("Device %s (%s): %s + %s on port %d", name, self.types[name] or "no type",
                  runtime.stt.model.name, runtime.voiceprinter.model.name, self.ports[name])

    async def stop_all(self) -> None:
        for name in list(self.servers):
            await self.servers.pop(name).stop()

    # ---------- the API's view ----------

    def list(self) -> dict:
        types = self.device_types.settings_map()

        def chosen_by(name: str, section: str) -> str:
            """Where a device's model comes from: the device itself, its type, or the default."""
            if ((self.entries.get(name) or {}).get(section) or {}).get("model"):
                return "device"
            if ((types.get(self.types[name]) or {}).get(section) or {}).get("model"):
                return "type"
            return "default"

        return {
            "source": self.source,
            "port_range": list(self.port_range),
            "types": self.device_types.view(self.type_users()),
            "devices": [
                {"name": n, "type": self.types[n], "port": self.ports[n],
                 "stt_model": r.stt.model.name, "speaker_model": r.voiceprinter.model.name,
                 "stt_from": chosen_by(n, "stt"), "speaker_from": chosen_by(n, "speaker"),
                 "publish_speaker": r.publish_speaker, "assistant_device": r.assistant_device}
                for n, r in sorted(self.runtimes.items(), key=lambda kv: self.ports[kv[0]])
            ],
        }

    def type_users(self) -> dict[str, list[str]]:
        """Type name -> the devices of that type."""
        out: dict[str, list[str]] = {}
        for device, kind in sorted(self.types.items()):
            if kind:
                out.setdefault(kind, []).append(device)
        return out

    # ---------- device types ----------

    def add_type(self, name: str, label: str, note: str | None, stt_model: str | None,
                 speaker_model: str | None) -> dict:
        return self.device_types.add(name, label, note, stt_model, speaker_model)

    def relabel_type(self, name: str, label: str | None, note: str | None) -> dict:
        found = self.device_types.relabel(name, label, note)
        return {**found, "used_by": self.type_users().get(name, [])}

    def remove_type(self, name: str) -> dict:
        self.device_types.remove(name, self.type_users().get(name, []))
        return {"removed": name}

    async def add(self, name: str, type_: str | None, port: int | None,
                  stt_model: str | None, speaker_model: str | None) -> dict:
        name = name.strip().lower()
        async with self._lock:
            if not _NAME.match(name):
                raise DeviceError("Device names are 1-30 lowercase letters, digits, - or _")
            if name in self.entries:
                raise DeviceError(f"Device '{name}' already exists", 409)
            if port is None:
                port = self._free_port()
            entry: dict = {"port": int(port)}
            if type_:
                entry["type"] = type_
            if stt_model:
                models.get(stt_model)  # refuse unknown names before saving
                entry["stt"] = {"model": stt_model}
            if speaker_model:
                speaker.get(speaker_model)
                entry["speaker"] = {"model": speaker_model}
            trial = {**self.entries, name: entry}
            device = next(d for d in self._resolve(trial) if d.name == name)
            self._check_port(device.port, name)
            # loading a new model can take a while (and may download it)
            runtime = await asyncio.to_thread(self._runtime, device)
            if runtime.voiceprinter.model.name not in {
                    r.voiceprinter.model.name for r in self.runtimes.values()}:
                printer = runtime.voiceprinter
                await asyncio.to_thread(self.store.rebuild, printer.model.name,
                                        partial(wav_voiceprint, printer))
            self.entries = trial
            self.runtimes[name] = runtime
            self.types[name] = device.type
            self.ports[name] = device.port
            await self._start(name)
            self._save()
        return next(d for d in self.list()["devices"] if d["name"] == name)

    async def rename(self, name: str, new_name: str) -> dict:
        new_name = new_name.strip().lower()
        async with self._lock:
            if name not in self.entries:
                raise DeviceError(f"No device named '{name}'", 404)
            if not _NAME.match(new_name):
                raise DeviceError("Device names are 1-30 lowercase letters, digits, - or _")
            if new_name != name and new_name in self.entries:
                raise DeviceError(f"Device '{new_name}' already exists", 409)
            self.entries = {(new_name if k == name else k): v for k, v in self.entries.items()}
            runtime = self.runtimes.pop(name)
            runtime.name = new_name  # its port keeps listening; new clips get the new name
            self.runtimes[new_name] = runtime
            self.types[new_name] = self.types.pop(name)
            self.ports[new_name] = self.ports.pop(name)
            self.servers[new_name] = self.servers.pop(name)
            if self.tuning:
                self.tuning.rename_device(name, new_name)
            moved = await asyncio.to_thread(self.store.rename_device, name, new_name)
            if self.store.retrain:
                self.store.retrain.rename_device(name, new_name)
            self._save()
        return {"renamed": name, "to": new_name, "clips_updated": moved}

    async def set_models(self, name: str, stt_model: str | None, speaker_model: str | None) -> dict:
        """Change a device's models while Oread runs. None leaves a model as it is; "" goes back
        to the default (from its type, or models.yaml). The device's port pauses for a moment
        while the new model loads; speaker settings changed while running are kept."""
        async with self._lock:
            if name not in self.entries:
                raise DeviceError(f"No device named '{name}'", 404)
            entry = copy.deepcopy(self.entries[name] or {})
            for key, value, model_list in (("stt", stt_model, models), ("speaker", speaker_model, speaker)):
                if value is None:
                    continue
                section = dict(entry.get(key) or {})
                if value == "":
                    section.pop("model", None)
                else:
                    model_list.get(value)   # refuse unknown names before anything changes
                    section["model"] = value
                if section:
                    entry[key] = section
                else:
                    entry.pop(key, None)
            trial = {**self.entries, name: entry}
            await self._refresh(name, trial)
            self.entries = trial
            self._save()
            self._unload_unused()
        return next(d for d in self.list()["devices"] if d["name"] == name)

    async def set_assistant_device(self, name: str, device_id: str) -> dict:
        """Match a device to its device in the voice assistant ("" = none); each clip then records
        that device's settings there."""
        async with self._lock:
            if name not in self.entries:
                raise DeviceError(f"No device named '{name}'", 404)
            if device_id and not re.fullmatch(r"[a-f0-9]{8,64}", device_id):
                raise DeviceError("assistant_device is a device id from the voice assistant (letters a-f and digits)")
            entry = dict(self.entries[name] or {})
            entry.pop("ha_device", None)   # its old name
            if device_id:
                entry["assistant_device"] = device_id
            else:
                entry.pop("assistant_device", None)
            self.entries = {**self.entries, name: entry}
            self.runtimes[name].assistant_device = device_id or None
            self._save()
        if self.publisher:   # read its settings now, so the next clip has them
            self.publisher.device_settings(device_id or None)
        return next(d for d in self.list()["devices"] if d["name"] == name)

    async def _refresh(self, name: str, entries: dict) -> str:
        """Bring one device up to date with `entries` and the model list. Only numbers changed
        (thresholds): they apply in place, at once. A different model, or its threads: the new
        one is loaded and the device's port restarts on it. Speaker settings changed for that
        device while running (data/tuning.yaml) stay on top. Says which happened."""
        device = next(d for d in self._resolve(entries) if d.name == name)
        old = self.runtimes[name]
        runtime = await asyncio.to_thread(self._runtime, device)   # may download it the first time
        if self.tuning:
            self.tuning.reapply(name, runtime)
        if runtime.stt is old.stt and runtime.voiceprinter is old.voiceprinter:
            for knob in ("unknown_below", "match_above", "min_training_seconds", "phrase_from",
                         "phrase_to", "phrase_mode", "publish_speaker", "trimmer", "trim_silence", "assistant_device",
                         "hears_own_speaker"):
                setattr(old, knob, getattr(runtime, knob))
            return "settings"
        printer = runtime.voiceprinter
        if printer.model.name not in {r.voiceprinter.model.name for r in self.runtimes.values()}:
            await asyncio.to_thread(self.store.rebuild, printer.model.name,
                                    partial(wav_voiceprint, printer))
        await self.servers.pop(name).stop()
        self.runtimes[name] = runtime
        await self._start(name)
        return "reloaded"

    def model_users(self, kind: str, name: str) -> list[str]:
        """Who relies on a model: devices using it now, devices or device types that name it."""
        section = {"speech": "stt", "voice": "speaker"}.get(kind)
        if section is None:
            return []
        attr = "stt" if kind == "speech" else "voiceprinter"
        users = {n for n, r in self.runtimes.items() if getattr(r, attr).model.name == name}
        users |= {n for n, e in self.entries.items() if ((e or {}).get(section) or {}).get("model") == name}
        users |= {f"type {t}" for t, e in self.device_types.settings_map().items()
                  if (e.get(section) or {}).get("model") == name}
        return sorted(users)

    async def reload_model(self, kind: str, name: str) -> list[str]:
        """After a model's entry changed (its files, say): devices using it load it afresh, and for a
        voice model every person's voiceprint is worked out again from their saved clips."""
        if kind not in ("speech", "voice"):
            return []
        attr = "stt" if kind == "speech" else "voiceprinter"
        async with self._lock:
            users = [n for n, r in self.runtimes.items() if getattr(r, attr).model.name == name]
            if not users:
                return []
            cache = self.loader.stt if kind == "speech" else self.loader.voiceprinters
            for key in [k for k in cache if k[0] == name]:
                del cache[key]
            for device in users:
                await self._refresh(device, self.entries)
            if kind == "voice":
                printer = self.runtimes[users[0]].voiceprinter
                await asyncio.to_thread(self.store.rebuild, name, partial(wav_voiceprint, printer), True)
            self._unload_unused()
        return users

    async def refresh_devices(self, names: list[str]) -> None:
        """Rebuild these devices from their settings now (after their while-running changes were forgotten)."""
        async with self._lock:
            for name in names:
                await self._refresh(name, self.entries)

    async def apply_model_list(self) -> dict:
        """After the model list changed (settings or a default): every device picks it up now."""
        done = {}
        async with self._lock:
            for name in list(self.runtimes):
                done[name] = await self._refresh(name, self.entries)
            self._unload_unused()
        return {"devices": {n: how for n, how in done.items()}}

    def _unload_unused(self) -> None:
        """Let go of models no device uses any more, so their memory can be freed."""
        stt_used = {id(r.stt) for r in self.runtimes.values()}
        vp_used = {id(r.voiceprinter) for r in self.runtimes.values()}
        for key in [k for k, v in self.loader.stt.items() if id(v) not in stt_used]:
            _LOG.info("Unloading %s (no device uses it now)", key[0])
            del self.loader.stt[key]
        for key in [k for k, v in self.loader.voiceprinters.items() if id(v) not in vp_used]:
            _LOG.info("Unloading voiceprint model %s (no device uses it now)", key[0])
            del self.loader.voiceprinters[key]
        import gc
        gc.collect()

    def model_choices(self) -> dict:
        """Every model a device can use: what it costs, who uses it now, and its settings."""
        listed = catalog.load()
        root = self.cfg["paths"]["models"]

        def users(attr: str, model_name: str) -> list[str]:
            return sorted(n for n, r in self.runtimes.items()
                          if getattr(r, attr).model.name == model_name)

        def common(kind: str, m) -> dict:
            shipped = catalog.shipped_settings(kind, m.name)
            return {"name": m.name, "label": m.label, "memory_mb": m.memory_mb, "notes": m.notes,
                    "license": m.license, "default": m.name == listed["defaults"][kind],
                    "settings": m.settings, "shipped_settings": shipped,
                    "changed": any(m.settings.get(k) != v for k, v in shipped.items())}

        return {
            "speech": [{**common("speech", m), "downloaded": models.is_installed(m, root),
                        "used_by": users("stt", m.name)}
                       for m in models.all_models().values()],
            "voice": [{**common("voice", m), "downloaded": (root / "speaker" / m.file).is_file(),
                       "used_by": users("voiceprinter", m.name)}
                      for m in speaker.all_models().values()],
            "vad": [{"name": n, "label": e.get("label") or n, "memory_mb": 0, "notes": e.get("notes", ""),
                     "license": e.get("license", ""), "default": n == listed["defaults"]["vad"],
                     "settings": e["settings"], "shipped_settings": catalog.shipped_settings("vad", n),
                     "changed": any(e["settings"].get(k) != v
                                    for k, v in catalog.shipped_settings("vad", n).items()),
                     "used_by": sorted(d for d, r in self.runtimes.items()
                                       if r.trim_silence and n == listed["defaults"]["vad"]),
                     "downloaded": (root / e["file"]).is_file()}
                    for n, e in listed["vad"].items()],
            "knobs": {kind: {key: {"kind": k, "min": lo, "max": hi, "help": text}
                             for key, (k, lo, hi, text) in catalog.KNOBS[kind].items()}
                      for kind in catalog.SECTIONS},
        }

    async def remove(self, name: str) -> dict:
        async with self._lock:
            if name not in self.entries:
                raise DeviceError(f"No device named '{name}'", 404)
            if len(self.entries) == 1:
                raise DeviceError("Oread needs at least one device", 409)
            await self.servers.pop(name).stop()
            del self.entries[name]
            del self.runtimes[name], self.types[name]
            port = self.ports.pop(name)
            if self.tuning:
                self.tuning.remove_device(name)
            self._save()
            self._unload_unused()
        return {"removed": name, "port_freed": port,
                "note": "its clips and any profiles they belong to are kept"}

    # ---------- helpers ----------

    def _free_port(self) -> int:
        low, high = self.port_range
        used = set(self.ports.values()) | {self.api_port}
        for port in range(low, high + 1):
            if port not in used:
                return port
        raise DeviceError(f"No free port left in {low}-{high}; widen server.port_range "
                          "(and the ports line in docker-compose.yml)", 409)

    def _check_port(self, port: int, name: str) -> None:
        low, high = self.port_range
        if not low <= port <= high:
            raise SettingsError(f"Device '{name}' uses port {port}, outside server.port_range "
                                f"{low}-{high} (the ports Docker opens)")
        for other, used in self.ports.items():
            if other != name and used == port:
                raise SettingsError(f"Devices '{other}' and '{name}' both use port {port}")

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(
            "# Devices, managed on the Devices page. While this file exists it replaces\n"
            "# the devices section of settings.yaml. Delete it to go back to settings.yaml.\n"
            + yaml.safe_dump({"devices": self.entries}, sort_keys=False))
        tmp.replace(self.file)
        self.source = "data/devices.yaml (managed on the Devices page)"
