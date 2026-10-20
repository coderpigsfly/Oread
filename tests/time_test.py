#!/usr/bin/env python3
"""OSPRI build 1 (oread4): Stats, where the time goes. A throwaway folder; calls nothing outside.
Run from the folder:  python3 tests/time_test.py"""

import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oread import metrics  # noqa: E402
from oread.timing import STEPS, TimeLog, steps_of  # noqa: E402

FAILED = []


def case(name, got, want):
    if got != want:
        FAILED.append(name)
        print(f"FAIL  {name}\n        got:  {got!r}\n        want: {want!r}")
    else:
        print(f"PASS  {name}")


case("The steps, in order", STEPS, ("speaking", "time_in", "stt", "voice_beyond", "ospri", "time_out"))
case("A request's steps: voice ID counts only past speech to text; out is matching, saving, Home Assistant, the reply",
     steps_of({"receive": 3550.9, "queue": 0.0, "sound": 20.5, "voiceprint": 284.1, "stt": 1115.0, "stt+voiceprint": 1116.4,
               "match+save": 28.7, "publish": 5.0, "reply": 0.5}),
     [3550.9, 0.0, 1115.0, 1.4000000000000909, None, 34.2])
case("Before Oct 18 only the two together were timed: all of it is speech to text, nothing beyond",
     steps_of({"receive": 2000, "queue": 3, "stt+voiceprint": 900, "match+save": 20, "reply": 1}), [2000.0, 3.0, 900.0, None, None, 21.0])


def at(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat(timespec="seconds")


tmp = Path(tempfile.mkdtemp(prefix="oread-time-"))
reqs = [  # Mon Oct 19 2026 in New York: 23:30 there is 03:30 the next day in UTC
    {"time": at("2026-10-19T23:30:00-04:00"), "device": "voice-pe", "steps_ms": {"receive": 3000, "queue": 0, "stt": 1000, "stt+voiceprint": 1010, "match+save": 30, "reply": 1}},
    {"time": at("2026-10-19T08:00:00-04:00"), "device": "tablet", "steps_ms": {"receive": 2000, "queue": 10, "stt": 2000, "stt+voiceprint": 2004, "match+save": 40, "reply": 1}},
    {"time": at("2026-10-18T12:00:00-04:00"), "device": "voice-pe", "steps_ms": {"receive": 1000, "queue": 0, "stt": 500, "stt+voiceprint": 505, "match+save": 20, "reply": 1}},
    {"time": at("2026-09-30T12:00:00-04:00"), "device": "voice-pe", "steps_ms": {"receive": 1000, "queue": 0, "stt": 700, "stt+voiceprint": 700, "match+save": 20, "reply": 1}},
    {"bad": "line"},
]
(tmp / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reqs) + "not json\n")
log = TimeLog(tmp)
case("The first start fills the steps from the request log (lines it can't read left out)",
     len((tmp / "time-steps.jsonl").read_text().splitlines()), 4)

now = datetime.fromisoformat("2026-10-20T00:10:00-04:00").timestamp()      # Tuesday, just after midnight in New York
r = log.report("America/New_York", now=now)
case("Days are the household's: 23:30 Monday in New York is Monday, though it's Tuesday in UTC",
     [(b["label"], b["count"]) for b in r["day"][:3]], [("Tue Oct 20", 0), ("Mon Oct 19", 2), ("Sun Oct 18", 1)])
case("Weeks from Monday; months by the calendar",
     ([(b["label"], b["count"]) for b in r["week"][:2]], [(b["label"], b["count"]) for b in r["month"][:2]]),
     ([("Week of Oct 19", 2), ("Week of Oct 12", 1)], [("October 2026", 3), ("September 2026", 1)]))
mon = r["day"][1]
case("A period: each step's median, slowest 5 percent and average, all devices and each",
     (mon["stt"], mon["time_out"]["median"], sorted(mon["by_device"]), mon["by_device"]["voice-pe"]["count"], "ospri" in mon),
     ({"median": 1500, "p95": 1000, "average": 1500}, 36, ["tablet", "voice-pe"], 1, False))
case("The last 24 hours", (r["last_24_hours"][0]["label"], r["last_24_hours"][0]["count"]), ("Last 24 hours", 2))
case("In UTC, Monday's late request is Tuesday's", [b["count"] for b in log.report("UTC", now=now)["day"][:2]], [1, 1])
case("A time zone that isn't one: the server's", log.report("Not/AZone", now=now)["time_zone"], "the server's")

metrics.LISTENERS.remove(log.note)
log.note({"time": "2026-10-21T10:00:00+00:00", "device": "laptop",
          "steps_ms": {"receive": 900, "queue": 0, "stt": 300, "stt+voiceprint": 301, "match+save": 10, "reply": 1}})
case("Each finished request adds its line", json.loads((tmp / "time-steps.jsonl").read_text().splitlines()[-1])["d"], "laptop")
log.keep_days = 1
log._trim(now=datetime.fromisoformat("2026-10-21T12:00:00+00:00").timestamp())
case("Kept for keep_days: older lines go", [json.loads(x)["d"] for x in (tmp / "time-steps.jsonl").read_text().splitlines()], ["laptop"])
case("A report is quick", (lambda t0: (log.report("America/New_York"), time.perf_counter() - t0 < 1)[1])(time.perf_counter()), True)

print(f"\n{'all pass' if not FAILED else str(len(FAILED)) + ' fail'}")
sys.exit(1 if FAILED else 0)
