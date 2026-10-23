"""Oread's API: everything the pages do, and everything a program can do with a token.

The interactive page at /docs lists every call and can try each one.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, catalog, explore, metrics, wepwawet
from .access import Access
from .audit import Audit
from .auth import TokenStore
from .compare import Comparisons
from .devices import DeviceManager
from .errors import OreadError
from .handler import process
from .phrases import top_phrases
from .store import Store
from .tuning import Tuning
from .users import MAX_SECONDS, RANK, Users
from .vault import Vault


class AssignBody(BaseModel):
    profile: str


class ProfileBody(BaseModel):
    name: str
    kind: Literal["person", "assistant"] = "person"   # assistant: an assistant's own voice (the patch)


class GatherBody(BaseModel):
    gather: bool


class LearnBody(BaseModel):
    again: bool = False


class LinkBody(BaseModel):
    enabled: bool | None = None
    people_sync: bool | None = None
    nightly_pull: bool | None = None
    pull_hour: int | None = None


class RenameBody(BaseModel):
    new_name: str


class NewDevice(BaseModel):
    name: str
    type: str | None = None
    port: int | None = None
    stt_model: str | None = None
    speaker_model: str | None = None


class ChangeDevice(BaseModel):
    new_name: str | None = None
    stt_model: str | None = None       # "" = back to the default
    speaker_model: str | None = None   # "" = back to the default
    assistant_device: str | None = None   # its device id in the voice assistant; "" = none


class RetrainBody(BaseModel):
    device: str
    person: str
    clips: list[str]
    why: str | None = None


class TrialBody(BaseModel):
    device: str
    person: str


class NewDeviceType(BaseModel):
    name: str
    label: str
    note: str | None = None
    stt_model: str | None = None       # leave out for the default
    speaker_model: str | None = None


class ChangeDeviceType(BaseModel):
    label: str | None = None
    note: str | None = None            # "" = no note


class ModelEntry(BaseModel):
    fields: dict


class NewModelEntry(BaseModel):
    name: str
    fields: dict


class ModelSettings(BaseModel):
    settings: dict[str, float | int | str]


class RouterAddress(BaseModel):
    url: str


class AllowedClients(BaseModel):
    allowed_clients: list[str]


class NewToken(BaseModel):
    name: str
    role: Literal["viewer", "reviewer", "administrator", "super"] = "administrator"


class VaultKey(BaseModel):
    value: str
    service: str | None = None
    note: str | None = None


class SpeakerKnobs(BaseModel):
    min_training_seconds: float | None = None
    unknown_below: float | None = None
    match_above: float | None = None
    phrase_from: float | None = None
    phrase_to: float | None = None
    phrase_mode: Literal["off", "shadow", "on"] | None = None
    publish_speaker: bool | None = None
    trim_silence: bool | None = None
    hears_own_speaker: bool | None = None


class CompareBody(BaseModel):
    kind: Literal["speech", "voice"]
    model: str
    limit: int = 50


class JudgeBody(BaseModel):
    clip: str
    choice: Literal["current", "candidate", "neither", ""]


class SetupBody(BaseModel):
    code: str
    username: str
    password: str


class SignInBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


class NewUser(BaseModel):
    username: str
    password: str
    role: Literal["viewer", "reviewer", "administrator", "super"]


class ChangeUser(BaseModel):
    role: Literal["viewer", "reviewer", "administrator", "super"] | None = None
    password: str | None = None


_bearer = HTTPBearer(auto_error=False, description="An Oread API token (oread_...)")
COOKIE = "oread_session"
WEB_DIR = Path(__file__).resolve().parent / "web"
GUIDE = Path(__file__).resolve().parent.parent / "docs" / "user-guide.md"

# Who may use each part of the API: (to read, to change). Tags not listed need
# an administrator. "public" routes need nobody (sign-in, setup, the CA file).
RULES = {
    "status": ("viewer", "administrator"),
    "resources": ("viewer", "administrator"),
    "phrases": ("viewer", "administrator"),
    "profiles": ("viewer", "reviewer"),
    "clips": ("reviewer", "reviewer"),
    "try": ("reviewer", "reviewer"),
    "sample": ("viewer", "administrator"),
    "devices": ("viewer", "administrator"),
    "settings": ("viewer", "administrator"),
    "tokens": ("administrator", "administrator"),
    "home assistant": ("administrator", "administrator"),
    "mishearings": ("reviewer", "reviewer"),
    "ospri": ("reviewer", "administrator"),
    "wepwawet": ("administrator", "administrator"),
    "users": ("administrator", "administrator"),
    "audit": ("administrator", "administrator"),
    "compare": ("administrator", "administrator"),
    "access": ("super", "super"),
    "vault": ("super", "super"),
    "account": ("viewer", "viewer"),
}
_READING = {"GET", "HEAD", "OPTIONS"}


def _check_url(url: str) -> dict:
    """Ask the address for its headers only: does it answer, and how big is the file?"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": f"Oread/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            size = resp.headers.get("Content-Length")
            return {"ok": True, "status": resp.status, "final_url": resp.geturl(),
                    "size_mb": round(int(size) / 2**20, 1) if size and size.isdigit() else None}
    except urllib.error.HTTPError as err:
        return {"ok": False, "status": err.code, "note": f"The address answered {err.code} {err.reason}"}
    except (urllib.error.URLError, OSError, ValueError) as err:
        return {"ok": False, "status": None, "note": f"Couldn't reach it: {getattr(err, 'reason', err)}"}


