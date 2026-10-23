"""Retraining one person's voice on one device (People, Retrain).

A device's sound can change (a mic's gain, a noise gate, an app's settings) while the person
doesn't. Every person's voiceprint is the average of all their clips from every device, so one
device's new sound is judged against mostly old sound. Retraining gives that device its own
voiceprint for the person, made only from clips a person picks (assigned by hand, heard after
the change). Nothing else changes: the voice model, the thresholds, the saved clips and the
call each clip got when it was heard.

The steps:
    retrain  the ticked clips make a trial voiceprint (pending). Live requests on the device
             note what the trial would have said (the clip's `shadow`); today's call decides.
    blind    the device's clips, whoever they're assigned to, scored with the trial.
    accept   the trial decides on that device from now on, and starts a new settings period
             there; clips assigned to the person from the device afterwards join it, and a
             clip taken back leaves it.
    reject   the trial is dropped; nothing is kept.
Retraining the same person on the same device again starts over.

A clip's score against a voiceprint made with that same clip is flattering, so a clip that's
part of a voiceprint is always scored against the voiceprint made without it.

Saved in data/device_profiles.json.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .errors import OreadError
from .speaker import unit
from .store import Store, label


_BULKY = ("vector", "measures", "assistant_settings", "ha", "heard_with")   # not needed on the page


class RetrainError(OreadError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def by_hand(clip: dict) -> bool:
    """Assigned by a person (clips assigned before this was recorded count: only people did then)."""
    return (clip.get("assigned") or {}).get("kind") in (None, "user")


class Retrain:
    def __init__(self, store: Store, path: Path) -> None:
        self.store = store
        self.path = path
        self._lock = threading.RLock()
        self._data = {"accepted": {}, "pending": {}, "periods": {}}
        if path.exists():
            self._data.update(json.loads(path.read_text()))

    # ---------- the voiceprints ----------

    def _record(self, state: str, device: str, person: str) -> dict | None:
        return (self._data[state].get(device) or {}).get(person)

    def _members(self, rec: dict, clips: list[dict], accepted: bool) -> list[dict]:
        """The clips a record is made of: the ticked ones, and once accepted, the person's
        clips the device heard from then on, assigned by hand. Taken-back clips are gone from `clips`."""
        ticked = set(rec["clips"])
        return [c for c in clips if by_hand(c) and
                (c["id"] in ticked or (accepted and c["time"] >= rec["at"]))]

    def voiceprint(self, device: str, person: str, model: str, state: str = "accepted",
                   leave_out: str | None = None) -> np.ndarray | None:
        with self._lock:
            rec = self._record(state, device, person)
        if rec is None or rec["model"] != model:
            return None
        members = self._members(rec, self.store.voiced(model, device, person), state == "accepted")
        vectors = [c["vector"] for c in members if c["id"] != leave_out]
        return unit(np.mean(vectors, axis=0)) if vectors else None

    def overrides(self, device: str, model: str, trial: bool = False) -> dict[str, np.ndarray]:
        """The device's own voiceprints for this model (with trial: pending ones on top)."""
        with self._lock:
            people = list((self._data["accepted"].get(device) or {}))
            pending = list((self._data["pending"].get(device) or {})) if trial else []
        out = {}
        for state, names in (("accepted", people), ("pending", pending)):
            for person in names:
                vec = self.voiceprint(device, person, model, state)
                if vec is not None:
                    out[person] = vec
        return out

    def has_trial(self, device: str, model: str) -> bool:
        with self._lock:
            return any(r["model"] == model for r in (self._data["pending"].get(device) or {}).values())

    def period(self, device: str) -> str | None:
        """When the device's current settings period began (its last accepted retrain)."""
        with self._lock:
            periods = self._data["periods"].get(device) or []
            return periods[-1]["at"] if periods else None

    # ---------- the Retrain page ----------

    def view(self, device: str, person: str, model: str) -> dict:
        """The person's clips on the device: the call each got when heard (original, never
        changed), and its score now with the device's own voiceprint (new: accepted only)
        and with the trial (trial: while one is pending)."""
        clips = self.store.voiced(model, device, person)
        with self._lock:
            accepted = self._record("accepted", device, person)
            pending = self._record("pending", device, person)
        rows = []
        for c in clips:
            row = {k: v for k, v in c.items() if k not in _BULKY}
            row["hand"] = by_hand(c)
            for key, state, rec in (("new_score", "accepted", accepted), ("trial_score", "pending", pending)):
                vec = None
                if rec is not None and rec["model"] == model:
                    vec = self.voiceprint(device, person, model, state, leave_out=c["id"])
                row[key] = round(float(np.dot(vec, c["vector"])), 3) if vec is not None else None
            row["in_accepted"] = accepted is not None and any(
                m["id"] == c["id"] for m in self._members(accepted, [c], True))
            row["in_trial"] = pending is not None and c["id"] in pending["clips"]
            rows.append(row)
        return {"device": device, "person": person, "model": model, "clips": rows[::-1],
                "accepted": accepted, "pending": pending, "period": self.period(device),
                "waiting": self.waiting(device, person, model), "assistants": sorted(self.store.assistant_names())}

    def waiting(self, device: str, person: str, model: str, most: int = 100) -> list[dict]:
        """The device's clips nobody is assigned to, closest to the person first (dev-oread #6): each with the
        call it got when heard, the two closest voices now (the device's voiceprints as today, the assistants'
        own voices among them) and the person's own score, so they can be assigned without leaving Retrain.
        A voice like an assistant's (Nora and Wren's) shows up here either way."""
        today = {**self.store.centroids(model), **self.overrides(device, model)}
        rows = []
        for c in self.store.voiced(model, device):
            if c["profile"] is not None:
                continue
            scores = sorted(((n, float(np.dot(v, c["vector"]))) for n, v in today.items()), key=lambda x: -x[1])
            row = {k: v for k, v in c.items() if k not in _BULKY}
            row["closest"] = [{"name": n, "score": round(s, 3)} for n, s in scores[:2]]
            row["person_score"] = round(dict(scores)[person], 3) if person in dict(scores) else None
            rows.append(row)
        rows.sort(key=lambda r: -1.0 if r["person_score"] is None else -r["person_score"])
        return rows[:most]

    def start(self, device: str, person: str, model: str, clip_ids: list[str], why: str | None,
              who: str | None) -> dict:
        """A trial voiceprint from the ticked clips (replacing any trial already pending)."""
        clips = {c["id"]: c for c in self.store.voiced(model, device, person)}
        wrong = [i for i in clip_ids if i not in clips]
        if wrong:
            raise RetrainError(f"Not {person}'s clips on {device} with a {model} voiceprint: "
                               + ", ".join(wrong[:5]), 409)
        not_hand = [i for i in clip_ids if not by_hand(clips[i])]
        if not_hand:
            raise RetrainError("Only clips a person assigned can retrain a voice: " + ", ".join(not_hand[:5]), 409)
        if not clip_ids:
            raise RetrainError("Tick at least one clip")
        rec = {"model": model, "clips": sorted(set(clip_ids)), "why": (why or "").strip()[:500],
               "by": who, "at": now()}
        with self._lock:
            self._data["pending"].setdefault(device, {})[person] = rec
            self._save()
        return rec

    def blind(self, device: str, person: str, model: str, unknown_below: float,
              match_above: float) -> dict:
        """Every clip the device heard, scored as today (the device's accepted voiceprints) and
        with the trial: who each would name, next to who it's assigned to. Counted apart for the
        clips heard since the oldest ticked one (the new sound) and before it (the old sound,
        which a trial for the new sound is expected to lose)."""
        with self._lock:
            pending = self._record("pending", device, person)
        if pending is None or pending["model"] != model:
            raise RetrainError(f"No trial for {person} on {device}; retrain first", 404)
        base = self.store.centroids(model)
        today = {**base, **self.overrides(device, model)}
        trial = {**today, **self.overrides(device, model, trial=True)}
        voiced = self.store.voiced(model, device)
        since = min((c["time"] for c in voiced if c["id"] in pending["clips"]), default=pending["at"])
        rows, theirs_scores = [], []
        counts = {when: {f"{group}_{call}": 0 for group in ("theirs", "others", "waiting")
                         for call in ("all", "today", "trial")} for when in ("since", "before")}
        for c in voiced:
            mine = dict(trial)
            if c["id"] in pending["clips"]:   # never scored against a voiceprint made with itself
                vec = self.voiceprint(device, person, model, "pending", leave_out=c["id"])
                if vec is None:
                    mine.pop(person, None)
                else:
                    mine[person] = vec
            now_call = label({n: float(np.dot(v, c["vector"])) for n, v in today.items()}, unknown_below, match_above)
            new_call = label({n: float(np.dot(v, c["vector"])) for n, v in mine.items()}, unknown_below, match_above)
            row = {k: v for k, v in c.items() if k not in _BULKY}
            row["today"] = {k: now_call.get(k) for k in ("label", "speaker", "guess", "score")}
            row["trial"] = {k: new_call.get(k) for k in ("label", "speaker", "guess", "score")}
            row["today"]["person_score"] = now_call.get("scores", {}).get(person)
            row["trial"]["person_score"] = new_call.get("scores", {}).get(person)
            rows.append(row)
            group = "theirs" if c["profile"] == person else ("waiting" if c["profile"] is None else "others")
            tally = counts["since" if c["time"] >= since else "before"]
            tally[f"{group}_all"] += 1
            tally[f"{group}_today"] += now_call.get("speaker") == person
            tally[f"{group}_trial"] += new_call.get("speaker") == person
            if group == "theirs" and c["time"] >= since:
                theirs_scores.append((row["today"]["person_score"], row["trial"]["person_score"]))
        return {"device": device, "person": person, "model": model, "counts": counts, "since": since,
                "verdict": verdict(counts["since"], theirs_scores),
                "clips": rows[::-1], "pending": pending}

    def accept(self, device: str, person: str, who: str | None) -> dict:
        with self._lock:
            rec = self._record("pending", device, person)
            if rec is None:
                raise RetrainError(f"No trial for {person} on {device} to accept", 404)
            del self._data["pending"][device][person]
            rec = {**rec, "started": rec["at"], "accepted_by": who, "at": now()}
            self._data["accepted"].setdefault(device, {})[person] = rec
            self._data["periods"].setdefault(device, []).append(
                {"at": rec["at"], "person": person, "why": rec["why"]})
            self._save()
            return rec

    def reject(self, device: str, person: str) -> None:
        with self._lock:
            if self._record("pending", device, person) is None:
                raise RetrainError(f"No trial for {person} on {device}", 404)
            del self._data["pending"][device][person]
            self._save()

    # ---------- keeping up with renames ----------

    def rename_person(self, old: str, new: str) -> None:
        with self._lock:
            for state in ("accepted", "pending"):
                for people in self._data[state].values():
                    if old in people:
                        people[new] = people.pop(old)
            self._save()

    def forget_person(self, name: str) -> None:
        with self._lock:
            for state in ("accepted", "pending"):
                for people in self._data[state].values():
                    people.pop(name, None)
            self._save()

    def rename_device(self, old: str, new: str) -> None:
        with self._lock:
            for state in ("accepted", "pending", "periods"):
                if old in self._data[state]:
                    self._data[state][new] = self._data[state].pop(old)
            self._save()

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)


FLAT = 0.02   # a score that moves less than this hasn't changed


def verdict(since: dict, scores: list[tuple]) -> dict:
    """Is the trial better or worse, judged on the new sound only (clips since the oldest ticked one;
    the old sound is expected to be lost). Better: more of the person's own clips named and no more
    of other people's named as them. Worse: fewer of their own, or more of other people's. Both the
    same: their average score decides (up, down, or no change). Anything else is mixed."""
    pairs = [(a, b) for a, b in scores if a is not None and b is not None]
    today = round(sum(a for a, _ in pairs) / len(pairs), 3) if pairs else None
    trial = round(sum(b for _, b in pairs) / len(pairs), 3) if pairs else None
    own = since["theirs_trial"] - since["theirs_today"]
    wrong = since["others_trial"] - since["others_today"]
    if own > 0 and wrong <= 0:
        word = "better"
    elif own < 0 or wrong > 0:
        word = "worse" if own <= 0 else "mixed"
    elif today is None or abs(trial - today) < FLAT:
        word = "no change"
    else:
        word = "better" if trial > today else "worse"
    return {"verdict": word, "average_today": today, "average_trial": trial, "clips": len(pairs)}
