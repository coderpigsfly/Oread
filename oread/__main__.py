"""Start Oread: load settings and models, serve one port per device plus the API."""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from . import __version__, metrics, settings as settings_mod, tls
from .access import Access
from .api import build_app
from .audit import Audit
from .auth import TokenStore
from .users import Users
from .device_types import DeviceTypes
from .devices import DeviceManager
from .errors import OreadError
from .resources import Resources
from .retrain import Retrain
from .sample import Sample
from .store import Store
from .tuning import Tuning
from .vault import Vault
from .publish import HomeAssistant
from .mishearings import Mishearings
from .assistant_voice import AssistantVoices
from .timing import TimeLog
from .ospri import Records

_LOG = logging.getLogger("oread")


async def main() -> None:
    cfg = settings_mod.load()
    logging.basicConfig(
        level=getattr(logging, str(cfg["logging"]["level"]).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _LOG.info("Oread %s starting", __version__)
    metrics.KEEP_REQUESTS = int(cfg["logging"].get("keep_requests", 10000))
    for key in ("data", "logs"):
        cfg["paths"][key].mkdir(parents=True, exist_ok=True)

    store = Store(cfg["paths"]["data"], int(cfg["review"]["max_unassigned"]))
    store.retrain = Retrain(store, cfg["paths"]["data"] / "device_profiles.json")
    limit = asyncio.Semaphore(int(cfg["server"]["max_concurrent"]))
    access = Access(cfg["server"].get("allowed_clients") or [], cfg["paths"]["data"] / "access.yaml")
    vault = Vault(cfg["paths"]["data"] / "vault.json", cfg["paths"]["keys"])
    _LOG.info("Vault: %d keys, encryption key from %s", len(vault.list()["keys"]), vault.key_source)

    publisher = HomeAssistant(cfg["home_assistant"], vault)
    if publisher.configured:
        _LOG.info("Home Assistant at %s: each clip records its device's settings there; devices with "
                  "publish_speaker on set sensor.oread_<device>_speaker", publisher.url)
    devices = DeviceManager(cfg, store, limit, access, publisher, DeviceTypes(cfg["paths"]["data"]))
    devices.load_all()
    _LOG.info("Devices from %s", devices.source)

    tuning = Tuning(devices.runtimes, cfg["paths"]["data"] / "tuning.yaml")
    devices.tuning = tuning
    store.training_minimum = tuning.minimum
    store.real_first = int(cfg["assistant_voice"]["real_clips_first"])

    # every voiceprint model in use gets each profile's voiceprint (from saved
    # audio where needed), so switching models needs no re-enrollment
    devices.rebuild_profiles()
    await devices.start_all()

    mishearings = Mishearings(cfg["wepwawet"], vault, store, cfg["paths"]["data"])
    if mishearings.configured:
        _LOG.info("Wepwawet Veil at %s: the Mishearings page pulls its mishearings", mishearings.url)
    voices = AssistantVoices(publisher, store, devices, cfg["paths"]["data"])
    mishearings.echoes_to = voices.teach     # the router's echoes, with each pull: her voice as each device hears it
    voices.start()                     # any device that hears its own speaker: her voice, learned if it's new
    tokens = TokenStore(cfg["paths"]["data"] / "tokens.json")
    audit = Audit(cfg["paths"]["logs"])
    users = Users(cfg["paths"]["data"], audit.record)
    tls_info = tls.setup(cfg)
    scheme = "https" if tls_info else "http"
    if users.needs_setup():
        code = users.setup_code()
        _LOG.warning("First run: open %s://<this server>:%d/ and enter this one-time setup code "
                     "to create the super user: %s (also in data/setup-code.txt; it stays the same "
                     "until used)", scheme, int(cfg["api"]["port"]), code)

    resources = Resources(cfg["paths"], devices, int(cfg["server"]["max_concurrent"]))
    times = TimeLog(cfg["paths"]["logs"], int(cfg["stats"]["keep_days"]))   # Stats: where the time goes
    records = Records(cfg["paths"]["data"])        # OSPRI: a record of each request, while gathering
    sampler = asyncio.create_task(resources.sample_forever())
    nightly = asyncio.create_task(mishearings.nightly_forever())   # the nightly pull, when switched on

    api_port = int(cfg["api"]["port"])
    server = uvicorn.Server(uvicorn.Config(
        build_app(store, tuning, devices, tokens, access, resources, vault, publisher, users, audit,
                  tls_info.get("ca"), tls.describe(tls_info), mishearings=mishearings, voices=voices, times=times, records=records,
                  sample=Sample(store, devices, times)),
        host=cfg["server"]["host"], port=api_port, log_level="warning",
        ssl_certfile=str(tls_info["cert"]) if tls_info else None,
        ssl_keyfile=str(tls_info["key"]) if tls_info else None))
    _LOG.info("Oread's pages on %s://%s:%d/ (API page: /docs)", scheme, cfg["server"]["host"], api_port)
    try:
        await server.serve()  # returns when the container is stopped
    finally:
        sampler.cancel()
        nightly.cancel()
        await devices.stop_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except OreadError as err:   # a setting or model that doesn't fit: say which, and stop
        raise SystemExit(str(err)) from None
