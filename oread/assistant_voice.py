"""An assistant's own voice, learned from the text-to-speech voice it answers in.

The patch for a device whose microphone hears its own speaker (Settings, Devices: "It hears its
own speaker"): Oread matches what it hears against the assistant's own voice too, so the router
doesn't take her for a person. That voice needs no recording: for each device with the switch on
and its Home Assistant device matched (Devices page), Oread reads which pipeline the device answers
with, and that pipeline's text-to-speech voice; has Home Assistant say the lines in voice_lines.txt
(data/voice_lines.txt replaces the shipped oread/voice_lines.txt) in that voice; and keeps them as
an assistant's profile named after the voice. Learned once per voice: when the switch is turned on,
when Oread starts, and when someone presses "Learn now" on the People page. A voice learned before
stays; a device moved to a new voice gets the new one learned too.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .errors import OreadError

_LOG = logging.getLogger("oread.assistant_voice")
SHIPPED_LINES = Path(__file__).with_name("voice_lines.txt")


def profile_name(voice: dict) -> str:
    """The profile's name for a text-to-speech voice: the voice's own name (or its engine's)."""
    name = re.sub(r"[^A-Za-z0-9 _'.-]", "-", str(voice.get("voice") or voice["engine"]))
    return name.strip(" -")[:40] or "assistant voice"


class AssistantVoices:
    def __init__(self, publisher, store, devices, data_dir: Path) -> None:
        self.publisher = publisher
        self.store = store
        self.devices = devices
        self.lines_file = data_dir / "voice_lines.txt"
        self.last: dict | None = None          # the last time Oread looked: {at, voices, error}
        self._running = threading.Lock()

    def lines(self) -> list[str]:
        f = self.lines_file if self.lines_file.exists() else SHIPPED_LINES
        return [ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]

    def wanted(self) -> list[dict]:
        """The voices the devices with the switch on answer in: [{engine, voice, language, devices}]."""
        listening = {n: r.assistant_device for n, r in self.devices.runtimes.items()
                     if r.hears_own_speaker and r.assistant_device}
        if not listening:
            return []
        if not self.publisher.configured:
            raise ValueError("Home Assistant isn't set up (the Connections page)")
        known = self.publisher.pipelines()
        by_name = {p.get("name"): p for p in known["pipelines"]}
        by_id = {p.get("id"): p for p in known["pipelines"]}
        voices: dict[tuple, dict] = {}
        for device, ha_device in sorted(listening.items()):
            for chosen in self.publisher.chosen_pipelines(ha_device):
                pipe = by_id.get(known["preferred"]) if chosen == "preferred" else by_name.get(chosen)
                if not pipe or not pipe.get("tts_engine"):
                    continue
                key = (pipe["tts_engine"], pipe.get("tts_voice"))
                v = voices.setdefault(key, {"engine": key[0], "voice": key[1],
                                            "language": pipe.get("tts_language") or pipe.get("language"),
                                            "devices": []})
                if device not in v["devices"]:
                    v["devices"].append(device)
        return list(voices.values())

    def learned(self) -> dict[tuple, str]:
        """(engine, voice) -> the profile already learned from it."""
        return {(p["voice"]["engine"], p["voice"].get("voice")): p["name"]
                for p in self.store.profiles() if p.get("voice")}

    def learn_all(self, again: bool = False) -> dict:
        """Learn every wanted voice not learned yet (again: learn them over). Returns the view."""
        if not self._running.acquire(blocking=False):
            return self.view()                 # already at it
        try:
            out = []
            have = self.learned()
            for v in self.wanted():
                key = (v["engine"], v["voice"])
                if key in have and not again:
                    out.append({**v, "profile": have[key], "new": False})
                else:
                    if key in have:              # learned over, under the name it has now
                        self.store.delete_profile(have[key])
                    out.append({**v, "profile": self._learn(v, have.get(key)), "new": True})
                self.store.set_voice_devices(out[-1]["profile"], v["devices"])   # its devices: their echoes teach it
            if any(v["new"] for v in out):
                self.devices.rebuild_profiles()      # their voiceprints, for every model in use
            self.last = {"at": _now(), "voices": out, "error": None}
        except Exception as err:               # Home Assistant, the voice or the network: say why, keep going
            _LOG.warning("Couldn't learn the assistant's own voice: %s", err)
            self.last = {"at": _now(), "voices": [], "error": str(err) or type(err).__name__}
        finally:
            self._running.release()
        return self.view()

    def _learn(self, v: dict, name: str | None = None) -> str:
        name = name or profile_name(v)
        taken = {p["name"].lower() for p in self.store.profiles()}
        base, n = name, 2
        while name.lower() in taken:
            name, n = f"{base[:36]} {n}", n + 1
        made = {"engine": v["engine"], "voice": v["voice"], "language": v["language"]}
        self.store.create_profile(name, kind="assistant", voice=made)
        for line in self.lines():
            pcm, rate = self.publisher.speak(v["engine"], v["voice"], v["language"], line)
            self.store.add_made_clip(name, pcm, rate, line, made)
        _LOG.info("Learned the assistant's voice %s (%s) for %s", name, v["engine"], ", ".join(v["devices"]))
        return name

    def teach(self, echoes: list[dict]) -> dict | None:
        """The router's echoes (each pull): her own answer heard back on a device, found by her words.
        Each clip Oread still has, not assigned yet, goes on the voice that device answers in: her voice
        as that device hears it, through its speaker and the room. Echoes found by the voice ID itself
        are left out (they'd only teach it what it already thinks). Returns the counts."""
        by_device: dict[str, list[str]] = {}
        for p in self.store.profiles():
            for d in (p.get("voice") or {}).get("devices") or []:
                by_device.setdefault(d, []).append(p["name"])
        counts = {"taught": 0, "already": 0, "not_here": 0, "no_voice": 0, "by_voice": 0, "refused": 0, "two_voices": 0}
        for e in echoes:
            names = by_device.get(e.get("device")) or []
            name = names[0] if len(names) == 1 else None
            if e.get("by") != "words":
                counts["by_voice"] += 1
            elif len(names) > 1:
                counts["two_voices"] += 1        # the device answers in two voices: which one came back isn't known
            elif not name:
                counts["no_voice"] += 1          # the device's voice isn't learned (its switch is off)
            else:
                try:
                    clip = self.store.clip(e["clip"])
                except (OreadError, KeyError):
                    counts["not_here"] += 1      # trimmed from the review list before this pull
                    continue
                if clip.get("profile"):
                    counts["already"] += 1       # someone (or an earlier pull) decided it
                    continue
                try:
                    self.store.assign(e["clip"], name, {"name": "house router", "kind": "echo"})
                    counts["taught"] += 1
                except OreadError:
                    counts["refused"] += 1       # too short, or heard before the device's last retrain
        if counts["taught"]:
            _LOG.info("Her voice taught from %d of the router's echoes", counts["taught"])
        return counts

    def start(self, again: bool = False) -> None:
        """Learn in the background (Home Assistant says each line; that takes a while)."""
        threading.Thread(target=self.learn_all, args=(again,), daemon=True).start()

    def view(self) -> dict:
        return {"learning": self._running.locked(), "last": self.last, "real_clips_first": self.store.real_first,
                "lines": len(self.lines()), "lines_file": "data/voice_lines.txt" if self.lines_file.exists()
                else "oread/voice_lines.txt (shipped)"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
