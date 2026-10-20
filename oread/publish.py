"""Tell Home Assistant who spoke, for setups without the intent router.

Home Assistant's Wyoming integration keeps only the text of Oread's reply
and drops who spoke. So, for each request, Oread sets a sensor in Home
Assistant for that device before it replies:

    sensor.oread_voice_pe_speaker = Ann
      label: known | maybe | unknown | too short
      guess, score, by (voice / voice+phrase), clip, heard_at

Because the sensor is set before the text goes back, it is already current
when Home Assistant hands the text on, so automations ("if Ann asked...")
can read it. Oread only pushes; nothing calls back into Oread.

With the intent router in place, the router sits on the audio path and gets
the speaker straight from Oread's reply, so publishing can be turned off
(publish_speaker: false) for the devices it serves.

Needs home_assistant.url in settings.yaml and a long-lived access token in
the vault under home_assistant.token_key (default "home-assistant"). The
sensors are set through Home Assistant's REST API; they reappear on the next
request after a Home Assistant restart. Home Assistant's history records
them; exclude sensor.oread_* in its recorder settings if that isn't wanted.

The same address and token also read a device's own settings in Home Assistant (its
microphone volume, finished-speaking detection, wake word sensitivity...: every number,
select and switch of the Home Assistant device a listening device is matched to), so each
clip records them. Read in the background at most once a minute, never while a request waits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

_LOG = logging.getLogger("oread.publish")


def entity_id(device: str) -> str:
    return "sensor.oread_" + re.sub(r"[^a-z0-9_]", "_", device.lower()) + "_speaker"


class HomeAssistant:
    def __init__(self, cfg: dict, vault) -> None:
        self.url = (cfg.get("url") or "").rstrip("/")
        self.key = cfg.get("token_key") or "home-assistant"
        self.timeout = float(cfg.get("timeout_s", 0.5))
        self.vault = vault
        self.last: dict | None = None        # the last attempt, for the pages
        self._last_warning = 0.0
        self._settings: dict[str, dict] = {}   # Home Assistant device id -> {"read_at", "values"}
        self._reading: set[str] = set()

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def view(self) -> dict:
        has_key = any(k["name"] == self.key for k in self.vault.list()["keys"])
        return {"url": self.url or None, "token_key": self.key,
                "token_in_vault": has_key, "timeout_s": self.timeout,
                "publishing": self.configured and has_key, "last_attempt": self.last}

    async def publish(self, device: str, result: dict, clip: str | None) -> bool:
        if not self.configured:
            return False
        state = result.get("speaker") or ("unknown" if result.get("label") != "too short" else "too short")
        body = {
            "state": state,
            "attributes": {
                "friendly_name": f"Oread {device} speaker",
                "icon": "mdi:account-voice",
                "device": device,
                "label": result.get("label"),
                "guess": result.get("guess"),
                "score": result.get("score"),
                "by": result.get("by"),
                "clip": clip,
                "heard_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            },
        }
        return await asyncio.to_thread(self._post, entity_id(device), body)

    def test(self) -> dict:
        """Check the address and token without changing anything (GET /api/)."""
        if not self.configured:
            return {"ok": False, "detail": "home_assistant.url isn't set in settings.yaml"}
        try:
            token = self.vault.get(self.key)
        except ValueError as err:
            return {"ok": False, "detail": str(err)}
        req = urllib.request.Request(self.url + "/api/", headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=max(self.timeout, 3)) as resp:
                return {"ok": True, "detail": json.loads(resp.read() or b"{}").get("message", "ok")}
        except urllib.error.HTTPError as err:
            return {"ok": False, "detail": f"Home Assistant answered {err.code}"
                    + (" (the token was refused)" if err.code == 401 else "")}
        except (urllib.error.URLError, OSError) as err:
            return {"ok": False, "detail": f"Couldn't reach {self.url}: {err}"}

    # ---------- reading a device's own settings ----------

    def _template(self, text: str):
        """Render a template in Home Assistant (POST /api/template) and read it as JSON."""
        token = self.vault.get(self.key)
        req = urllib.request.Request(
            self.url + "/api/template", data=json.dumps({"template": text}).encode(), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=max(self.timeout, 5)) as resp:
            return json.loads(resp.read())

    def voice_devices(self) -> list[dict]:
        """Home Assistant's devices with a voice satellite, to match to listening devices."""
        if not self.configured:
            return []
        return self._template(
            "{% set ns = namespace(out=[]) %}{% for s in states.assist_satellite %}"
            "{% set d = device_id(s.entity_id) %}{% if d %}{% set ns.out = ns.out + "
            "[{'id': d, 'name': device_attr(d, 'name_by_user') or device_attr(d, 'name')}] %}"
            "{% endif %}{% endfor %}{{ ns.out | tojson }}")

    def device_settings(self, device_id: str | None) -> dict | None:
        """The last reading of a Home Assistant device's settings ({read_at, values}); a fresh
        one is fetched in the background when it's over a minute old."""
        if not device_id or not self.configured:
            return None
        known = self._settings.get(device_id)
        if (known is None or time.time() - known["fetched"] > 60) and device_id not in self._reading:
            self._reading.add(device_id)
            threading.Thread(target=self._read_settings, args=(device_id,), daemon=True).start()
        return {k: v for k, v in known.items() if k != "fetched"} if known else None

    def _read_settings(self, device_id: str) -> None:
        try:
            values = self._template(
                "{% set ns = namespace(out={}) %}{% for e in device_entities('" + re.sub(r"[^a-f0-9]", "", device_id)
                + "') %}{% if e.split('.')[0] in ['number', 'select', 'switch'] %}"
                "{% set ns.out = dict(ns.out, **{e: states(e)}) %}{% endif %}{% endfor %}{{ ns.out | tojson }}")
            self._settings[device_id] = {"fetched": time.time(), "values": values,
                                         "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        except (urllib.error.URLError, OSError, ValueError) as err:
            if time.monotonic() - self._last_warning > 300:
                self._last_warning = time.monotonic()
                _LOG.warning("Couldn't read Home Assistant device %s's settings: %s", device_id, err)
        finally:
            self._reading.discard(device_id)

    # ---------- an assistant's own voice: the patch for a device that hears itself ----------

    def pipelines(self) -> dict:
        """Home Assistant's voice pipelines ({"preferred": id, "pipelines": [...]}, each with its name,
        tts_engine, tts_language and tts_voice), read over its websocket API (no REST call lists them)."""
        from websockets.sync.client import connect      # only this reading needs it
        with connect(re.sub(r"^http", "ws", self.url) + "/api/websocket", open_timeout=10) as ws:
            ws.recv()
            ws.send(json.dumps({"type": "auth", "access_token": self.vault.get(self.key)}))
            if json.loads(ws.recv()).get("type") != "auth_ok":
                raise ValueError("Home Assistant refused the token")
            ws.send(json.dumps({"id": 1, "type": "assist_pipeline/pipeline/list"}))
            got = json.loads(ws.recv(timeout=10))
        if not got.get("success"):
            raise ValueError(f"Home Assistant couldn't list its pipelines: {got.get('error')}")
        result = got["result"]
        return {"preferred": result.get("preferred_pipeline"), "pipelines": result.get("pipelines") or []}

    def chosen_pipelines(self, device_id: str) -> list[str]:
        """The values of a Home Assistant device's selects in use: among them, the pipelines it answers
        with (a pipeline's name, or "preferred"). A second assistant (a select ending _2, _3...) counts only
        while its wake word (the select ending wake_word_2...) is set: unused, it may name any pipeline."""
        values = self._template(
            "{% set ns = namespace(out={}) %}{% for e in device_entities('" + re.sub(r"[^a-f0-9]", "", device_id)
            + "') %}{% if e.startswith('select.') %}{% set ns.out = dict(ns.out, **{e: states(e)}) %}{% endif %}"
            "{% endfor %}{{ ns.out | tojson }}")
        return [str(v) for e, v in values.items() if slot_in_use(e, values)]

    def speak(self, engine: str, voice: str | None, language: str | None, text: str) -> tuple[bytes, int]:
        """A line said by a Home Assistant text-to-speech voice: (16-bit mono samples, rate)."""
        token = self.vault.get(self.key)
        options = {"preferred_format": "wav", "preferred_sample_rate": 16000, "preferred_sample_channels": 1}
        if voice:
            options["voice"] = voice
        req = urllib.request.Request(
            self.url + "/api/tts_get_url", method="POST",
            data=json.dumps({"engine_id": engine, "message": text, "language": language, "options": options}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            path = json.loads(resp.read())["path"]
        with urllib.request.urlopen(urllib.request.Request(
                self.url + path, headers={"Authorization": f"Bearer {token}"}), timeout=60) as resp:
            return wav_samples(resp.read())

    def _post(self, entity: str, body: dict) -> bool:
        started = time.perf_counter()
        try:
            token = self.vault.get(self.key)
            req = urllib.request.Request(
                f"{self.url}/api/states/{entity}", data=json.dumps(body).encode(), method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            ok, detail = True, "ok"
        except urllib.error.HTTPError as err:
            ok, detail = False, f"Home Assistant answered {err.code}"
        except (urllib.error.URLError, OSError, ValueError) as err:   # ValueError: vault problems
            ok, detail = False, str(err)
        self.last = {"entity": entity, "state": body["state"], "ok": ok, "detail": detail,
                     "ms": round((time.perf_counter() - started) * 1000, 1),
                     "time": body["attributes"]["heard_at"]}
        if not ok and time.monotonic() - self._last_warning > 300:   # warn at most every 5 minutes
            self._last_warning = time.monotonic()
            _LOG.warning("Couldn't tell Home Assistant who spoke (%s): %s", entity, detail)
        return ok


def slot_in_use(entity: str, selects: dict) -> bool:
    """A select of a numbered slot (ending _2, _3...) is in use only while that slot's wake word is set."""
    slot = re.search(r"_(\d+)$", entity)
    if not slot or entity.endswith("wake_word" + slot.group(0)):
        return True
    wake = [v for e, v in selects.items() if e.endswith("wake_word" + slot.group(0))]
    return any(v not in ("no_wake_word", "unknown", "unavailable", "") for v in wake)


def wav_samples(data: bytes) -> tuple[bytes, int]:
    """A WAV's 16-bit mono samples and rate, read by its chunks: a streamed WAV's header can't
    give the length (it says "very long"), so the data chunk runs to the end."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Not a WAV")
    at, rate, form = 12, None, None
    while at + 8 <= len(data):
        kind, size = data[at:at + 4], int.from_bytes(data[at + 4:at + 8], "little")
        if kind == b"fmt ":
            form = (int.from_bytes(data[at + 8:at + 10], "little"), int.from_bytes(data[at + 10:at + 12], "little"),
                    int.from_bytes(data[at + 22:at + 24], "little"))
            rate = int.from_bytes(data[at + 12:at + 16], "little")
        elif kind == b"data":
            if form != (1, 1, 16) or not rate:
                raise ValueError("The voice didn't come back as 16-bit mono WAV")
            end = len(data) if size in (0, 0xFFFFFFFF) or at + 8 + size > len(data) else at + 8 + size
            return data[at + 8:end][: (end - at - 8) // 2 * 2], rate
        at += 8 + size + (size & 1)
    raise ValueError("The WAV has no sound in it")
