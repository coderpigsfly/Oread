"""Compare models on your own clips, for one device. Runs only when someone asks.

Two kinds:

- voice: a real backtest. Assigned clips are confirmed answers (a person said
  who was speaking), so each model is scored on them: for each of the device's
  assigned clips, the voices are learned from every *other* assigned clip, then
  Oread checks whether that model names the right person, says "maybe", says
  unknown, or names the wrong person. The device's current voice model is
  scored the same way, side by side.
- speech: a side-by-side. There are no "correct" words to score against, only
  what Oread heard at the time, so the candidate model listens to the device's
  newest clips and every clip where its words differ is shown next to the
  original for a person to judge (the judgements are tallied).

Gentle on the machine: one comparison at a time, one thread, one clip at a
time, holding one of the working slots only while a clip is processed, so live
requests always have the other. The candidate model is loaded for the test
only (unless a device already uses it) and let go afterwards. Results stay
until the next comparison or a restart.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import re
import time
import wave
from datetime import datetime, timezone

import numpy as np

from .errors import OreadError
from . import models, speaker
from .stt import SpeechToText, to_float_mono

_LOG = logging.getLogger("oread.compare")


class CompareError(OreadError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _words(text: str) -> str:
    """For deciding whether two transcripts say the same thing: case and punctuation don't count."""
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).split())


