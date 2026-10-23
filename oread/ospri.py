"""OSPRI (Oread STT Pattern Recognition Improvement): in v1.0.0 it only gathers records and exports them.

While Gather records is on (the OSPRI page; data/ospri.yaml: gather), every request adds one record to
data/ospri/records.jsonl: when, the device, who spoke (the voice ID's label and score), the speech and
voice models, what was heard, how long, and the clip it was heard in. The records aren't the review
list's clips: they stay when a clip is trimmed. An export joins in what was meant, from the mishearings
pulled from the house router (by the clip, else by the words heard), so each record says whether it was
misheard and what was really said. The analysis, and corrections fed back from it, come in a later version.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from pathlib import Path

import yaml

from . import metrics
from .mishearings import key

_LOG = logging.getLogger("oread.ospri")
FIELDS = ("time", "device", "speaker", "label", "score", "guess", "by", "stt_model", "voice_model",
          "heard", "audio_s", "speech_s", "clip")
EXPORT_FIELDS = FIELDS + ("misheard", "meant")


class Records:
    def __init__(self, data_dir: Path) -> None:
        self.settings_file = data_dir / "ospri.yaml"
        self.file = data_dir / "ospri" / "records.jsonl"
        self._lock = threading.Lock()
        self.gather = bool(self._settings().get("gather", False))
        metrics.LISTENERS.append(self.note)

    def _settings(self) -> dict:
        try:
            return yaml.safe_load(self.settings_file.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def set_gather(self, on: bool) -> dict:
        self.gather = bool(on)
        self.settings_file.write_text("# OSPRI: gather a record of every request (the OSPRI page)\n"
                                      f"gather: {'true' if self.gather else 'false'}\n")
        return self.view()

    @staticmethod
    def record(fields: dict) -> dict:
        """A request's fields (as metrics writes them) as one record."""
        return {"time": fields.get("time"), "device": fields.get("device"), "speaker": fields.get("speaker"),
                "label": fields.get("label"), "score": fields.get("score"), "guess": fields.get("guess"),
                "by": fields.get("by"), "stt_model": fields.get("model"), "voice_model": fields.get("speaker_model"),
                "heard": fields.get("text") or "", "audio_s": fields.get("audio_s"), "speech_s": fields.get("speech_s"),
                "clip": fields.get("clip")}

    def note(self, fields: dict) -> None:
        """Each finished request (metrics.LISTENERS), while gathering."""
        if not self.gather or fields.get("error") or fields.get("sample"):
            return
        line = json.dumps(self.record(fields)) + "\n"
        with self._lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("a") as f:
                f.write(line)

    def _rows(self) -> list[dict]:
        with self._lock:
            try:
                lines = self.file.read_text().splitlines()
            except OSError:
                return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def view(self) -> dict:
        rows = self._rows()
        size = self.file.stat().st_size if self.file.exists() else 0
        return {"gather": self.gather, "records": len(rows), "first": rows[0]["time"] if rows else None,
                "last": rows[-1]["time"] if rows else None, "bytes": size, "file": "data/ospri/records.jsonl"}

    def export(self, lines: list[dict]) -> list[dict]:
        """Every record with misheard (yes, or no) and meant, joined in from the mishearings pulled:
        by the clip it was heard in, else by the words heard (capitals and punctuation aside)."""
        by_clip, by_words = {}, {}
        for line in lines:
            if not line.get("meant") or line.get("gone"):
                continue
            by_words.setdefault(key(line.get("said")), line["meant"])
            for c in line.get("clips") or []:
                by_clip.setdefault(c.get("clip"), line["meant"])
        out = []
        for r in self._rows():
            meant = by_clip.get(r.get("clip")) or by_words.get(key(r.get("heard")))
            out.append({**r, "misheard": "yes" if meant else "no", "meant": meant or ""})
        return out

    @staticmethod
    def csv(rows: list[dict]) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()
