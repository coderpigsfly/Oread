"""What Oread costs to run: memory, CPU, disk, and how fast requests are.

For deciding what hardware Oread fits on (the size sample). Everything here
is measured on the running Oread, not estimated.

Once a minute Oread notes its CPU time and memory (two reads from the kernel,
a few microseconds; nothing is written). Each minute is folded into the
current hour, and each finished hour is appended to logs/resources-history.jsonl,
so averages and peaks cover the last hour, day and 30 days and survive restarts.

Queue waits: when more requests arrive at once than server.max_concurrent,
the extra ones wait in line. The longest wait ever is kept in
logs/queue-record.json, and each hour records its longest wait, so it's plain
whether a building needs more concurrency (and the cores to back it).
Peak memory since start comes straight from the kernel, so no spike is missed
between samples; CPU per minute is exact too, since it is CPU time used over
the whole minute, not a snapshot.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import statistics
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import metrics

_START = time.time()
_SAMPLE_SECONDS = 60
_KEEP_HOURS = 24 * 30


class Resources:
    def __init__(self, paths: dict, devices, max_concurrent: int = 2) -> None:
        self.paths = paths
        self.devices = devices
        self.max_concurrent = max_concurrent
        self.record_file = paths["logs"] / "queue-record.json"
        try:
            self.record = json.loads(self.record_file.read_text())
        except (OSError, ValueError):
            self.record = None
        metrics.LISTENERS.append(self.note_request)
        self.history_file = paths["logs"] / "resources-history.jsonl"
        self.hours: deque = deque(_load_hours(self.history_file), maxlen=_KEEP_HOURS)
        self.minutes: deque = deque(maxlen=60)   # (wall time, CPU % of one core, memory MB)
        self.hour = None                         # the hour being filled
        self._hour_queue = {"waited": 0, "max": 0.0, "requests": 0}
        self._last = (time.time(), metrics.cpu_seconds())

    async def sample_forever(self) -> None:
        while True:
            await asyncio.sleep(_SAMPLE_SECONDS)
            self.sample()

    def sample(self) -> None:
        now, cpu = time.time(), metrics.cpu_seconds()
        (t0, c0), self._last = self._last, (now, cpu)
        if now <= t0:
            return
        percent = 100 * (cpu - c0) / (now - t0)
        memory = metrics.rss_mb()
        self.minutes.append((now, percent, memory))
        start = int(now // 3600 * 3600)
        if self.hour and self.hour["start"] != start:
            self._close_hour()
        if not self.hour:
            self.hour = {"start": start, "minutes": 0, "cpu_sum": 0.0, "cpu_max": 0.0,
                         "mem_sum": 0.0, "mem_max": 0.0}
        h = self.hour
        h["minutes"] += 1
        h["cpu_sum"] += percent
        h["cpu_max"] = max(h["cpu_max"], percent)
        h["mem_sum"] += memory
        h["mem_max"] = max(h["mem_max"], memory)

    def note_request(self, fields: dict) -> None:
        if fields.get("sample"):   # the sample household's requests never wait; they'd only blur the hour
            return
        wait = float((fields.get("steps_ms") or {}).get("queue") or 0)
        q = self._hour_queue
        q["requests"] += 1
        q["max"] = max(q["max"], wait)
        if wait >= 1:
            q["waited"] += 1
        if wait >= 1 and (not self.record or wait > self.record["wait_ms"]):
            self.record = {"wait_ms": round(wait, 1), "device": fields.get("device"),
                           "time": fields.get("time"), "audio_s": fields.get("audio_s"),
                           "max_concurrent": self.max_concurrent}
            try:
                tmp = self.record_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.record))
                tmp.replace(self.record_file)
            except OSError:
                pass

    def _close_hour(self) -> None:
        h, self.hour = self.hour, None
        row = {"hour": datetime.fromtimestamp(h["start"], timezone.utc).isoformat(timespec="minutes"),
               "minutes": h["minutes"],
               "cpu_avg": round(h["cpu_sum"] / h["minutes"], 1), "cpu_max": round(h["cpu_max"], 1),
               "mem_avg": round(h["mem_sum"] / h["minutes"]), "mem_max": round(h["mem_max"]),
               "requests": self._hour_queue["requests"], "waited": self._hour_queue["waited"],
               "queue_max_ms": round(self._hour_queue["max"])}
        self._hour_queue = {"waited": 0, "max": 0.0, "requests": 0}
        self.hours.append(row)
        try:
            with self.history_file.open("a") as f:
                f.write(json.dumps(row) + "\n")
            if self.history_file.stat().st_size > 400_000:   # keep the file to about 30 days
                tmp = self.history_file.with_suffix(".tmp")
                tmp.write_text("".join(json.dumps(r) + "\n" for r in self.hours))
                tmp.replace(self.history_file)
        except OSError:
            pass

    def history(self) -> dict:
        """Averages and peaks over the last hour, day and 30 days."""
        current = []
        if self.hour and self.hour["minutes"]:
            h = self.hour
            current = [{"minutes": h["minutes"], "cpu_avg": h["cpu_sum"] / h["minutes"],
                        "cpu_max": h["cpu_max"], "mem_avg": h["mem_sum"] / h["minutes"],
                        "mem_max": h["mem_max"]}]
        hours = list(self.hours) + current
        out = {}
        if self.minutes:  # the last 60 minutes, minute by minute
            cpu, mem = [m[1] for m in self.minutes], [m[2] for m in self.minutes]
            out["last_hour"] = {
                "hours_recorded": round(len(cpu) / 60, 1),
                "cpu_average_percent_of_one_core": round(sum(cpu) / len(cpu), 1),
                "cpu_busiest_minute_percent": round(max(cpu), 1),
                "memory_average_mb": round(sum(mem) / len(mem)),
                "memory_highest_mb": round(max(mem)),
            }
        for label, count in (("last_24_hours", 24), ("last_30_days", _KEEP_HOURS)):
            rows = hours[-count:]
            minutes = sum(r["minutes"] for r in rows)
            if not minutes:
                continue
            out[label] = {
                "hours_recorded": round(minutes / 60, 1),
                "cpu_average_percent_of_one_core":
                    round(sum(r["cpu_avg"] * r["minutes"] for r in rows) / minutes, 1),
                "cpu_busiest_minute_percent": round(max(r["cpu_max"] for r in rows), 1),
                "memory_average_mb": round(sum(r["mem_avg"] * r["minutes"] for r in rows) / minutes),
                "memory_highest_mb": round(max(r["mem_max"] for r in rows)),
            }
            finished = [r for r in rows if "requests" in r]
            if finished:
                out[label].update({
                    "requests": sum(r["requests"] for r in finished),
                    "requests_that_waited": sum(r["waited"] for r in finished),
                    "longest_queue_wait_ms": max(r["queue_max_ms"] for r in finished),
                })
        if not out:
            out["note"] = "the first minute hasn't been measured yet"
        return out

    def report(self) -> dict:
        cores = _cores()
        return {
            "uptime_hours": round((time.time() - _START) / 3600, 2),
            "memory": self._memory(),
            "cpu": {**self._cpu(cores), **_cpu_info()},
            "history": self.history(),
            "disk": self._disk(),
            "models_loaded": self._models(),
            "capacity": self._capacity(cores),
            "queue": self._queue(),
            "requests": _request_stats(self.paths["logs"] / "requests.jsonl"),
        }

    def _memory(self) -> dict:
        out = {"oread_now_mb": round(metrics.rss_mb()), "oread_peak_mb": round(metrics.peak_rss_mb())}
        limit = _read("/sys/fs/cgroup/memory.max")
        if limit and limit.isdigit():
            out["container_limit_mb"] = round(int(limit) / 2**20)
        try:
            with open("/proc/meminfo") as f:
                info = {line.split(":")[0]: int(line.split()[1]) for line in f}
            out["machine_total_mb"] = round(info["MemTotal"] / 1024)
            out["machine_available_mb"] = round(info["MemAvailable"] / 1024)
        except (OSError, KeyError, ValueError):
            pass
        return out

    def _cpu(self, cores: float) -> dict:
        used = metrics.cpu_seconds()
        uptime = max(time.time() - _START, 1)
        out = {"cores_available": cores,
               "average_percent_of_one_core_since_start": round(100 * used / uptime, 1)}
        recent = [p for t, p, _ in self.minutes if t > time.time() - 300]
        if recent:
            out["last_5_minutes_percent_of_one_core"] = round(sum(recent) / len(recent), 1)
        return out

    def _disk(self) -> dict:
        out = {}
        for key in ("models", "data", "logs"):
            out[f"{key}_mb"] = round(_size(self.paths[key]) / 2**20, 1)
        # the models actually in use: what a new device would need on disk
        loader, root = self.devices.loader, self.paths["models"]
        in_use = sum(_size(root / stt.model.folder) for stt in loader.stt.values())
        in_use += sum(_size(root / "speaker" / v.model.file) for v in loader.voiceprinters.values())
        out["models_in_use_mb"] = round(in_use / 2**20, 1)
        clips = self.paths["data"] / "clips"
        out["clips_saved"] = len(list(clips.glob("*.wav"))) if clips.exists() else 0
        usage = shutil.disk_usage(self.paths["data"])
        out["free_gb"] = round(usage.free / 2**30, 1)
        return out

    def _capacity(self, cores: float) -> dict:
        # the loader keys each model by (name, threads, ...)
        threads = max((key[1] for key in self.devices.loader.stt), default=1)
        vp = max((key[1] for key in self.devices.loader.voiceprinters), default=1)
        busy = self.max_concurrent * (threads + vp)
        return {"max_concurrent": self.max_concurrent,
                "threads_per_decode": threads, "voiceprint_threads": vp,
                "threads_when_all_busy": busy, "cores_available": cores,
                "note": ("More requests than max_concurrent at once wait in line. Raise "
                         "server.max_concurrent in settings.yaml (restart) when waits show up; "
                         "add cores when threads_when_all_busy is well past cores_available.")}

    def _queue(self) -> dict:
        out = {"longest_wait_ever": self.record or "no request has waited yet"}
        recent = _queue_stats(self.paths["logs"] / "requests.jsonl")
        if recent:
            out["last_requests"] = recent
        return out

    def _models(self) -> dict:
        loader = self.devices.loader
        return {
            "speech_to_text": sorted({stt.model.name for stt in loader.stt.values()}),
            "voiceprints": sorted({v.model.name for v in loader.voiceprinters.values()}),
        }


def _load_hours(path: Path) -> list[dict]:
    try:
        lines = path.read_text().splitlines()[-_KEEP_HOURS:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _queue_stats(path: Path, last: int = 200) -> dict | None:
    rows = _read_rows(path, last)
    if not rows:
        return None
    waits = [float((r.get("steps_ms") or {}).get("queue") or 0) for r in rows]
    waited = [w for w in waits if w >= 1]
    out = {"requests": len(rows), "waited": len(waited),
           "longest_wait_ms": round(max(waits)) if waits else 0}
    if waited:
        out["median_wait_when_waiting_ms"] = round(statistics.median(waited))
    return out


def _read_rows(path: Path, last: int) -> list[dict]:
    try:
        lines = path.read_text().splitlines()[-last:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _request_stats(path: Path, last: int = 200) -> dict:
    """Timing over the most recent requests, overall and per device."""
    try:
        lines = path.read_text().splitlines()[-last:]
    except OSError:
        return {"count": 0}
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if not rows:
        return {"count": 0}

    def summary(rs: list[dict]) -> dict:
        totals = sorted(r["total_ms"] for r in rs if "total_ms" in r)
        audio = [r["audio_s"] for r in rs if r.get("audio_s")]
        rtf = [r["rtf"] for r in rs if r.get("rtf") is not None]
        out = {"count": len(rs)}
        if totals:
            out["median_reply_ms"] = round(statistics.median(totals))
            out["slowest_5_percent_ms"] = round(totals[int(0.95 * (len(totals) - 1))])
        if audio:
            out["median_audio_s"] = round(statistics.median(audio), 2)
        if rtf:
            out["median_work_per_second_of_speech"] = round(statistics.median(rtf), 3)
        waits = [float((r.get("steps_ms") or {}).get("queue") or 0) for r in rs]
        out["longest_queue_wait_ms"] = round(max(waits)) if waits else 0
        return out

    by_device: dict[str, list] = {}
    for r in rows:
        by_device.setdefault(r.get("device", "?"), []).append(r)
    return {"last_requests": summary(rows),
            "by_device": {d: summary(rs) for d, rs in sorted(by_device.items())}}


def _cores() -> float:
    quota = _read("/sys/fs/cgroup/cpu.max")  # container CPU limit, e.g. "200000 100000" = 2 cores
    if quota and not quota.startswith("max"):
        try:
            q, period = quota.split()
            return round(int(q) / int(period), 2)
        except ValueError:
            pass
    try:
        return float(len(os.sched_getaffinity(0)))
    except AttributeError:
        return float(os.cpu_count() or 1)


def _cpu_info() -> dict:
    """The processor, and whether it has the instructions models run fastest with."""
    model, flags = None, set()
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name") and model is None:
                    model = line.split(":", 1)[1].strip()
                elif line.startswith("flags") and not flags:
                    flags = set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return {"processor": model,
            "has_avx2": "avx2" in flags,
            "has_avx512": any(f.startswith("avx512") for f in flags)}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None