def allowed(role: str, tag: str, method: str) -> bool:
    read, change = RULES.get(tag, ("administrator", "administrator"))
    need = read if method in _READING else change
    return RANK[role] >= RANK[need]


def build_app(store: Store, tuning: Tuning, devices: DeviceManager, tokens: TokenStore,
              access: Access, resources, vault: Vault, publisher, users: Users,
              audit: Audit, ca_file: Path | None = None, https: dict | None = None,
              mishearings=None, voices=None, times=None, records=None, sample=None) -> FastAPI:
    def caller(request: Request,
               creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict | None:
        """Who is calling: an API token (programs) or a signed-in person (pages)."""
        route = request.scope.get("route")
        tags = getattr(route, "tags", None) or []
        if "public" in tags:
            return None
        token = creds.credentials if creds else None
        who = None
        if token:
            name = tokens.check(token)
            if name is not None:
                who = {"kind": "token", "name": name, "role": tokens.role(name)}
        else:
            user = users.session_user(request.cookies.get(COOKIE))
            if user is not None:
                if request.method not in _READING and request.headers.get("x-requested-with") != "oread":
                    # a page from another site can't add this header, so it can't act for you
                    raise HTTPException(status_code=403, detail="Missing X-Requested-With: oread")
                who = {"kind": "user", "name": user["name"], "role": user["role"]}
        if who is None:
            raise HTTPException(status_code=401, detail="Sign in, or give a permitted API token",
                                headers={"WWW-Authenticate": "Bearer"})
        tag = tags[0] if tags else ""
        if not allowed(who["role"], tag, request.method):
            raise HTTPException(status_code=403,
                                detail=f"A {who['role']} can't do that ({tag or 'this'})")
        request.state.caller = who
        return who

    app = FastAPI(
        title="Oread",
        version=__version__,
        dependencies=[Depends(caller)],
        # the API page and its description are served below, for signed-in people and tokens only
        docs_url=None, redoc_url=None, openapi_url=None,
        description=(
            "Speech-to-text and speaker ID. Review recent clips, listen to them, and "
            "assign them to people; each assignment improves that person's voiceprint.\n\n"
            "People use Oread's pages (`/ui/`). Programs use this API with a token: "
            "**press Authorize** (top right) and paste one, then open a call, press "
            "**Try it out**, and **Execute**. Each token has a role, like a person, and "
            "can do only what that role allows."
        ),
    )

    @app.exception_handler(OreadError)
    async def refused(request: Request, err: OreadError):
        """Any part of Oread saying no: its status code and its message, as FastAPI shows errors."""
        return JSONResponse(status_code=err.status, content={"detail": str(err)})

    def client_of(request: Request) -> str | None:
        return request.client.host if request.client else None

    @app.middleware("http")
    async def record_and_protect(request: Request, call_next):
        response = await call_next(request)
        who = getattr(request.state, "caller", None)
        if request.method not in _READING and who is not None:
            audit.record(action=f"{request.method} {request.url.path}", who=who["name"],
                         by=who["kind"], client=client_of(request), status=response.status_code)
        if request.url.path.startswith("/ui"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def set_session(response: Response, request: Request, session: str) -> None:
        response.set_cookie(COOKIE, session, max_age=MAX_SECONDS, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")

    # ---------- the API page: only for someone signed in (or a program with a token) ----------

    @app.get("/openapi.json", tags=["account"], include_in_schema=False)
    def openapi_description():
        # with its x-wepwawet section: how Oread fits the house router (oread/wepwawet.py)
        return JSONResponse(wepwawet.described(app.openapi()))

    @app.get("/docs", tags=["public"], include_in_schema=False)
    def api_page(request: Request):
        if users.session_user(request.cookies.get(COOKIE)) is None:
            return RedirectResponse("/ui/")   # sign in on the pages first
        return get_swagger_ui_html(openapi_url="/openapi.json", title="Oread API")

    # ---------- signing in (public) ----------

    @app.get("/api/setup", tags=["public"], summary="Does Oread still need its first user?")
    def setup_needed():
        return {"needed": users.needs_setup()}

    @app.post("/api/setup", tags=["public"],
              summary="First run: the setup code (data/setup-code.txt or the log), then the super user's name and password")
    def setup(body: SetupBody, request: Request, response: Response):
        user = users.setup(body.code, body.username, body.password, client_of(request))
        session, user = users.sign_in(body.username, body.password, client_of(request))
        set_session(response, request, session)
        return {"user": user}

    @app.post("/api/session", tags=["public"], summary="Sign in")
    def sign_in(body: SignInBody, request: Request, response: Response):
        session, user = users.sign_in(body.username, body.password, client_of(request))
        set_session(response, request, session)
        return {"user": user}

    @app.get("/api/session", tags=["public"], summary="Who is signed in, and what they may use")
    def who_am_i(request: Request):
        user = users.session_user(request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in")
        can = {tag: {"read": allowed(user["role"], tag, "GET"),
                     "change": allowed(user["role"], tag, "POST")} for tag in RULES}
        return {"user": user, "can": can, "grantable": users.grantable(user),
                "version": __version__}

    @app.delete("/api/session", tags=["public"], summary="Sign out")
    def sign_out(request: Request, response: Response):
        user = users.session_user(request.cookies.get(COOKIE))
        users.sign_out(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        if user:
            audit.record(action="sign-out", who=user["name"], client=client_of(request))
        return {"signed_out": True}

    @app.get("/ca.crt", tags=["public"], response_class=FileResponse,
             summary="Oread's household certificate authority, to install on your devices")
    def ca_certificate():
        if ca_file is None or not ca_file.exists():
            raise HTTPException(status_code=404, detail="Oread isn't using its household certificate")
        return FileResponse(ca_file, media_type="application/x-x509-ca-cert", filename="oread-household-ca.crt")

    # ---------- your account ----------

    @app.post("/api/account/password", tags=["account"], summary="Change your own password")
    def change_password(body: PasswordBody, request: Request):
        who = request.state.caller
        if who["kind"] != "user":
            raise HTTPException(status_code=400, detail="API tokens have no password")
        users.change_own_password(who["name"], body.current, body.new, request.cookies.get(COOKIE))
        return {"changed": True, "note": "Your other sessions were signed out."}

    @app.get("/guide", tags=["account"], response_class=PlainTextResponse,
             summary="The user guide (Markdown), as shipped with this version of Oread")
    def user_guide():
        """docs/user-guide.md from this install; the Setup guide page shows it."""
        if not GUIDE.exists():
            raise HTTPException(status_code=404, detail="The user guide isn't in this install")
        return PlainTextResponse(GUIDE.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")

    # ---------- users (from the role down) ----------

    @app.get("/users", tags=["users"], summary="Everyone who can sign in")
    def list_users(request: Request):
        actor = request.state.caller
        return {"users": users.list(actor), "you_can_grant": users.grantable(actor)}

    @app.post("/users", tags=["users"], summary="Add a person (roles below your own)")
    def add_user(body: NewUser, request: Request):
        return users.create(request.state.caller, body.username, body.password, body.role)

    @app.patch("/users/{name}", tags=["users"],
               summary="Change a person's role or reset their password (signs them out)")
    def change_user(name: str, body: ChangeUser, request: Request):
        return users.update(request.state.caller, name, body.role, body.password)

    @app.delete("/users/{name}", tags=["users"], summary="Remove a person")
    def remove_user(name: str, request: Request):
        users.delete(request.state.caller, name)
        return {"removed": name}

    @app.post("/api/try", tags=["try"],
              summary="Try it: send audio as if from a listening device; get the words and the speaker")
    async def try_it(request: Request, device: str, rate: int = 16000):
        """The body is raw audio: 16-bit little-endian mono samples at `rate` per second, up to
        20 seconds. It's handled exactly like a request from that device's listening port
        (the same models, settings and Learn page), except who spoke isn't reported onward."""
        runtime = devices.runtimes.get(device)
        if runtime is None:
            raise HTTPException(status_code=404, detail=f"No device named '{device}'")
        if not 8000 <= rate <= 96000:
            raise HTTPException(status_code=400, detail="rate must be between 8000 and 96000")
        pcm = await request.body()
        if len(pcm) > rate * 2 * 20 + 4096:
            raise HTTPException(status_code=413, detail="That's longer than 20 seconds")
        if len(pcm) < rate * 2 // 4:
            raise HTTPException(status_code=400, detail="That's too short to hear anything; speak for a second or more")
        who = request.state.caller
        req = metrics.Request(devices.cfg["paths"]["logs"], f"try-it ({who['name']})")
        req.start_step()
        req.end_step("receive")
        text, context = await process(runtime, store, devices.limit, devices.habits, None,
                                      pcm[: len(pcm) - len(pcm) % 2], rate, 2, 1, req, publish=False)
        return {"text": text, **context}

    @app.get("/sample", tags=["sample"], summary="The sample household: whether it's here, and what it holds")
    def sample_status():
        """Three LibriSpeech readers: two taught (Sample Ada, Sample Ben) and one Oread hasn't met,
        with their clips heard on `device`. added: it's here now; busy: being added or removed."""
        if sample is None:
            raise HTTPException(status_code=404, detail="No sample household in this Oread")
        return sample.status()

    @app.post("/sample", tags=["sample"], summary="Add the sample household (about a minute)")
    async def sample_add():
        """Each clip goes through the same steps as a request from the device (nothing is reported
        onward): the taught ones are assigned to their sample person, the rest wait on the Learn page
        with Oread's own guesses. Refused (409) when it's already here or a person has a sample name."""
        if sample is None:
            raise HTTPException(status_code=404, detail="No sample household in this Oread")
        return await sample.add()

    @app.delete("/sample", tags=["sample"], summary="Remove the sample household, and nothing else")
    async def sample_remove():
        """Its clips, its people and their lines in the logs (Stats) go. A clip of yours assigned to
        a sample person goes back to waiting."""
        if sample is None:
            raise HTTPException(status_code=404, detail="No sample household in this Oread")
        return await sample.remove()

    @app.get("/audit", tags=["audit"], summary="Who changed what, newest first")
    def audit_log(limit: int = 200):
        return {"events": audit.recent(max(1, min(limit, 2000)))}

    # the front door opens Oread's pages
    app.add_route("/", lambda request: RedirectResponse("/ui/"), include_in_schema=False)
    if WEB_DIR.exists():
        app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    @app.get("/resources", tags=["resources"],
             summary="Memory, CPU, disk and request speed (for choosing hardware)")
    def get_resources():
        return resources.report()

    @app.get("/access", tags=["access"],
             summary="Clients permitted on the listening ports, and who was recently refused")
    def get_access(request: Request):
        """your_address: the address this request came from, to add your own computer."""
        return {**access.view(), "your_address": client_of(request)}

    @app.put("/access", tags=["access"], summary="Set the clients permitted on the listening ports")
    def set_access(body: AllowedClients):
        """Addresses (192.168.1.50) or ranges (192.168.1.0/24). Include Home Assistant's
        address and your laptop's. An empty list lets anyone connect. Takes effect for the
        next connection. The API port is protected by tokens, not by this list."""
        return access.replace(body.allowed_clients)

    @app.get("/tokens", tags=["tokens"], summary="API tokens (names and last use, never the tokens)")
    def list_tokens():
        return tokens.list()

    @app.post("/tokens", tags=["tokens"], summary="Create an API token (shown once; copy it)")
    def create_token(body: NewToken, request: Request):
        """role: what the token may do, like a person's role (default administrator).
        It can't be higher than your own; only a super user can make a super token."""
        actor = request.state.caller
        if RANK[body.role] > RANK[actor["role"]]:
            raise HTTPException(status_code=403, detail=f"A {actor['role']} can't make a {body.role} token")
        return {"name": body.name.strip(), "role": body.role,
                "token": tokens.create(body.name, body.role),
                "note": "Copy this now; it won't be shown again."}

    @app.delete("/tokens/{name}", tags=["tokens"], summary="Revoke an API token")
    def revoke_token(name: str):
        tokens.revoke(name)
        return {"revoked": name}

    @app.get("/vault", tags=["vault"],
             summary="Keys Oread uses to reach other programs (names and hints, never the keys)")
    def list_vault():
        """Shows each key's name, what it's for, its last 4 characters and when it was
        last used. The keys themselves are never returned by the API."""
        return vault.list()

    @app.put("/vault/{name}", tags=["vault"], summary="Add or replace a key")
    def set_vault(name: str, body: VaultKey):
        """name: lowercase, like `home-assistant`. value: the key or token the other program
        gave you. service and note are optional labels (kept if left out on a replace).
        Stored encrypted; the API shows only its last 4 characters from now on."""
        return vault.set(name, body.value, body.service, body.note)

    @app.delete("/vault/{name}", tags=["vault"], summary="Delete a key")
    def delete_vault(name: str):
        vault.delete(name)
        return {"deleted": name}

    @app.get("/home-assistant", tags=["home assistant"],
             summary="Telling Home Assistant who spoke: address, token and the last attempt")
    def ha_view():
        """Without the intent router, Oread sets sensor.oread_<device>_speaker in Home
        Assistant before each reply. Set home_assistant.url in settings.yaml and put a
        long-lived access token in the vault (PUT /vault/home-assistant). Turn it off per
        device with publish_speaker on PATCH /settings/speaker."""
        return publisher.view()

    @app.get("/assistant/devices", tags=["home assistant"],
             summary="The voice assistant's devices, to match each listening device to one")
    async def assistant_devices():
        """Each device with a voice satellite in the voice assistant Oread is connected to
        (home_assistant: url): its id and name. configured: false when no address is set."""
        try:
            return {"configured": publisher.configured,
                    "devices": await asyncio.to_thread(publisher.voice_devices)}
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise HTTPException(status_code=502, detail=f"Couldn't read Home Assistant's devices: {err}")

    @app.post("/home-assistant/test", tags=["home assistant"],
              summary="Check the address and token (changes nothing)")
    def ha_test():
        return publisher.test()

    @app.get("/mishearings", tags=["mishearings"],
             summary="The mishearings pulled from Wepwawet Veil (the house router), with their clips")
    def mishearings_view():
        """Each line speech-to-text heard (said) under what was really said (meant), its count,
        and each Oread clip it was heard in, with how it was heard (heard_with: the models) and
        whether it can still be played; the router's address, whether its token is in the vault,
        and the last pull."""
        return mishearings.view()

    @app.post("/mishearings/pull", tags=["mishearings"],
              summary="Pull the router's mishearings now and merge them in")
    async def mishearings_pull():
        """Asks the router (wepwawet: url, its oread door, the token in the vault under
        wepwawet: token_key). New lines are added, changed ones updated, lines the router no
        longer has are kept and marked gone; each clip is looked up here and kept from trimming."""
        return await asyncio.to_thread(mishearings.pull)

    @app.get("/wepwawet", tags=["wepwawet"], summary="How Oread works with the house router, and its people beside ours")
    def wepwawet_view():
        """The router's address and token, the switches (enabled, people_sync, nightly_pull, pull_hour),
        the last pull, and, when the router can be asked, Oread's people beside the router's column for Oread."""
        out = {k: v for k, v in mishearings.view().items() if k != "lines"}
        people = [p["name"] for p in store.profiles(everyone=False)]
        try:
            out["people"] = mishearings.people_view(people) if mishearings.configured else None
        except OreadError as err:
            out["people"], out["people_error"] = None, str(err)
        return out

    @app.patch("/wepwawet", tags=["wepwawet"], summary="Switch Oread's work with the router on or off, people in step, the nightly pull")
    def wepwawet_set(body: LinkBody):
        return mishearings.set_link(body.model_dump())

    @app.post("/wepwawet/people", tags=["wepwawet"], summary="Add every person here the router doesn't have yet")
    def wepwawet_people():
        return mishearings.sync_people([p["name"] for p in store.profiles(everyone=False)])

    @app.put("/mishearings/router", tags=["wepwawet"],
             summary="Set the router's address for pulling (empty: off)")
    def mishearings_router(body: RouterAddress):
        """Kept in data/wepwawet.yaml, which then takes over from settings.yaml (wepwawet: url)."""
        return mishearings.set_url(body.url)

    @app.get("/status", tags=["status"], summary="Version, devices and counts")
    def status():
        return {"version": __version__, "devices": devices.list()["devices"], **store.counts(),
                "https": https or {"https": False}}

    @app.get("/devices", tags=["devices"], summary="Listening devices, their ports and models")
    def list_devices():
        return devices.list()

    @app.post("/devices", tags=["devices"], summary="Add a device (starts listening at once)")
    async def add_device(body: NewDevice):
        """name: lowercase, like `kitchen-pe`. type: a device type's name (GET /device-types).
        port: leave out to take the next free one. stt_model / speaker_model: leave out to use
        the type's or the defaults. Then point that device's client (Home Assistant, for
        example) at this server and the port shown."""
        return await devices.add(body.name, body.type, body.port, body.stt_model, body.speaker_model)

    @app.patch("/devices/{name}", tags=["devices"],
               summary="Rename a device, or change its models (\"\" = back to the default)")
    async def change_device(name: str, body: ChangeDevice):
        """new_name: its port and clips go with it. stt_model / speaker_model: a name from
        GET /models, or "" for the default. assistant_device: its device in the voice assistant (an
        id from GET /assistant/devices; "" for none), whose settings each clip then records. A device on its own model loads that model into
        memory (once; devices sharing a model share it); the port pauses while it loads."""
        result = {}
        if body.new_name is not None and body.new_name.strip().lower() != name:
            result = await devices.rename(name, body.new_name)
            name = result["to"]
        if body.stt_model is not None or body.speaker_model is not None:
            result = {**result, **await devices.set_models(name, body.stt_model, body.speaker_model)}
        if body.assistant_device is not None:
            result = {**result, **await devices.set_assistant_device(name, body.assistant_device.strip())}
        return result or {"unchanged": name}

    @app.get("/device-types", tags=["devices"],
             summary="Kinds of device: label, note, starting models, which devices use each")
    def list_device_types():
        return {"types": devices.list()["types"]}

    @app.post("/device-types", tags=["devices"], summary="Add a device type (saved in data/device-types.yaml)")
    def add_device_type(body: NewDeviceType):
        """name: lowercase, like `kitchen-speaker` (devices refer to it). label: what people read.
        stt_model / speaker_model: starting models for every device of this type (a name from
        GET /models); leave out for the defaults. A device's own model choice still wins."""
        return devices.add_type(body.name, body.label, body.note, body.stt_model, body.speaker_model)

    @app.patch("/device-types/{name}", tags=["devices"], summary="Change a type's label or note")
    def change_device_type(name: str, body: ChangeDeviceType):
        """The name stays the same, so devices of this type keep it."""
        return devices.relabel_type(name, body.label, body.note)

    @app.delete("/device-types/{name}", tags=["devices"], summary="Remove a type no device uses")
    def remove_device_type(name: str):
        return devices.remove_type(name)

    comparisons = Comparisons(devices, store)

    @app.post("/devices/{name}/compare", tags=["compare"],
              summary="Compare a model on this device's own clips (runs only when asked)")
    async def start_compare(name: str, body: CompareBody, request: Request):
        """kind voice: score the device's current voice model and `model` on its assigned clips
        (who was speaking is known). kind speech: `model` listens to the device's newest `limit`
        clips; clips where its words differ are listed for a person to judge. One comparison at
        a time; follow it with GET /compare."""
        return comparisons.start(name, body.kind, body.model, body.limit, request.state.caller["name"])

    @app.get("/compare", tags=["compare"], summary="The running or last comparison, with results")
    def get_compare():
        return comparisons.view()

    @app.post("/compare/judge", tags=["compare"],
              summary="Speech comparison: say which words were right for a clip")
    def judge_compare(body: JudgeBody):
        return comparisons.judge(body.clip, body.choice)

    @app.delete("/compare", tags=["compare"],
                summary="Stop the running comparison, or put away a finished one")
    def cancel_compare():
        return comparisons.cancel()

    @app.get("/models", tags=["devices"], summary="Models a device can use: memory, notes, who uses them")
    def list_models():
        return devices.model_choices()

    @app.patch("/models/{kind}/{name}", tags=["settings"],
               summary="Change a model's own settings (every device using it picks them up now)")
    async def change_model_settings(kind: Literal["speech", "voice", "vad"], name: str, body: ModelSettings):
        """settings: only what you change, from the model's `settings` in GET /models (threads; for
        voice models also unknown_below, match_above, phrase_from, phrase_to). Saved in
        data/models.yaml. Thresholds apply at once; a thread change reloads the model, pausing
        those devices' ports for a moment. Values set for one device stay on top."""
        catalog.save(kind, name, settings=body.settings)
        return {"model": name, **await devices.apply_model_list()}

    @app.post("/models/{kind}/{name}/default", tags=["settings"],
              summary="Make this the default model (devices without their own choice switch now)")
    async def make_default_model(kind: Literal["speech", "voice", "vad"], name: str):
        catalog.save(kind, name, make_default=True)
        return {"default": name, **await devices.apply_model_list()}

    @app.delete("/models/{kind}/{name}/settings", tags=["settings"],
                summary="Put a model's settings back to the shipped ones")
    async def reset_model_settings(kind: Literal["speech", "voice", "vad"], name: str):
        catalog.save(kind, name, back_to_shipped=True)
        return {"model": name, **await devices.apply_model_list()}

    def import_view() -> dict:
        listed = catalog.load()
        root = devices.cfg["paths"]["models"]
        out = {}
        for kind in catalog.SECTIONS:
            rows = []
            for name, entry in listed[kind].items():
                shipped = catalog.shipped_entry(kind, name)
                fields = catalog.DEFINITION_FIELDS[kind]
                if kind == "speech":
                    downloaded = (root / entry["folder"]).is_dir()
                else:
                    downloaded = (root / ("speaker" if kind == "voice" else "") / entry["file"]).is_file()
                rows.append({"name": name, **{k: entry.get(k) for k in fields if k in entry},
                             "shipped": bool(shipped), "default": listed["defaults"][kind] == name,
                             "changed": bool(shipped) and any(entry.get(k) != shipped.get(k) for k in fields),
                             "shipped_entry": {k: shipped.get(k) for k in fields if k in shipped},
                             "in_use": devices.model_users(kind, name), "downloaded": downloaded})
            out[kind] = rows
        return {**out, "fields": catalog.DEFINITION_FIELDS, "file_roles": catalog.FILE_ROLES,
                "speech_kinds": sorted(catalog.SPEECH_KINDS), "vad_kinds": sorted(catalog.VAD_KINDS)}

    @app.get("/imports", tags=["settings"],
             summary="Where every model comes from: download address, files, license (the Imports page)")
    def list_imports():
        return import_view()

    @app.post("/imports/{kind}", tags=["settings"], summary="Add a model to the list (saved in data/models.yaml)")
    def add_import(kind: Literal["speech", "voice", "vad"], body: NewModelEntry):
        """fields: everything a model of this kind needs (see `fields` and `file_roles` in GET /imports).
        It's downloaded the first time a device uses it."""
        catalog.save_definition(kind, body.name, body.fields, new=True)
        return import_view()

    @app.put("/imports/{kind}/{name}", tags=["settings"],
             summary="Change where a model comes from (devices using it load it again)")
    async def change_import(kind: Literal["speech", "voice", "vad"], name: str, body: ModelEntry):
        catalog.save_definition(kind, name, body.fields)
        reloaded = await devices.reload_model(kind, name)
        return {**import_view(), "reloaded": reloaded}

    @app.delete("/imports/{kind}/{name}", tags=["settings"],
                summary="A shipped model back to models.yaml's entry; a model you added off the list")
    async def reset_import(kind: Literal["speech", "voice", "vad"], name: str):
        if not catalog.shipped_entry(kind, name):
            users = devices.model_users(kind, name)
            if users:
                raise HTTPException(status_code=409, detail=f"{name} is still used by {', '.join(users)}; "
                                                            "choose another model for them first")
        done = catalog.reset_definition(kind, name)
        reloaded = await devices.reload_model(kind, name) if done == "shipped" else []
        return {**import_view(), "done": done, "reloaded": reloaded}

    @app.post("/imports/{kind}/{name}/check", tags=["settings"],
              summary="Check that a model's download address answers (downloads nothing)")
    async def check_import(kind: Literal["speech", "voice", "vad"], name: str):
        entry = catalog.load()[kind].get(name)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No {kind} model named '{name}'")
        return await asyncio.to_thread(_check_url, entry["url"])

    @app.delete("/devices/{name}", tags=["devices"],
                summary="Remove a device (stops its port; its clips are kept)")
    async def remove_device(name: str):
        return await devices.remove(name)

    @app.get("/settings", tags=["settings"], summary="Each device's models and speaker knobs")
    def get_settings():
        return tuning.current()

    @app.patch("/settings/speaker", tags=["settings"],
               summary="Change speaker knobs now (all devices, or one with ?device=)")
    def change_speaker(body: SpeakerKnobs, device: str | None = None):
        """Leave out any value you don't want to change. Takes effect immediately
        and survives restarts. min_training_seconds: 0.5 to 10. Thresholds: 0 to 1,
        with unknown_below no higher than match_above.

        Phrases: when the voice score is from phrase_from up to phrase_to (and the voice
        says "maybe"), a habit phrase in what was said can confirm who it is, or pick
        between two people the voice found nearly tied. It never rules anyone out.
        phrase_mode: off, shadow (note in the clip what phrases would decide, change
        nothing), or on.

        trim_silence: true trims before speech-to-text with the default voice detector: a
        clip with no speech isn't decoded, and the quiet after the last speech is cut
        (keep_after_speech, its setting). Voice ID and the saved clip get the whole clip."""
        changed = tuning.update(device, body.model_dump())
        if body.hears_own_speaker and voices is not None:
            voices.start()                # the assistant's own voice, learned from her text-to-speech
        return changed

    @app.delete("/settings/speaker", tags=["settings"],
                summary="Put speaker settings back to the model's, type's and settings.yaml values (now)")
    async def reset_speaker(device: str | None = None):
        if device is not None and device not in devices.runtimes:
            raise HTTPException(status_code=404, detail=f"No device named '{device}'")
        tuning.reset(device)
        await devices.refresh_devices([device] if device else list(devices.runtimes))
        return {"reset": device or "all devices", **tuning.current()}

    @app.get("/clips", tags=["clips"], summary="Clips heard, waiting or assigned (newest first)")
    def list_clips(status: Literal["unassigned", "assigned", "all"] = "unassigned",
                   device: str | None = None, limit: int = 50, person: str | None = None):
        """person: only clips assigned to that person."""
        return store.clips(status, device, limit, person)

    @app.get("/clips/{clip_id}", tags=["clips"], summary="One clip")
    def get_clip(clip_id: str):
        return store.clip(clip_id)

    @app.get("/clips/{clip_id}/audio", tags=["clips"], summary="Play a clip (WAV)",
             response_class=FileResponse)
    def clip_audio(clip_id: str):
        return FileResponse(store.audio_path(clip_id), media_type="audio/wav")

    @app.post("/clips/{clip_id}/assign", tags=["clips"],
              summary="Assign a clip to a person (creates the profile if new)")
    def assign(clip_id: str, body: AssignBody, request: Request):
        """Who assigned it, and when, is kept with the clip: only clips a person assigned
        (not a program with a token) can retrain a voice on a device."""
        return store.assign(clip_id, body.profile, request.state.caller)

    @app.post("/clips/{clip_id}/unassign", tags=["clips"],
              summary="Take a clip back off its profile")
    def unassign(clip_id: str):
        return store.unassign(clip_id)

    @app.delete("/clips/{clip_id}", tags=["clips"], summary="Discard a clip")
    def discard(clip_id: str):
        store.discard(clip_id)
        return {"discarded": clip_id}

    @app.get("/profiles", tags=["profiles"], summary="People and how many clips each has")
    def list_profiles(all: bool = False):
        """The people. all=true: an assistant's own voice too (kind: assistant), which is never a person
        (the house router reads this list as the household's people)."""
        return store.profiles(everyone=all)

    def told(action: str, name: str, was: str | None = None) -> dict:
        """A person's change, told to the router when people are kept in step (the Wepwawet page)."""
        said = mishearings.person_changed(action, name, was) if mishearings is not None else None
        return {"wepwawet": said} if said else {}

    @app.get("/assistant-voices", tags=["profiles"], summary="The assistant voices learned from text-to-speech")
    def assistant_voices():
        """For the devices that hear their own speaker: which text-to-speech voice each answers in, and
        the assistant's profile learned from it (the last time Oread looked, and whether it's at it now)."""
        if voices is None:
            raise HTTPException(status_code=404, detail="Not running here")
        return voices.view()

    @app.post("/assistant-voices/learn", tags=["profiles"],
              summary="Learn the assistant's own voice now, from the voice each device answers in")
    def assistant_voices_learn(body: LearnBody):
        """In the background: Home Assistant says each line of voice_lines.txt in the voice. again: learn
        the voices over (the lines changed). Read GET /assistant-voices to see when it's done."""
        if voices is None:
            raise HTTPException(status_code=404, detail="Not running here")
        voices.start(body.again)
        return {**voices.view(), "learning": True}

    @app.get("/stats/time", tags=["resources"], summary="Where the time goes: each step, last 24 hours, by day, week and month")
    def stats_time(tz: str | None = None):
        """Speaking (the audio arriving), time in (waiting in line), speech to text, voice ID beyond it,
        OSPRI (none until it's built) and time to out (matching, saving, the reply), each with its count,
        median, slowest 5 percent and average, all devices and each. tz: the page's time zone (an IANA
        name, like America/New_York), so a day is the household's."""
        if times is None:
            raise HTTPException(status_code=404, detail="Not running here")
        return times.report(tz)

    @app.get("/ospri", tags=["ospri"], summary="OSPRI: whether records are gathered, how many, over which dates")
    def ospri_view():
        """OSPRI in v1.0 only gathers a record of each request and exports them; applying corrections (OSPRI lite) comes in a later version."""
        if records is None:
            raise HTTPException(status_code=404, detail="Not running here")
        return records.view()

    @app.patch("/ospri", tags=["ospri"], summary="OSPRI: gather records, or stop (kept in data/ospri.yaml)")
    def ospri_gather(body: GatherBody):
        if records is None:
            raise HTTPException(status_code=404, detail="Not running here")
        return records.set_gather(body.gather)

    @app.get("/ospri/records", tags=["ospri"], summary="OSPRI: every record, with what was meant joined in (JSON or CSV)")
    def ospri_records(format: Literal["json", "csv"] = "json"):
        """Each record: time, device, speaker, label, score, guess, by, stt_model, voice_model, heard, audio_s,
        speech_s, clip; and misheard (yes or no) and meant, from the mishearings pulled from the house router."""
        if records is None:
            raise HTTPException(status_code=404, detail="Not running here")
        rows = records.export(mishearings.view()["lines"] if mishearings is not None else [])
        if format == "csv":
            return Response(records.csv(rows), media_type="text/csv",
                            headers={"Content-Disposition": "attachment; filename=oread-ospri-records.csv"})
        return rows

    @app.get("/explore", tags=["clips"], summary="Every clip heard and every word misheard, as rows for a pivot table")
    def explore_rows():
        """clips: one row per clip heard; words: one row per word of each mishearing with what was meant
        (right, swapped, dropped or added). Each row's time is UTC; the page shows it in local time."""
        lines = mishearings.view()["lines"] if mishearings is not None else []
        return explore.rows(store.clips("all", limit=1_000_000), lines, devices.types, store.assistant_names())

    @app.post("/profiles", tags=["profiles"], summary="Create a profile")
    def create_profile(body: ProfileBody):
        made = store.create_profile(body.name, body.kind)
        return {**made, **(told("add", made["name"]) if made.get("kind", "person") == "person" else {})}

    @app.patch("/profiles/{name}", tags=["profiles"], summary="Rename a profile")
    def rename_profile(name: str, body: RenameBody):
        person = name not in store.assistant_names()
        renamed = store.rename_profile(name, body.new_name)
        store.retrain.rename_person(name, renamed["name"])
        return {**renamed, **(told("rename", renamed["name"], name) if person else {})}

    @app.delete("/profiles/{name}", tags=["profiles"],
                summary="Delete a profile (its clips go back to waiting)")
    def delete_profile(name: str):
        person = name not in store.assistant_names()
        returned = store.delete_profile(name)
        store.retrain.forget_person(name)
        return {"deleted": name, "clips_returned": returned, **(told("remove", name) if person else {})}

    # ---------- retraining one person's voice on one device ----------

    def runtime_of(device: str):
        runtime = devices.runtimes.get(device)
        if runtime is None:
            raise HTTPException(status_code=404, detail=f"No device named '{device}'")
        return runtime

    @app.get("/retrain", tags=["profiles"],
             summary="A person's clips on a device: the call each got when heard, and its score now")
    def retrain_view(device: str, person: str):
        """original: the clip's `result` (the call when heard; never changed). new_score: its score
        against the device's own voiceprint for the person (after an accepted retrain).
        trial_score: against the pending trial. A clip in a voiceprint is scored without itself."""
        return store.retrain.view(device, person, runtime_of(device).voiceprinter.model.name)

    @app.post("/retrain", tags=["profiles"],
              summary="Retrain: a trial voiceprint for a person on a device, from the ticked clips")
    def retrain_start(body: RetrainBody, request: Request):
        """clips: ids of the person's clips on the device, assigned by a person. why: optional,
        kept with it. The trial runs in shadow (live requests note what it would say) until
        accepted or rejected; today's voice ID decides meanwhile."""
        model = runtime_of(body.device).voiceprinter.model.name
        store.retrain.start(body.device, body.person, model, body.clips, body.why, request.state.caller["name"])
        return store.retrain.view(body.device, body.person, model)

    @app.get("/retrain/blind", tags=["profiles"],
             summary="Blind test: every clip on the device, who it would name with the trial")
    def retrain_blind(device: str, person: str):
        runtime = runtime_of(device)
        return store.retrain.blind(device, person, runtime.voiceprinter.model.name,
                                   runtime.unknown_below, runtime.match_above)

    @app.post("/retrain/accept", tags=["profiles"],
              summary="Accept the trial: it decides on that device from now on")
    def retrain_accept(body: TrialBody, request: Request):
        runtime_of(body.device)
        return store.retrain.accept(body.device, body.person, request.state.caller["name"])

    @app.post("/retrain/reject", tags=["profiles"], summary="Reject the trial: nothing is kept")
    def retrain_reject(body: TrialBody):
        store.retrain.reject(body.device, body.person)
        return {"rejected": True}

    @app.get("/measures", tags=["resources"],
             summary="How a device's requests sounded, newest last (kept after clips go)")
    def device_measures(device: str, limit: int = 500):
        """One line per request, with words or not: level, background, gating, clipping, the
        shape of the sound, the models, the settings period and the device's Home Assistant settings."""
        runtime_of(device)
        return {"device": device, "lines": store.measures.read(device, max(1, min(limit, 10000)))}

    @app.get("/profiles/{name}/phrases", tags=["phrases"],
             summary="A person's most-used phrases and words")
    def profile_phrases(name: str, top: int = 10):
        return {"profile": name, **top_phrases(store.transcripts(name), top),
                "habits": devices.habits.view(name)}

    return app
