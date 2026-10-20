"""Clips, profiles and matching.

Every request that heard words is saved as a clip: the audio, its
transcript, which device heard it, its voiceprint, and Oread's best guess.
Unassigned clips wait on the Learn page (the newest `max_unassigned` are kept, and any clip a
mishearing was heard in: kept_for: mishearing, so it can be played again later).
A profile is a name plus the clips a person assigned to it; its voiceprint
is the average of those clips' voiceprints. Assigning or removing a clip
recomputes that average. That is the learning.

A clip also records how it was heard (the audio measures, the models, the device's settings in
the voice assistant, its settings period) and, once assigned, who assigned it and when.
A device can have its own voiceprint for a person (retrain.py); `retrain` is set at start.

Layout under data/:
    clips/<id>.wav, clips/<id>.json
    profiles.json
    measures/<device>.jsonl   (measures.py: kept when clips go)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import OreadError
from .measures import MeasureLog
from .speaker import unit
from .stt import to_float_mono

_LOG = logging.getLogger(__name__)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _'.-]{0,39}$")


class StoreError(OreadError):
    """A request the store refuses, with a message fit to show a person."""


class Store:
    def __init__(self, data_dir: Path, max_unassigned: int = 200) -> None:
        self.clip_dir = data_dir / "clips"
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_file = data_dir / "profiles.json"
        self.max_unassigned = max_unassigned
        self._lock = threading.RLock()
        self._clips: dict[str, dict] = {}
        for meta_file in self.clip_dir.glob("*.json"):
            try:
                meta = json.loads(meta_file.read_text())
                self._clips[meta["id"]] = meta
            except (OSError, ValueError, KeyError) as err:
                _LOG.warning("Skipping unreadable clip %s: %s", meta_file.name, err)
        self._profiles: dict[str, dict] = {}
        if self.profiles_file.exists():
            self._profiles = json.loads(self.profiles_file.read_text()).get("profiles", {})
        self._centroids: dict[str, dict[str, np.ndarray]] = {}  # model -> profile -> voiceprint
        # the training minimum can change while running, so whether a
        # clip may be assigned is worked out when asked, from its device's setting
        self.training_minimum: Callable[[str], float] = lambda device: 2.0
        self.measures = MeasureLog(data_dir / "measures")
        self.retrain = None   # retrain.Retrain, set at start: per-device voiceprints
        self.real_first = 5   # assistant_voice.real_clips_first: with this many heard clips, the made ones stop counting

    # ---------- saving clips ----------

    def save_clip(self, *, device: str, pcm: bytes, rate: int, width: int, channels: int,
                  transcript: str, audio_s: float, trainable: bool, model: str | None,
                  voiceprint: np.ndarray | None, result: dict, extra: dict | None = None) -> str:
        """extra: how it was heard (measures, heard_with, period, assistant_settings, shadow), kept with the clip."""
        now = datetime.now(timezone.utc)
        clip_id = now.strftime("%Y%m%d-%H%M%S-%f")[:-3] + "-" + device
        samples = to_float_mono(pcm, width, channels)
        with wave.open(str(self.clip_dir / f"{clip_id}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        meta = {
            "id": clip_id,
            "time": now.isoformat(timespec="seconds"),
            "device": device,
            "transcript": transcript,
            "audio_s": round(audio_s, 2),
            "trainable": trainable,
            "profile": None,
            "result": result,
            "voiceprints": {model: voiceprint.round(6).tolist()} if voiceprint is not None and model else {},
            **(extra or {}),
        }
        with self._lock:
            self._clips[clip_id] = meta
            self._write_meta(meta)
            self._prune()
        return clip_id

    def add_made_clip(self, name: str, pcm: bytes, rate: int, transcript: str, made: dict) -> str:
        """A clip made, not heard: a line said by an assistant's text-to-speech voice (made: its engine
        and voice), saved on that voice's profile. Its device is "tts"; it never waits on the Learn page."""
        now = datetime.now(timezone.utc)
        clip_id = now.strftime("%Y%m%d-%H%M%S-%f")[:-3] + "-tts"
        with wave.open(str(self.clip_dir / f"{clip_id}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        meta = {"id": clip_id, "time": now.isoformat(timespec="seconds"), "device": "tts",
                "transcript": transcript, "audio_s": round(len(pcm) / 2 / rate, 2), "trainable": True,
                "profile": name, "made": made, "result": {}, "voiceprints": {},
                "assigned": {"by": "oread", "kind": "made", "at": now.isoformat(timespec="seconds")}}
        with self._lock:
            self._get_profile(name)
            self._clips[clip_id] = meta
            self._write_meta(meta)
        return clip_id

    def _write_meta(self, meta: dict) -> None:
        tmp = self.clip_dir / f"{meta['id']}.json.tmp"
        tmp.write_text(json.dumps(meta))
        tmp.replace(self.clip_dir / f"{meta['id']}.json")

    def _prune(self) -> None:
        """The oldest unassigned clips past max_unassigned go; a clip kept for a mishearing stays."""
        unassigned = sorted(
            (c for c in self._clips.values() if c["profile"] is None and not c.get("kept_for")), key=lambda c: c["id"]
        )
        for clip in unassigned[: max(0, len(unassigned) - self.max_unassigned)]:
            self._delete_files(clip["id"])
            del self._clips[clip["id"]]

    def _delete_files(self, clip_id: str) -> None:
        for suffix in (".wav", ".json"):
            (self.clip_dir / f"{clip_id}{suffix}").unlink(missing_ok=True)

    # ---------- matching ----------

    def match(self, model: str, voiceprint: np.ndarray | None,
              unknown_below: float, match_above: float, overrides: dict | None = None,
              own_voice: bool = False) -> dict:
        """Best profile for a voiceprint, labelled known / maybe / unknown.
        overrides: a device's own voiceprints for some people, used in place of theirs.
        own_voice: the device hears its own speaker (the patch): the assistants' voices are matched
        too, and one of them, known, is marked own_voice. Off: they're left out."""
        if voiceprint is None:
            return {"label": "too short", "speaker": None, "guess": None, "score": None}
        with self._lock:
            centroids = {**self._centroids.get(model, {}), **(overrides or {})}
            assistants = self.assistant_names()
            if not own_voice:
                centroids = {n: c for n, c in centroids.items() if n not in assistants}
            scores = {name: float(np.dot(c, voiceprint)) for name, c in centroids.items()}
        result = label(scores, unknown_below, match_above)
        if result.get("speaker") in assistants:
            result["own_voice"] = True        # her own voice, through the device's own speaker
        return result

    def assistant_names(self) -> set[str]:
        """The profiles that are an assistant's own voice (kind: assistant), never a person."""
        with self._lock:
            return {n for n, info in self._profiles.items() if info.get("kind") == "assistant"}

    def centroids(self, model: str) -> dict[str, np.ndarray]:
        """Every person's voiceprint for a model (all devices together)."""
        with self._lock:
            return dict(self._centroids.get(model, {}))

    def voiced(self, model: str, device: str, person: str | None = None) -> list[dict]:
        """A device's clips that have a voiceprint for this model (only one person's, if named),
        each with its voiceprint as `vector`, oldest first."""
        with self._lock:
            out = [{**self._public(c), "vector": np.array(c["voiceprints"][model], dtype=np.float32)}
                   for c in self._clips.values()
                   if c["device"] == device and model in c["voiceprints"]
                   and (person is None or c["profile"] == person)]
        return sorted(out, key=lambda c: c["id"])

    def rebuild(self, model: str, voiceprint_of: Callable[[Path], np.ndarray | None],
                fresh: bool = False) -> None:
        """Recompute every profile's voiceprint for a model.

        Clips assigned under a different model get a voiceprint for this one
        from their saved audio, so switching models needs no re-enrollment.
        fresh: work every clip's voiceprint out again (the model's file changed).
        """
        with self._lock:
            members: dict[str, list[tuple[np.ndarray, bool]]] = {}
            for clip in self._clips.values():
                if clip["profile"] is None:
                    continue
                vec = None if fresh else clip["voiceprints"].get(model)
                if vec is None:
                    computed = voiceprint_of(self.clip_dir / f"{clip['id']}.wav")
                    if computed is None:
                        continue
                    clip["voiceprints"][model] = computed.round(6).tolist()
                    self._write_meta(clip)
                    vec = clip["voiceprints"][model]
                members.setdefault(clip["profile"], []).append((np.array(vec, dtype=np.float32), bool(clip.get("made"))))
            self._centroids[model] = {name: unit(np.mean(self._counted(pairs), axis=0)) for name, pairs in members.items()}

    # ---------- waiting clips and profiles ----------

    def clips(self, status: str = "unassigned", device: str | None = None,
              limit: int = 50, profile: str | None = None) -> list[dict]:
        with self._lock:
            chosen = [
                c for c in self._clips.values()
                if (status == "all"
                    or (status == "unassigned" and c["profile"] is None)
                    or (status == "assigned" and c["profile"] is not None))
                and (device is None or c["device"] == device)
                and (profile is None or c["profile"] == profile)
            ]
        chosen.sort(key=lambda c: c["id"], reverse=True)
        return [self._public(c) for c in chosen[:limit]]

    def clip(self, clip_id: str) -> dict:
        with self._lock:
            return self._public(self._get(clip_id))

    def audio_path(self, clip_id: str) -> Path:
        with self._lock:
            self._get(clip_id)
        return self.clip_dir / f"{clip_id}.wav"

    def assign(self, clip_id: str, name: str, by: dict | None = None) -> dict:
        """by: who assigned it ({"name", "kind": user or token}); a person's own choice
        (kind user) is what retraining learns from."""
        name = name.strip()
        with self._lock:
            clip = self._get(clip_id)
            minimum = self.training_minimum(clip["device"])
            if self._old_sound(clip):
                raise StoreError(
                    f"Heard before {clip['device']}'s last retrain, when it sounded different; "
                    "old sound isn't used for teaching (keep it or discard it)", 409)
            if clip["audio_s"] < minimum:
                raise StoreError(
                    f"Clip is {clip['audio_s']} s; training clips on {clip['device']} need at "
                    f"least {minimum} s (min_training_seconds)", 409)
            if name not in self._profiles:
                self.create_profile(name)
            old = clip["profile"]
            clip["profile"] = name
            clip["assigned"] = {"by": (by or {}).get("name"), "kind": (by or {}).get("kind"),
                                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self._write_meta(clip)
            self._refresh(name, old)
            return self._public(clip)

    def unassign(self, clip_id: str) -> dict:
        with self._lock:
            clip = self._get(clip_id)
            old, clip["profile"] = clip["profile"], None
            clip.pop("assigned", None)
            self._write_meta(clip)
            self._refresh(old)
            self._prune()
            return self._public(clip)

    def keep(self, clip_id: str, why: str) -> dict:
        """Keep a clip out of the review list's trimming (why: mishearing). Returns the clip."""
        with self._lock:
            clip = self._get(clip_id)
            if clip.get("kept_for") != why:
                clip["kept_for"] = why
                self._write_meta(clip)
            return self._public(clip)

    def discard(self, clip_id: str) -> None:
        with self._lock:
            clip = self._get(clip_id)
            self._delete_files(clip_id)
            del self._clips[clip_id]
            self._refresh(clip["profile"])

    def profiles(self, everyone: bool = True) -> list[dict]:
        """Each profile with its clips; everyone False: people only (no assistant's voice)."""
        assistants = self.assistant_names()
        with self._lock:
            out = []
            for name, info in sorted(self._profiles.items()):
                if not everyone and name in assistants:
                    continue
                members = [c for c in self._clips.values() if c["profile"] == name]
                by_device: dict[str, int] = {}
                for c in members:
                    by_device[c["device"]] = by_device.get(c["device"], 0) + 1
                out.append({"name": name, "created": info.get("created"), "kind": info.get("kind") or "person",
                            "clips": len(members), "clips_by_device": by_device,
                            "made": sum(1 for c in members if c.get("made")),
                            **({"voice": info["voice"]} if info.get("voice") else {}),
                            **({"sample": True} if info.get("sample") else {})})
            return out

    def create_profile(self, name: str, kind: str = "person", voice: dict | None = None,
                       sample: bool = False) -> dict:
        """kind: person, or assistant (an assistant's own voice, for a device that hears its own speaker);
        voice: the text-to-speech voice an assistant's profile was learned from; sample: one of the
        sample household's people (sample.py)."""
        name = name.strip()
        if kind not in ("person", "assistant"):
            raise StoreError("A profile is a person or an assistant's voice")
        if not _NAME.match(name):
            raise StoreError("Profile names are 1-40 letters, digits, spaces, or _ ' . -")
        with self._lock:
            if any(n.lower() == name.lower() for n in self._profiles):
                raise StoreError(f"Profile '{name}' already exists", 409)
            self._profiles[name] = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if sample:
                self._profiles[name]["sample"] = True
            if kind == "assistant":
                self._profiles[name]["kind"] = "assistant"
                if voice:
                    self._profiles[name]["voice"] = voice
            self._write_profiles()
            return {"name": name, "kind": kind, **self._profiles[name]}

    def rename_profile(self, name: str, new_name: str) -> dict:
        new_name = new_name.strip()
        if not _NAME.match(new_name):
            raise StoreError("Profile names are 1-40 letters, digits, spaces, or _ ' . -")
        with self._lock:
            if name not in self._profiles:
                raise StoreError(f"No profile named '{name}'", 404)
            if any(n.lower() == new_name.lower() and n != name for n in self._profiles):
                raise StoreError(f"Profile '{new_name}' already exists", 409)
            self._profiles[new_name] = self._profiles.pop(name)
            for clip in self._clips.values():
                if clip["profile"] == name:
                    clip["profile"] = new_name
                    self._write_meta(clip)
            for centroids in self._centroids.values():
                if name in centroids:
                    centroids[new_name] = centroids.pop(name)
            self._write_profiles()
            return {"name": new_name, **self._profiles[new_name]}

    def delete_profile(self, name: str) -> int:
        """Remove a profile; its clips go back to waiting."""
        with self._lock:
            if name not in self._profiles:
                raise StoreError(f"No profile named '{name}'", 404)
            returned = 0
            for clip in list(self._clips.values()):
                if clip["profile"] == name and clip.get("made"):    # made, never heard: gone with it
                    self._delete_files(clip["id"])
                    del self._clips[clip["id"]]
                elif clip["profile"] == name:
                    clip["profile"] = None
                    clip.pop("assigned", None)
                    self._write_meta(clip)
                    returned += 1
            del self._profiles[name]
            for centroids in self._centroids.values():
                centroids.pop(name, None)
            self._write_profiles()
            self._prune()
            return returned

    def remove_sample(self) -> dict:
        """Remove the sample household: its clips and its people, nothing else. A clip of yours
        assigned to a sample person goes back to waiting; a person of yours keeps their own clips."""
        with self._lock:
            clips = [c for c in self._clips.values() if c.get("sample")]
            touched = {c["profile"] for c in clips if c["profile"]}
            for clip in clips:
                self._delete_files(clip["id"])
                del self._clips[clip["id"]]
            people = sorted(n for n, info in self._profiles.items() if info.get("sample"))
            returned = sum(self.delete_profile(n) for n in people)
            self._refresh(*(touched - set(people)))
            return {"clips": len(clips), "people": people, "returned": returned}

    def rename_device(self, old: str, new: str) -> int:
        """Clips heard by a renamed device take its new name."""
        with self._lock:
            moved = 0
            for clip in self._clips.values():
                if clip["device"] == old:
                    clip["device"] = new
                    self._write_meta(clip)
                    moved += 1
            self.measures.rename_device(old, new)
            return moved

    def transcripts(self, name: str) -> list[str]:
        """Transcripts of every clip assigned to a profile."""
        with self._lock:
            if name not in self._profiles:
                raise StoreError(f"No profile named '{name}'", 404)
            return [c["transcript"] for c in self._clips.values() if c["profile"] == name]

    def assigned_transcripts(self) -> list[tuple[str, str, str]]:
        """(clip id, profile, transcript) for every assigned clip, for phrase habits."""
        with self._lock:
            return [(c["id"], c["profile"], c["transcript"])
                    for c in self._clips.values() if c["profile"] is not None]

    def counts(self) -> dict:
        with self._lock:
            assigned = sum(c["profile"] is not None for c in self._clips.values())
            return {"profiles": len(self._profiles), "assigned_clips": assigned,
                    "review_list": len(self._clips) - assigned,
                    "review_list_max": self.max_unassigned}

    # ---------- helpers ----------

    def _public(self, clip: dict) -> dict:
        """A clip as the API shows it: no voiceprints, trainable by today's setting, and old_sound
        when its device was retrained after it was heard."""
        out = {k: v for k, v in clip.items() if k != "voiceprints"}
        out["trainable"] = clip["audio_s"] >= self.training_minimum(clip["device"])
        out["old_sound"] = self._old_sound(clip)
        return out

    def _old_sound(self, clip: dict) -> bool:
        """Heard before its device's last accepted retrain: the device sounded different then."""
        period = self.retrain.period(clip["device"]) if self.retrain else None
        return bool(period and clip["time"] < period)

    def _get_profile(self, name: str) -> dict:
        if name not in self._profiles:
            raise StoreError(f"No profile named '{name}'", 404)
        return self._profiles[name]

    def _get(self, clip_id: str) -> dict:
        if clip_id not in self._clips:
            raise StoreError(f"No clip '{clip_id}'", 404)
        return self._clips[clip_id]

    def _refresh(self, *names: str | None) -> None:
        """Recompute the voiceprints of the named profiles for every model in use."""
        for model, centroids in self._centroids.items():
            for name in {n for n in names if n}:
                vectors = self._counted([(np.array(c["voiceprints"][model], dtype=np.float32), bool(c.get("made")))
                                         for c in self._clips.values()
                                         if c["profile"] == name and model in c["voiceprints"]])
                if vectors:
                    centroids[name] = unit(np.mean(vectors, axis=0))
                else:
                    centroids.pop(name, None)

    def _counted(self, pairs: list[tuple[np.ndarray, bool]]) -> list[np.ndarray]:
        """The voiceprints a profile's own is the mean of: (voiceprint, made) pairs. Clips made from her
        text-to-speech count until there are real_first heard ones (her voice through the device's speaker
        and the room); then the heard ones alone."""
        heard = [v for v, made in pairs if not made]
        if len(heard) >= self.real_first:
            return heard
        return [v for v, _ in pairs]

    def set_voice_devices(self, name: str, devices: list[str]) -> None:
        """The devices an assistant's learned voice is the voice of (the ones that answer in it)."""
        with self._lock:
            voice = self._get_profile(name).get("voice")
            if voice is not None and voice.get("devices") != sorted(devices):
                voice["devices"] = sorted(devices)
                self._write_profiles()

    def _write_profiles(self) -> None:
        tmp = self.profiles_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"profiles": self._profiles}, indent=2))
        tmp.replace(self.profiles_file)


def label(scores: dict[str, float], unknown_below: float, match_above: float) -> dict:
    """The best of some scores, labelled known / maybe / unknown, with every score."""
    if not scores:
        return {"label": "unknown", "speaker": None, "guess": None, "score": None}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    guess, best = ranked[0]
    score = round(best, 3)
    if score >= match_above:
        label_, speaker = "known", guess
    elif score >= unknown_below:
        label_, speaker = "maybe", None
    else:
        label_, speaker = "unknown", None
    return {"label": label_, "speaker": speaker, "guess": guess, "score": score,
            "by": "voice" if speaker else None,
            "close": [{"name": n, "score": round(v, 3)} for n, v in ranked[:3]],
            "scores": {n: round(v, 3) for n, v in ranked}}