def _read_wav(path) -> tuple[bytes, int, int, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()


class Comparisons:
    def __init__(self, devices, store) -> None:
        self.devices = devices
        self.store = store
        self.job: dict | None = None
        self._task: asyncio.Task | None = None
        self._cancel = False

    # ---------- what the API calls ----------

    def view(self) -> dict:
        return self.job or {"state": "none"}

    def start(self, device: str, kind: str, model: str, limit: int, who: str) -> dict:
        if self._task and not self._task.done():
            raise CompareError("A comparison is already running; wait for it or cancel it", 409)
        runtime = self.devices.runtimes.get(device)
        if runtime is None:
            raise CompareError(f"No device named '{device}'", 404)
        limit = max(5, min(int(limit), 200))
        if kind == "speech":
            candidate = models.get(model)
            current = runtime.stt.model
        elif kind == "voice":
            candidate = speaker.get(model)
            current = runtime.voiceprinter.model
        else:
            raise CompareError("kind is speech or voice")
        if kind == "speech" and candidate.name == current.name:
            raise CompareError(f"{device} already uses {candidate.label}; pick another model to compare")
        self._cancel = False
        self.job = {"state": "starting", "kind": kind, "device": device, "model": candidate.name,
                    "model_label": candidate.label, "current": current.name,
                    "current_label": current.label, "limit": limit, "done": 0, "total": 0,
                    "started": _now(), "by": who, "note": ""}
        self._task = asyncio.create_task(self._run(runtime, kind, candidate, limit))
        return self.job

    def cancel(self) -> dict:
        """Stop a running comparison; or, once it's finished, put it away (it won't show again)."""
        if self._task and not self._task.done():
            self._cancel = True
            return self.view()
        self.job = None
        return {"state": "none"}

    def judge(self, clip_id: str, choice: str) -> dict:
        job = self.job
        if not job or job.get("kind") != "speech":
            raise CompareError("There's no speech comparison to judge", 409)
        if choice not in ("current", "candidate", "neither", ""):
            raise CompareError("choice is current, candidate, neither, or empty to clear")
        for row in job.get("different", []):
            if row["clip"] == clip_id:
                row["judged"] = choice or None
                break
        else:
            raise CompareError(f"Clip '{clip_id}' isn't in this comparison", 404)
        tally = {"current": 0, "candidate": 0, "neither": 0}
        for row in job["different"]:
            if row.get("judged"):
                tally[row["judged"]] += 1
        job["judged"] = tally
        return job

    # ---------- the work ----------

    async def _run(self, runtime, kind: str, candidate, limit: int) -> None:
        job = self.job
        try:
            if kind == "speech":
                await self._speech(runtime, candidate, limit, job)
            else:
                await self._voice(runtime, candidate, limit, job)
            job["state"] = "cancelled" if self._cancel else "done"
        except CompareError as err:
            job["state"], job["note"] = "failed", str(err)
        except Exception as err:   # report it on the page instead of losing it
            _LOG.exception("Comparison failed")
            job["state"], job["note"] = "failed", f"{type(err).__name__}: {err}"
        finally:
            job["finished"] = _now()
            gc.collect()   # let a test-only model go

    async def _step(self, fn, *args):
        """One clip's work: hold a working slot only while doing it, so live requests keep the other."""
        async with self.devices.limit:
            return await asyncio.to_thread(fn, *args)

    async def _speech(self, runtime, candidate: models.SttModel, limit: int, job: dict) -> None:
        clips = [c for c in self.store.clips("all", runtime.name, limit)]
        job["total"] = len(clips)
        if not clips:
            raise CompareError(f"{runtime.name} has no saved clips yet; speak to it (or use Try it as it) first")
        loaded = next((s for key, s in self.devices.loader.stt.items() if key[0] == candidate.name), None)
        if loaded is None:
            job["state"] = "loading"
            if not models.is_installed(candidate, self.devices.cfg["paths"]["models"]):
                job["note"] = f"Downloading {candidate.label} (first time only)…"
            folder = await asyncio.to_thread(models.ensure, candidate, self.devices.cfg["paths"]["models"])
            loaded = await asyncio.to_thread(SpeechToText, candidate, folder, 1)
            job["note"] = ""
        job["state"] = "running"
        job["same"], job["different"], seconds, audio = 0, [], 0.0, 0.0
        for clip in clips:
            if self._cancel:
                break
            pcm, rate, width, channels = _read_wav(self.store.audio_path(clip["id"]))
            t0 = time.perf_counter()
            text = await self._step(loaded.transcribe, pcm, rate, width, channels)
            seconds += time.perf_counter() - t0
            audio += clip["audio_s"]
            if _words(text) == _words(clip["transcript"]):
                job["same"] += 1
            else:
                job["different"].append({"clip": clip["id"], "time": clip["time"], "audio_s": clip["audio_s"],
                                         "current": clip["transcript"], "candidate": text, "judged": None})
            job["done"] += 1
            job["seconds_per_second_of_speech"] = round(seconds / audio, 3) if audio else None
            await asyncio.sleep(0)
        job["judged"] = {"current": 0, "candidate": 0, "neither": 0}
        del loaded

    async def _voice(self, runtime, candidate: speaker.SpeakerModel, limit: int, job: dict) -> None:
        assigned = self.store.clips("assigned", None, 100000)
        tests = [c for c in assigned if c["device"] == runtime.name][:limit]
        people = {c["profile"] for c in assigned}
        if len(tests) < 2:
            raise CompareError(f"{runtime.name} needs at least 2 assigned clips to test voice models "
                               "(assign some on the Learn page first)")
        job["total"] = len(assigned)
        job["state"] = "loading"
        current = runtime.voiceprinter
        loaded = next((v for key, v in self.devices.loader.voiceprinters.items()
                       if key[0] == candidate.name), None)
        if loaded is None:
            path = await asyncio.to_thread(speaker.ensure, candidate, self.devices.cfg["paths"]["models"])
            loaded = await asyncio.to_thread(speaker.Voiceprinter, candidate, path, 1)
        job["state"] = "running"
        # one voiceprint per assigned clip, per model (saved ones are reused)
        prints: dict[str, dict[str, np.ndarray]] = {current.model.name: {}, candidate.name: {}}
        for clip in assigned:
            if self._cancel:
                return
            raw = self.store._clips.get(clip["id"], {})
            saved = raw.get("voiceprints", {})
            needed = [p for p in {current, loaded} if p.model.name not in saved]
            for p in {current, loaded}:
                if p.model.name in saved:
                    prints[p.model.name][clip["id"]] = np.array(saved[p.model.name], dtype=np.float32)
            if needed:
                pcm, rate, width, channels = _read_wav(self.store.audio_path(clip["id"]))
                samples = to_float_mono(pcm, width, channels)
                for p in needed:
                    vec = await self._step(p.voiceprint, samples, rate)
                    if vec is not None:
                        prints[p.model.name][clip["id"]] = vec
            job["done"] += 1
            await asyncio.sleep(0)
        # each model judged by its own thresholds: the device's for the one it uses now,
        # the candidate's own (models.yaml) for the one being tried
        pairs = [(current.model.name, current.model.label, runtime.unknown_below, runtime.match_above)]
        if candidate.name != current.model.name:
            pairs.append((candidate.name, candidate.label, float(candidate.settings["unknown_below"]),
                          float(candidate.settings["match_above"])))
        job["results"] = [self._score(name, label, prints[name], assigned, tests, unknown, match)
                          for name, label, unknown, match in pairs]
        job["people"] = len(people)
        job["tested"] = len(tests)
        del loaded

    @staticmethod
    def _score(name: str, label: str, prints: dict, assigned: list, tests: list,
               unknown_below: float, match_above: float) -> dict:
        """Leave one out: learn the voices without the clip, then ask who it is."""
        out = {"model": name, "label": label, "right": 0, "maybe": 0, "unknown": 0, "wrong": 0,
               "skipped": 0, "tested": 0}
        right_scores, other_scores = [], []
        for clip in tests:
            vec = prints.get(clip["id"])
            if vec is None:
                out["skipped"] += 1
                continue
            groups: dict[str, list] = {}
            for other in assigned:
                if other["id"] != clip["id"] and other["id"] in prints:
                    groups.setdefault(other["profile"], []).append(prints[other["id"]])
            if clip["profile"] not in groups:   # the only clip of that person: nothing to learn from
                out["skipped"] += 1
                continue
            scores = {}
            for person, vectors in groups.items():
                centre = np.mean(vectors, axis=0)
                centre = centre / (np.linalg.norm(centre) or 1)
                scores[person] = float(np.dot(centre, vec))
            best = max(scores, key=scores.get)
            right_scores.append(scores[clip["profile"]])
            others = [s for p, s in scores.items() if p != clip["profile"]]
            if others:
                other_scores.append(max(others))
            out["tested"] += 1
            if scores[best] < unknown_below:
                out["unknown"] += 1
            elif best != clip["profile"]:
                out["wrong"] += 1 if scores[best] >= match_above else 0
                out["maybe"] += 0 if scores[best] >= match_above else 1
            elif scores[best] >= match_above:
                out["right"] += 1
            else:
                out["maybe"] += 1
        out["average_right_score"] = round(float(np.mean(right_scores)), 3) if right_scores else None
        out["average_closest_other"] = round(float(np.mean(other_scores)), 3) if other_scores else None
        return out
