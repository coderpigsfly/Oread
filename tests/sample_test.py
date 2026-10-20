#!/usr/bin/env python3
"""The sample household's removal: its clips, its people and its log lines go, nothing of yours.
A throwaway folder; no models, calls nothing outside. Run from the folder:  python3 tests/sample_test.py
(Adding runs the real models: the page tests add and remove it.)"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oread import metrics  # noqa: E402
from oread.store import Store  # noqa: E402
from oread.timing import TimeLog  # noqa: E402

FAILED = []


def case(name, got, want):
    if got != want:
        FAILED.append(name)
        print(f"FAIL  {name}\n        got:  {got!r}\n        want: {want!r}")
    else:
        print(f"PASS  {name}")


tmp = Path(tempfile.mkdtemp(prefix="oread-sample-"))
store = Store(tmp / "data")
store.training_minimum = lambda device: 0.5


def heard(sample=False, x=1.0):
    vec = np.array([x, 1 - x, 0], dtype=np.float32)
    return store.save_clip(device="voice-pe", pcm=b"\0\0" * 16000, rate=16000, width=2, channels=1, transcript="hello",
                           audio_s=1.0, trainable=True, model="m", voiceprint=vec,
                           result={"label": "unknown", "speaker": None, "guess": None, "score": None},
                           extra={"sample": True} if sample else None)


store._centroids["m"] = {}
mine = heard()
store.assign(mine, "Kim")                                # a person of yours
store.create_profile("Sample Ada", sample=True)
taught = heard(sample=True, x=0.0)
store.assign(taught, "Sample Ada")
waiting = heard(sample=True)                             # a sample clip you assigned to Kim
store.assign(waiting, "Kim")
yours_on_sample = heard()                                # a clip of yours assigned to a sample person
store.assign(yours_on_sample, "Sample Ada")
case("Sample people show as such", {p["name"]: p.get("sample", False) for p in store.profiles()},
     {"Kim": False, "Sample Ada": True})

logs = tmp / "logs"
logs.mkdir()
lines = [{"time": "2026-10-20T12:00:00+00:00", "device": "voice-pe", "steps_ms": {"stt": 1}},
         {"time": "2026-10-20T12:01:00+00:00", "device": "voice-pe", "steps_ms": {"stt": 1}, "sample": True}]
(logs / "requests.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines) + '{"cut short\n')
times = TimeLog(logs, 400)
metrics.LISTENERS.remove(times.note)
case("Time steps keep the sample mark", [r.get("sample", False) for r in times._rows()], [False, True])
store.measures.add("voice-pe", {"clip": mine})
store.measures.add("voice-pe", {"clip": taught, "sample": True})

gone = store.remove_sample()
case("Removed: the sample's clips and people; your clip on a sample person goes back to waiting",
     gone, {"clips": 2, "people": ["Sample Ada"], "returned": 1})
case("Kept: your person, with only your clips",
     ({c["id"]: c["profile"] for c in store.clips("all")}, [p["name"] for p in store.profiles()]),
     ({mine: "Kim", yours_on_sample: None}, ["Kim"]))
case("Kim's voiceprint is worked out again without the sample's clip",
     store.centroids("m")["Kim"].round(3).tolist(), [1.0, 0.0, 0.0])
case("The log lines: the sample's go, yours and a line cut short stay",
     (metrics.forget_sample(logs), store.measures.forget_sample(), times.forget_sample(),
      (logs / "requests.jsonl").read_text().count("\n"), len(store.measures.read("voice-pe")), len(times._rows())),
     (1, 1, 1, 2, 1, 1))
case("Nothing more to remove the second time", store.remove_sample(), {"clips": 0, "people": [], "returned": 0})

manifest = yaml.safe_load((Path(__file__).resolve().parent.parent / "sample" / "sample.yaml").read_text())
folder = Path(__file__).resolve().parent.parent / "sample" / "clips"
case("The shipped sample: every clip's file is there, 12 taught and 8 waiting, two people",
     (all((folder / c["file"]).is_file() for c in manifest["clips"]),
      sum(c["role"] == "teach" for c in manifest["clips"]), sum(c["role"] == "waiting" for c in manifest["clips"]),
      sorted({c["person"] for c in manifest["clips"] if c["person"]})),
     (True, 12, 8, ["Sample Ada", "Sample Ben"]))

print(f"\n{len(FAILED)} fail" if FAILED else "\nall pass")
sys.exit(1 if FAILED else 0)
