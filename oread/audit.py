"""Who changed what, and when: logs/audit.jsonl.

Every change made through the API (anything but reading) is recorded with
who made it (a signed-in user or an API token), the address it came from,
what was asked and whether it worked. Sign-ins, refused sign-ins, setup and
account changes are recorded too. Nothing secret is written: no passwords,
keys or tokens. The file keeps the newest KEEP lines.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

KEEP = 10000


class Audit:
    def __init__(self, log_dir: Path) -> None:
        self.path = log_dir / "audit.jsonl"
        self._lock = threading.Lock()
        self._lines: int | None = None

    def record(self, **event) -> None:
        row = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               **{k: v for k, v in event.items() if v is not None}}
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                if self._lines is None:
                    with self.path.open("rb") as f:
                        self._lines = sum(1 for _ in f)
                else:
                    self._lines += 1
                if self._lines > KEEP * 1.2:
                    keep = self.path.read_text().splitlines()[-KEEP:]
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text("".join(line + "\n" for line in keep))
                    tmp.replace(self.path)
                    self._lines = len(keep)
            except OSError:
                pass

    def recent(self, limit: int = 200) -> list[dict]:
        try:
            lines = self.path.read_text().splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
