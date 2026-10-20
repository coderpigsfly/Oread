#!/usr/bin/env python3
"""OSPRI in v1.0.0: gathering a record of each request, and the export with what was meant joined in.
A throwaway folder; calls nothing outside. Run from the folder:  python3 tests/ospri_test.py"""

import csv
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oread import metrics  # noqa: E402
from oread.ospri import EXPORT_FIELDS, Records  # noqa: E402

FAILED = []


def case(name, got, want):
    if got != want:
        FAILED.append(name)
        print(f"FAIL  {name}\n        got:  {got!r}\n        want: {want!r}")
    else:
        print(f"PASS  {name}")


def request(clip, text, **more):
    return {"time": "2026-10-20T12:00:00+00:00", "device": "voice-pe", "text": text, "model": "parakeet", "speaker_model": "titanet",
            "speaker": "Ann", "label": "known", "guess": "Ann", "score": 0.71, "by": "voice", "audio_s": 2.4, "speech_s": 2.1,
            "clip": clip, "steps_ms": {"stt": 900}, **more}


tmp = Path(tempfile.mkdtemp(prefix="oread-ospri-"))
rec = Records(tmp)
metrics.LISTENERS.remove(rec.note)
case("Off to start with: nothing gathered", (rec.view()["gather"], rec.note(request("c0", "Hello")), rec.view()["records"]), (False, None, 0))
case("Switched on, and kept", (rec.set_gather(True)["gather"], Records(tmp).gather), (True, True))
metrics.LISTENERS.remove(metrics.LISTENERS[-1])
rec.note(request("c1", "Is the watch a runny?"))
rec.note(request("c2", "Read me my cat listen."))
rec.note(request("c3", "Good morning", speaker=None, label="unknown"))
rec.note(request("c4", "", error="Transcription failed"))
v = rec.view()
case("A record per request (a failed one left out), with its dates and size",
     (v["records"], v["first"], v["bytes"] > 0), (3, "2026-10-20T12:00:00+00:00", True))
case("A record's fields", json.loads((tmp / "ospri" / "records.jsonl").read_text().splitlines()[0]),
     {"time": "2026-10-20T12:00:00+00:00", "device": "voice-pe", "speaker": "Ann", "label": "known", "score": 0.71, "guess": "Ann",
      "by": "voice", "stt_model": "parakeet", "voice_model": "titanet", "heard": "Is the watch a runny?", "audio_s": 2.4,
      "speech_s": 2.1, "clip": "c1"})
lines = [{"said": "Is the watch a runny?", "meant": "Is the washer running?", "clips": [{"clip": "c1"}]},
         {"said": "read me my cat listen", "meant": "Read me my task list.", "clips": []},
         {"said": "Good morning", "meant": None, "clips": [{"clip": "c3"}]}]
out = rec.export(lines)
case("The export joins in what was meant: by the clip, else by the words heard; no meaning given: not misheard",
     [(r["clip"], r["misheard"], r["meant"]) for r in out],
     [("c1", "yes", "Is the washer running?"), ("c2", "yes", "Read me my task list."), ("c3", "no", "")])
rows = list(csv.DictReader(io.StringIO(rec.csv(out))))
case("CSV: every field, a row per record", (tuple(rows[0].keys()), len(rows), rows[0]["meant"]), (EXPORT_FIELDS, 3, "Is the washer running?"))
rec.set_gather(False)
rec.note(request("c5", "Stopped"))
case("Switched off: nothing more gathered, the records kept", rec.view()["records"], 3)

print(f"\n{'all pass' if not FAILED else str(len(FAILED)) + ' fail'}")
sys.exit(1 if FAILED else 0)
