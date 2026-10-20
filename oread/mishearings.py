"""The mishearings, pulled from Wepwawet Veil (the house router), for Oread to learn from.

The router keeps what speech-to-text heard under what was really said, with the Oread clip
each was heard in (its learn/mishearings.yaml). Oread pulls that list when someone presses
Pull on the Mishearings page (batches you choose, no timer), through the router's oread door
(GET /learn/mishearings with the router's token), and looks each clip up itself: the models
that heard it and how (heard_with), kept with the line so they outlast the clip. A clip a
mishearing was heard in is kept out of the review list's trimming, so it can be played again
when a device's settings or a model change.

Saved in data/mishearings.json. Each pull merges in: a heard line is the same line whatever
its capitals, punctuation and spacing; a line the router no longer has is kept and marked gone
(corrections are never dropped here).

Needs the router's address (wepwawet: url in settings.yaml, or set on the Mishearings page,
then kept in data/wepwawet.yaml) and the router's token for the oread door in the vault under
wepwawet: token_key (default "wepwawet"). No address: off, and Oread stands alone.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .errors import OreadError

_LOG = logging.getLogger("oread.mishearings")
PATH = "/learn/mishearings"   # the router's door for this list (its oread door)


class MishearingsError(OreadError):
    pass


def key(text: str | None) -> str:
    """The same words whatever their capitals, punctuation (apostrophes too) and spacing."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower().replace("'", "")).split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Mishearings:
    def __init__(self, cfg: dict, vault, store, data_dir: Path) -> None:
        self.vault, self.store = vault, store
        self.key_name = cfg.get("token_key") or "wepwawet"
        self.timeout = float(cfg.get("timeout_s", 10))
        self.echoes_to = None        # set at start: the router's echoes go to the assistant voices (oread3)
        self.file = data_dir / "mishearings.json"
        self.url_file = data_dir / "wepwawet.yaml"
        self._lock = threading.Lock()
        saved = (yaml.safe_load(self.url_file.read_text()) or {}) if self.url_file.exists() else {}
        if self.url_file.exists():
            self.url = str(saved.get("url") or "")
            self.url_source = "data/wepwawet.yaml (set on the Wepwawet page)"
        else:
            self.url = str(cfg.get("url") or "")
            self.url_source = "settings.yaml"
        self.url = self.url.rstrip("/")
        # the Wepwawet page's switches (stage 1): on at all, people kept in step, the nightly pull
        self.link = {"enabled": bool(saved.get("enabled", True)),          # on unless switched off: with no address it does nothing
                     "people_sync": bool(saved.get("people_sync", False)),
                     "nightly_pull": bool(saved.get("nightly_pull", False)),
                     "pull_hour": int(saved.get("pull_hour", 3))}
        self._data = json.loads(self.file.read_text()) if self.file.exists() else {"lines": [], "last_pull": None}

    @property
    def configured(self) -> bool:
        return bool(self.url) and self.link["enabled"]

    def set_url(self, url: str) -> dict:
        """The router's address, from the page (empty: off). Kept in data/wepwawet.yaml."""
        url = (url or "").strip().rstrip("/")
        if url and not re.fullmatch(r"https?://[^\s/]+(:\d+)?", url):
            raise MishearingsError("The router's address is like http://192.168.1.20:8770 (its chat door's port)")
        with self._lock:
            self.url, self.url_source = url, "data/wepwawet.yaml (set on the Wepwawet page)"
            self._write_link()
        return self.view()

    def _write_link(self) -> None:
        tmp = self.url_file.with_suffix(".tmp")
        tmp.write_text("# How Oread works with the house router (Wepwawet Veil), set on the Wepwawet page.\n"
                       "# url empty = off. Delete this file to go back to settings.yaml (wepwawet: url).\n"
                       + yaml.safe_dump({"url": self.url, **self.link}, sort_keys=False))
        tmp.replace(self.url_file)

    def set_link(self, changes: dict) -> dict:
        """The Wepwawet page's switches: enabled, people_sync, nightly_pull, pull_hour (0 to 23)."""
        with self._lock:
            for k in ("enabled", "people_sync", "nightly_pull"):
                if changes.get(k) is not None:
                    self.link[k] = bool(changes[k])
            if changes.get("pull_hour") is not None:
                hour = int(changes["pull_hour"])
                if not 0 <= hour <= 23:
                    raise MishearingsError("The pull's hour is 0 to 23 (this server's clock)")
                self.link["pull_hour"] = hour
            self._write_link()
        return self.view()

    # ---------- people kept in step with the router's people grid (its people door) ----------

    def _ask(self, method: str, path: str, body: dict | None = None) -> dict:
        """One call to the router through Oread's door (its token in the vault)."""
        if not self.configured:
            raise MishearingsError("The router isn't set up or is switched off (the Wepwawet page)")
        try:
            token = self.vault.get(self.key_name)
        except ValueError as err:
            raise MishearingsError(f"No router token in the vault: put it under {self.key_name}") from err
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                detail = json.loads(err.read() or b"{}").get("detail") or ""
            except ValueError:
                detail = ""
            raise MishearingsError(f"The router answered {err.code}" + (f" ({detail})" if detail else ""), 502) from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise MishearingsError(f"Couldn't reach the router at {self.url}: {getattr(err, 'reason', err)}", 502) from err

    def person_changed(self, action: str, name: str, was: str | None = None) -> str | None:
        """A person added, renamed or deleted here, told to the router when people are kept in step
        (added: a row in its people grid if nobody has the name; renamed: the name there too; deleted:
        only taken out of Oread's column, the row kept for you to decide). Says what happened, or None
        when people aren't kept in step. Never fails the change made here."""
        if not (self.configured and self.link["people_sync"]):
            return None
        try:
            got = self._ask("POST", "/people/oread", {"action": action, "name": name, "was": was})
            return str(got.get("said") or "told the router")
        except OreadError as err:
            _LOG.warning("The router wasn't told about %s %s: %s", action, name, err)
            return f"the router wasn't told: {err}"

    def people_view(self, ours: list[str]) -> dict:
        """Oread's people beside the router's column for Oread: each name here, whether the router has
        it (and as whom), and the router's names Oread doesn't have."""
        got = self._ask("GET", "/people/oread")
        rows = got.get("people") or []
        theirs = {n.lower(): (row.get("person") or n) for row in rows for n in row.get("names") or []}
        mine = {o.lower() for o in ours}
        return {"here": [{"name": n, "at_router": theirs.get(n.lower())} for n in sorted(ours)],
                "only_at_router": sorted({n for row in rows for n in row.get("names") or [] if n.lower() not in mine})}

    def sync_people(self, ours: list[str]) -> dict:
        """Every person here the router doesn't have yet, added there."""
        view = self.people_view(ours)
        added = []
        for p in view["here"]:
            if not p["at_router"]:
                self._ask("POST", "/people/oread", {"action": "add", "name": p["name"]})
                added.append(p["name"])
        return {"added": added, **self.people_view(ours)}

    async def nightly_forever(self) -> None:
        """The nightly pull: once a day, at pull_hour on this server's clock, when switched on."""
        import asyncio
        while True:
            await asyncio.sleep(300)
            if not (self.configured and self.link["nightly_pull"]):
                continue
            now = datetime.now().astimezone()
            last = (self._data.get("last_pull") or {}).get("time")
            recent = bool(last) and (now - datetime.fromisoformat(last)).total_seconds() < 20 * 3600
            if now.hour == self.link["pull_hour"] and not recent:
                try:
                    summary = await asyncio.to_thread(self.pull)
                    _LOG.info("Nightly pull: %d lines, %d new", summary["lines"], summary["new"])
                except OreadError as err:
                    _LOG.warning("Nightly pull didn't run: %s", err)

    def view(self) -> dict:
        """The connection, the last pull, and every line with its clips (playable while Oread has them)."""
        has_key = any(k["name"] == self.key_name for k in self.vault.list()["keys"])
        with self._lock:
            lines = json.loads(json.dumps(self._data["lines"]))
            last = self._data.get("last_pull")
        for line in lines:
            for c in line.get("clips") or []:
                c["playable"] = self._clip(c["clip"]) is not None
        return {"url": self.url or None, "url_source": self.url_source, "token_key": self.key_name,
                "token_in_vault": has_key, "ready": self.configured and has_key, "last_pull": last, "lines": lines,
                **self.link}

    def _clip(self, clip_id: str) -> dict | None:
        try:
            return self.store.clip(clip_id)
        except OreadError:
            return None

    def _fetch(self) -> dict:
        if not self.configured:
            raise MishearingsError("Set the router's address first (wepwawet: url, or on this page)")
        try:
            token = self.vault.get(self.key_name)
        except ValueError as err:
            raise MishearingsError(f"No router token in the vault: put it under {self.key_name} "
                                   "(the router makes it: Security, API keys, the oread door)") from err
        req = urllib.request.Request(self.url + PATH, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            try:
                detail = json.loads(err.read() or b"{}").get("detail") or ""
            except ValueError:
                detail = ""
            hint = {401: "the router refused the token (its oread door wants its own token)",
                    403: "the router turned the request away"}.get(err.code, "")
            raise MishearingsError(f"The router answered {err.code}" + (f": {hint}" if hint else "")
                                   + (f" ({detail})" if detail else ""), 502) from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise MishearingsError(f"Couldn't reach the router at {self.url}: {getattr(err, 'reason', err)}", 502) from err

    def pull(self) -> dict:
        """Pull the router's list and merge it in. Returns what changed."""
        got = self._fetch()
        taught = self.echoes_to(got.get("echoes") or []) if self.echoes_to else None
        incoming = [(p.get("meant"), c) for p in got.get("mishearings") or [] for c in p.get("heard") or []]
        now = _now()
        with self._lock:
            lines = {key(line["said"]): line for line in self._data["lines"]}
            seen, new, changed, clips_new = set(), 0, 0, 0
            for meant, c in incoming:
                k = key(c.get("said"))
                if not k or k in seen:
                    continue
                seen.add(k)
                line = lines.get(k)
                if line is None:
                    line = lines[k] = {"said": c.get("said"), "clips": [], "pulled_first": now}
                    new += 1
                fresh = {"meant": meant, "count": int(c.get("count") or 1), "first": c.get("first"),
                         "last": c.get("last"), "taken": bool(c.get("taken")), "gone": False}
                if any(line.get(f) != v for f, v in fresh.items()) and line.get("pulled_first") != now:
                    changed += 1
                line.update(fresh, said=c.get("said"))
                have = {x["clip"] for x in line["clips"]}
                for x in c.get("clips") or []:
                    if not x.get("clip") or x["clip"] in have:
                        continue
                    line["clips"].append(self._look_up(x))
                    have.add(x["clip"])
                    clips_new += 1
            gone = 0
            for k, line in lines.items():
                if k not in seen and not line.get("gone"):
                    line["gone"] = True
                    gone += 1
            summary = {"time": now, "from": self.url, "router": got.get("router"), "lines": len(seen),
                       "new": new, "changed": changed, "gone": gone, "clips_new": clips_new,
                       "clips_found": sum(1 for line in lines.values() for x in line["clips"] if x.get("found")),
                       "clips_missing": sum(1 for line in lines.values() for x in line["clips"] if not x.get("found")),
                       **({"echoes": taught} if taught is not None else {})}
            self._data = {"lines": list(lines.values()), "last_pull": summary}
            self._save()
        _LOG.info("Mishearings pulled from %s: %d lines (%d new, %d changed, %d gone), %d new clips",
                  self.url, len(seen), new, changed, gone, clips_new)
        return summary

    def _look_up(self, x: dict) -> dict:
        """One clip the router named: Oread's own record of how it was heard, kept with the line."""
        out = {"clip": str(x["clip"]), "device": x.get("device"), "when": x.get("when"), "found": False}
        clip = self._clip(out["clip"])
        if clip is not None:
            out.update(found=True, device=clip.get("device") or out["device"], heard_at=clip.get("time"),
                       transcript=clip.get("transcript"), audio_s=clip.get("audio_s"),
                       heard_with=clip.get("heard_with"))
            try:
                self.store.keep(out["clip"], "mishearing")
            except OreadError as err:
                _LOG.warning("Couldn't keep clip %s for its mishearing: %s", out["clip"], err)
        return out

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1))
        tmp.replace(self.file)
