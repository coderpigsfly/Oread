"""Per-request resource logging: CPU time, memory and time per step.

Every request writes one JSON line to logs/requests.jsonl and a short
readable line to the container log, so a change that makes Oread slow or
hungry shows up immediately.

The file keeps the newest KEEP_REQUESTS lines (logging.keep_requests in
settings.yaml): it's trimmed whenever it grows a fifth past that. The longest
queue wait ever and the hourly history are kept elsewhere, so trimming loses
neither.
"""

from __future__ import annotations

import json
import logging
import os
import resource
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_LOG = logging.getLogger("oread.requests")
_PAGE = os.sysconf("SC_PAGE_SIZE")
_WRITE_LOCK = threading.Lock()
KEEP_REQUESTS = 10000  # set from settings at start
_lines: int | None = None  # lines in requests.jsonl, counted once, then tracked
LISTENERS: list = []   # called with each finished request's fields (the resources report uses this)


def rss_mb() -> float:
    """Current resident memory of the Oread process."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * _PAGE / 2**20
    except OSError:
        return 0.0


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def cpu_seconds() -> float:
    """CPU time used by the whole process (all threads, user + system)."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


class Request:
    """Times the steps of one request and writes the log line at the end."""

    def __init__(self, log_dir: Path, client: str) -> None:
        self.log_dir = log_dir
        self.fields: dict = {"client": client, "steps_ms": {}}
        self._t0 = time.perf_counter()
        self._step_start: float | None = None
        self._cpu_start: float | None = None

    def start_step(self) -> None:
        self._step_start = time.perf_counter()

    def end_step(self, name: str) -> None:
        if self._step_start is not None:
            ms = (time.perf_counter() - self._step_start) * 1000
            self.fields["steps_ms"][name] = round(ms, 1)
        self._step_start = None

    def start_cpu(self) -> None:
        self._cpu_start = cpu_seconds()

    def end_cpu(self) -> None:
        if self._cpu_start is not None:
            self.fields["cpu_ms"] = round((cpu_seconds() - self._cpu_start) * 1000, 1)

    def finish(self, **extra) -> dict:
        self.fields.update(extra)
        self.fields["total_ms"] = round((time.perf_counter() - self._t0) * 1000, 1)
        self.fields["rss_mb"] = round(rss_mb(), 1)
        self.fields["peak_rss_mb"] = round(max(peak_rss_mb(), self.fields["rss_mb"]), 1)
        audio_s = self.fields.get("audio_s") or 0
        steps = self.fields["steps_ms"]
        stt_ms = steps.get("stt", steps.get("stt+voiceprint"))
        if audio_s and stt_ms is not None:
            # real-time factor: 0.1 means 10 s of audio took 1 s to transcribe
            self.fields["rtf"] = round(stt_ms / 1000 / audio_s, 3)
        self.fields = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **self.fields}
        self._write()
        for listen in LISTENERS:
            try:
                listen(self.fields)
            except Exception as err:  # a report must never break a request
                _LOG.warning("Request listener failed: %r", err)
        return self.fields

    def _write(self) -> None:
        f = self.fields
        steps = f["steps_ms"]
        speaker = f.get("speaker") or f.get("label")
        if f.get("guess") and not f.get("speaker"):
            speaker = f"{f.get('label')} (best {f['guess']} {f.get('score')})"
        _LOG.info(
            "%s audio=%.1fs work=%sms stt=%sms voiceprint=%sms cpu=%sms total=%sms rss=%sMB speaker=%s text=%r",
            f.get("device"), f.get("audio_s", 0), steps.get("stt+voiceprint", steps.get("stt")), steps.get("stt", "-"),
            steps.get("voiceprint", "-"), f.get("cpu_ms"), f["total_ms"], f["rss_mb"], speaker, f.get("text", ""),
        )
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / "requests.jsonl"
            with _WRITE_LOCK:
                with open(path, "a") as out:
                    out.write(json.dumps(f) + "\n")
                _trim(path)
        except OSError as err:
            _LOG.warning("Could not write request log: %s", err)


def drop_sample_lines(path: Path) -> int:
    """Take the sample household's lines (sample: true) out of a JSON-lines log; returns how many.
    The caller holds the log's own lock."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    kept = []
    for line in lines:
        try:
            if json.loads(line).get("sample"):
                continue
        except (ValueError, AttributeError):
            pass                                 # a line cut short stays as it was
        kept.append(line)
    if len(kept) < len(lines):
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(line + "\n" for line in kept))
        tmp.replace(path)
    return len(lines) - len(kept)


def forget_sample(log_dir: Path) -> int:
    """The sample household's lines out of requests.jsonl."""
    global _lines
    with _WRITE_LOCK:
        dropped = drop_sample_lines(log_dir / "requests.jsonl")
        _lines = None                            # counted again on the next write
    return dropped


def _trim(path: Path) -> None:
    """Keep the newest KEEP_REQUESTS lines (called under _WRITE_LOCK)."""
    global _lines
    if _lines is None:
        with open(path, "rb") as f:
            _lines = sum(1 for _ in f)
    else:
        _lines += 1
    if KEEP_REQUESTS > 0 and _lines > KEEP_REQUESTS * 1.2:
        keep = path.read_text().splitlines()[-KEEP_REQUESTS:]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(line + "\n" for line in keep))
        tmp.replace(path)
        _lines = len(keep)
