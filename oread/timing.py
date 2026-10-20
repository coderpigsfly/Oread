"""Where the time goes: each request's time split into its steps, kept by day for the Stats page.

The steps, in the order a request goes through them:
    speaking     the audio arriving from the device (the person talking: not Oread's time)
    time_in      waiting in line for a free slot (server.max_concurrent): Oread's own
    stt          speech to text (the speech model's own time)
    voice_beyond voice ID's time past speech to text (they run side by side; only the extra counts)
    ospri        OSPRI: applying the correction parameters (none until it's built: no value)
    time_out     matching the voice, saving the clip, telling Home Assistant, the reply: Oread's own

Each request adds one short line to logs/time-steps.jsonl (time, device, the six steps), kept for
stats.keep_days, so a week or a month is told from every request in it, not from a summary. The
first start fills it from logs/requests.jsonl. The page asks with its own time zone, so a day is the
household's day.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import metrics

_LOG = logging.getLogger("oread.timing")
STEPS = ("speaking", "time_in", "stt", "voice_beyond", "ospri", "time_out")
PERIODS = {"day": 14, "week": 8, "month": 12}      # how many of each the page shows


def steps_of(steps_ms: dict) -> list[float | None]:
    """A request's steps_ms (as handler.py times them) as the six steps, in STEPS order."""
    s = {k: float(v) for k, v in (steps_ms or {}).items() if isinstance(v, (int, float))}
    both = s.get("stt+voiceprint")
    stt = s.get("stt", both)          # before Oct 18 only the two together were timed: all of it counts as speech to text
    beyond = max(0.0, both - stt) if both is not None and "stt" in s else None
    out_parts = [s[k] for k in ("match+save", "publish", "reply") if k in s]
    return [s.get("receive"), s.get("queue"), stt, beyond, s.get("ospri"),
            round(sum(out_parts), 1) if out_parts else None]


class TimeLog:
    def __init__(self, logs: Path, keep_days: int = 400) -> None:
        self.file = logs / "time-steps.jsonl"
        self.keep_days = keep_days
        self._lock = threading.Lock()
        self._writes = 0
        if not self.file.exists():
            self._fill(logs / "requests.jsonl")
        metrics.LISTENERS.append(self.note)

    def _fill(self, requests: Path) -> None:
        """The first start: every request still in requests.jsonl."""
        rows = []
        try:
            for line in requests.read_text().splitlines():
                try:
                    rows.append(self._row(json.loads(line)))
                except ValueError:
                    continue                     # a line cut short: left out
            self.file.write_text("".join(json.dumps(r) + "\n" for r in rows if r))
        except OSError as err:
            _LOG.warning("Couldn't fill %s from %s: %s", self.file.name, requests.name, err)

    @staticmethod
    def _row(fields: dict) -> dict | None:
        try:
            t = datetime.fromisoformat(fields["time"]).timestamp()
        except (KeyError, ValueError, TypeError):
            return None
        return {"t": round(t), "d": fields.get("device") or "?", "s": steps_of(fields.get("steps_ms")),
                **({"sample": True} if fields.get("sample") else {})}

    def note(self, fields: dict) -> None:
        """Each finished request (metrics.LISTENERS)."""
        row = self._row(fields)
        if not row:
            return
        with self._lock:
            with self.file.open("a") as f:
                f.write(json.dumps(row) + "\n")
            self._writes += 1
            if self._writes % 500 == 1:
                self._trim()

    def forget_sample(self) -> int:
        """The sample household's lines out of time-steps.jsonl."""
        with self._lock:
            return metrics.drop_sample_lines(self.file)

    def _trim(self, now: float | None = None) -> None:
        cutoff = (now or time.time()) - self.keep_days * 86400
        rows = self._rows()
        kept = [r for r in rows if r["t"] >= cutoff]
        if len(kept) < len(rows):
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(r) + "\n" for r in kept))
            tmp.replace(self.file)

    def _rows(self) -> list[dict]:
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

    def report(self, tz: str | None = None, now: float | None = None) -> dict:
        """The last 24 hours, and by day, week and month (in the time zone tz, an IANA name like
        America/New_York; else the server's): each with its count and each step's median, slowest
        5 percent and average, all together and per device."""
        try:
            zone = ZoneInfo(tz) if tz else None
        except (ZoneInfoNotFoundError, ValueError):
            zone = None
        now = now or time.time()
        with self._lock:
            rows = self._rows()
        local = datetime.fromtimestamp(now, zone) if zone else datetime.fromtimestamp(now).astimezone()
        out = {"steps": list(STEPS), "time_zone": str(zone) if zone else "the server's", "keep_days": self.keep_days,
               "last_24_hours": [_bucket("Last 24 hours", [r for r in rows if r["t"] >= now - 86400])]}
        for period, many in PERIODS.items():
            starts = _starts(local, period, many)
            buckets = []
            for i, (label, start) in enumerate(starts):
                end = starts[i - 1][1] if i else now + 1
                buckets.append(_bucket(label, [r for r in rows if start <= r["t"] < end]))
            out[period] = buckets
        return out


def _starts(local: datetime, period: str, many: int) -> list[tuple[str, float]]:
    """The newest first: (label, start as a timestamp) of the last `many` days, weeks (from Monday) or months."""
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for i in range(many):
        if period == "day":
            start = _midnight(day - timedelta(days=i))
            label = start.strftime("%a %b %d").replace(" 0", " ")
        elif period == "week":
            start = _midnight(day - timedelta(days=day.weekday() + 7 * i))
            label = "Week of " + start.strftime("%b %d").replace(" 0", " ")
        else:
            y, m = divmod(day.year * 12 + day.month - 1 - i, 12)
            start = _midnight(day.replace(year=y, month=m + 1, day=1))
            label = start.strftime("%B %Y")
        out.append((label, start.timestamp()))
    return out


def _midnight(d: datetime) -> datetime:
    """Midnight of that date in its own zone (a day across a clock change still starts at midnight)."""
    return d.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)


def _bucket(label: str, rows: list[dict]) -> dict:
    def summary(rs: list[dict]) -> dict:
        out = {"count": len(rs)}
        for i, step in enumerate(STEPS):
            values = sorted(r["s"][i] for r in rs if r["s"][i] is not None)
            if values:
                out[step] = {"median": round(statistics.median(values)), "p95": round(values[int(0.95 * (len(values) - 1))]),
                             "average": round(sum(values) / len(values))}
        return out
    by_device: dict[str, list] = {}
    for r in rows:
        by_device.setdefault(r["d"], []).append(r)
    return {"label": label, **summary(rows), "by_device": {d: summary(rs) for d, rs in sorted(by_device.items())}}
