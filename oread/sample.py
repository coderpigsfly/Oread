"""The sample household: short clips read by three LibriSpeech volunteers, added and removed as one
(Settings, Sample household), so a new Oread has something to show before anyone has spoken to it.

Adding sends each clip through the same steps as a request from a listening device (voice-pe, or the
first device), like the Try it button: real words, voiceprints and guesses, nothing reported onward.
The teach clips go first and are assigned to their sample person; then the waiting clips, so the
guesses on the Learn page are Oread's own. Everything the sample makes is marked sample: true (its
clips, its people and their lines in the logs), so removing it takes exactly that away.

The clips and who reads them: sample/sample.yaml.
"""

from __future__ import annotations

import asyncio
import logging
import wave
from pathlib import Path

import yaml

from . import metrics
from .errors import OreadError
from .handler import process

_LOG = logging.getLogger(__name__)
FOLDER = Path(__file__).resolve().parent.parent / "sample"


class SampleError(OreadError):
    """A request about the sample household that can't be done, with a message fit to show a person."""


class Sample:
    def __init__(self, store, devices, times=None, folder: Path = FOLDER) -> None:
        self.store = store
        self.devices = devices
        self.times = times          # timing.TimeLog: its lines are cleaned too
        self.folder = folder
        self._lock = asyncio.Lock()

    def clips(self) -> list[dict]:
        try:
            return yaml.safe_load((self.folder / "sample.yaml").read_text())["clips"]
        except (OSError, KeyError, TypeError, yaml.YAMLError) as err:
            raise SampleError(f"The sample household's files are missing ({err})", 404) from err

    def device(self) -> str | None:
        """The device the sample is heard on: voice-pe, or else the first device."""
        names = list(self.devices.runtimes)
        return "voice-pe" if "voice-pe" in names else (names[0] if names else None)

    def status(self) -> dict:
        added = [c for c in self.store.clips("all", limit=1_000_000) if c.get("sample")]
        people = [p["name"] for p in self.store.profiles() if p.get("sample")]
        return {"available": (self.folder / "sample.yaml").is_file(), "added": bool(added or people),
                "clips": len(added), "people": people, "device": self.device(), "busy": self._lock.locked()}

    async def add(self) -> dict:
        if self._lock.locked():
            raise SampleError("The sample household is already being added or removed", 409)
        async with self._lock:
            if self.status()["added"]:
                raise SampleError("The sample household is already here; remove it first", 409)
            clips = self.clips()
            device = self.device()
            if device is None:
                raise SampleError("Add a listening device first; the sample is heard on one", 409)
            runtime = self.devices.runtimes[device]
            people = sorted({c["person"] for c in clips if c.get("person")})
            taken = {p["name"].lower() for p in self.store.profiles()}
            clash = [p for p in people if p.lower() in taken]
            if clash:
                raise SampleError(f"There's already someone called {', '.join(clash)}; rename them first", 409)
            for name in people:
                self.store.create_profile(name, sample=True)
            heard = 0
            # the teach clips first, so the waiting ones are guessed against their people
            for clip in sorted(clips, key=lambda c: c.get("role") != "teach"):
                with wave.open(str(self.folder / "clips" / clip["file"]), "rb") as w:
                    pcm, rate = w.readframes(w.getnframes()), w.getframerate()
                req = metrics.Request(self.devices.cfg["paths"]["logs"], "sample")
                req.start_step()
                req.end_step("receive")
                _, context = await process(runtime, self.store, self.devices.limit, self.devices.habits, None,
                                           pcm, rate, 2, 1, req, publish=False, sample=True)
                if context.get("clip"):
                    heard += 1
                    if clip.get("role") == "teach" and clip.get("person"):
                        self.store.assign(context["clip"], clip["person"], {"name": "sample", "kind": "sample"})
            _LOG.info("Added the sample household on %s: %d clips, %s", device, heard, ", ".join(people))
            return self.status()

    async def remove(self) -> dict:
        if self._lock.locked():
            raise SampleError("The sample household is already being added or removed", 409)
        async with self._lock:
            gone = self.store.remove_sample()
            lines = metrics.forget_sample(self.devices.cfg["paths"]["logs"]) + self.store.measures.forget_sample()
            if self.times is not None:
                lines += self.times.forget_sample()
            _LOG.info("Removed the sample household: %d clips, %s, %d log lines",
                      gone["clips"], ", ".join(gone["people"]) or "no people", lines)
            return {**gone, "log_lines": lines, **self.status()}
