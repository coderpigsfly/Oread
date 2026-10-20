"""Browser test of Oread's pages: first-run setup, sign-in, roles, theme, phone layout.

Starts its own Oread with empty, temporary data (your real data is never
touched), then drives the pages in every browser engine Playwright has here:
Chromium (Chrome, Edge), Firefox and WebKit (Safari's engine), at laptop and
phone sizes. Engines that aren't installed are skipped and reported.

    pip install playwright && playwright install chromium firefox webkit
    python3 tests/web_test.py

Stop any running Oread first (the test uses the same ports).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl
from pathlib import Path

import yaml
from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://localhost:10311"
SIZES = {"laptop": {"width": 1280, "height": 800}, "phone": {"width": 390, "height": 844}}
PASSWORD = "correct horse battery"


def start_oread(tmp: Path) -> tuple[subprocess.Popen, str]:
    settings = yaml.safe_load((ROOT / "settings.yaml").read_text())
    settings["paths"] = {"models": str(ROOT / "models"), "data": str(tmp / "data"),
                         "logs": str(tmp / "logs"), "keys": str(tmp / "keys")}
    (tmp / "settings.yaml").write_text(yaml.safe_dump(settings))
    log = open(tmp / "oread.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "oread"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "OREAD_SETTINGS": str(tmp / "settings.yaml")})
    insecure = ssl.create_default_context()
    insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE
    for _ in range(120):
        time.sleep(1)
        try:
            urllib.request.urlopen(BASE + "/api/setup", context=insecure, timeout=2)
            break
        except OSError:
            if proc.poll() is not None:
                sys.exit("Oread stopped:\n" + (tmp / "oread.log").read_text()[-2000:])
    found = re.search(r"setup code to create the super user: ([0-9A-F-]+)", (tmp / "oread.log").read_text())
    if not found:
        sys.exit("No setup code in Oread's log")
    return proc, found.group(1)


def stand_in_router():
    """A stand-in for the house router's oread door: its mishearings for the right token."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    grid = [{"person": "Master", "names": ["Master"]}]

    class Door(BaseHTTPRequestHandler):
        def _json(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):   # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.path == "/people/oread" and self.headers.get("Authorization") == "Bearer router-token":
                if body.get("action") == "add" and not any(body.get("name") in r["names"] for r in grid):
                    grid.append({"person": body["name"], "names": [body["name"]]})
                return self._json(200, {"said": f"{body.get('name')} added to the people grid", "people": grid})
            return self._json(401, {"detail": "no"})

        def do_GET(self):   # noqa: N802
            if self.path == "/people/oread":
                ok = self.headers.get("Authorization") == "Bearer router-token"
                return self._json(200 if ok else 401, {"people": grid} if ok else {"detail": "no"})
            ok = self.path == "/learn/mishearings" and self.headers.get("Authorization") == "Bearer router-token"
            body = {"router": "0.1.0", "mishearings": [
                {"meant": "add a chore", "heard": [{"said": "at a chore", "count": 2, "first": "2026-10-17 09:00",
                                                     "last": "2026-10-17 09:10", "clips": [{"clip": "20200101-000000-000-voice-pe",
                                                                                            "device": "voice-pe"}]}]},
                {"meant": None, "heard": [{"said": "are the windows hold", "count": 1}]}]} if ok else {"detail": "no"}
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Door)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def __call__(self, what: str, fn) -> None:
        try:
            fn()
            print(f"  PASS  {what}")
        except (AssertionError, PlaywrightError) as err:
            print(f"  FAIL  {what}: {str(err).splitlines()[0][:160]}")
            self.failures.append(what)


def run_engine(p, engine: str, code: str | None, check: Checks) -> None:
    if engine == "chromium":
        # a sample recording stands in for the microphone, so Try it hears real speech
        browser = p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={ROOT / 'tests' / 'audio' / 'librispeech-1.wav'}"])
    else:
        browser = getattr(p, engine).launch()
    for size_name, size in SIZES.items():
        print(f"{engine}, {size_name}:")
        context = browser.new_context(viewport=size, ignore_https_errors=True)
        page = context.new_page()
        page.on("dialog", lambda d: problems.append("a pop-up: " + d.message) or d.dismiss())   # none any more
        problems: list[str] = []
        # real problems only: script errors, content the security policy blocked, and any of the
        # page's own files failing. (Refused API calls are expected; the test causes them.)
        # (WebKit's own: any <select> on a page whose policy forbids inline styles logs "Refused to apply a
        # stylesheet", even on a page that holds nothing else; checked Oct 20. Not the page's: left out.)
        webkit_select = "Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline'"
        page.on("console", lambda m: problems.append(m.text)
                if m.type == "error" and not m.text.startswith("Failed to load resource")
                and not (engine == "webkit" and m.text.startswith(webkit_select)) else None)
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.on("response", lambda r: problems.append(f"{r.status} {r.url}")
                if "/ui/" in r.url and r.status >= 400 else None)
        page.goto(BASE + "/")

        if code:  # the very first visit: setup
            def passwords_checked_while_typing():
                expect(page.get_by_role("heading", name="Welcome to Oread")).to_be_visible()
                page.get_by_label("Password", exact=True).fill("short")
                page.get_by_label("Password again").fill("short")
                expect(page.locator("#password2-match")).to_contain_text("at least 10 characters")
                page.get_by_label("Password", exact=True).fill(PASSWORD)
                page.get_by_label("Password again").fill(PASSWORD + "x")
                expect(page.locator("#password2-match")).to_contain_text("don't match")
                page.get_by_label("Password again").fill(PASSWORD)
                expect(page.locator("#password2-match")).to_contain_text("Passwords match")
            check("passwords: too short, don't match, match, shown while typing", passwords_checked_while_typing)

            def setup_wrong_code():
                expect(page.get_by_role("heading", name="Welcome to Oread")).to_be_visible()
                page.get_by_label("Setup code").fill("AAAA-BBBB-CCCC")
                page.get_by_label("Your username").fill("sam")
                page.get_by_label("Password", exact=True).fill(PASSWORD)
                page.get_by_label("Password again").fill(PASSWORD)
                page.get_by_role("button", name="Create the super user").click()
                expect(page.get_by_role("alert")).to_contain_text("setup code isn't right")
            check("setup refuses a wrong code", setup_wrong_code)

            def setup_right_code():
                page.get_by_label("Setup code").fill(code)
                page.get_by_role("button", name="Create the super user").click()
                expect(page.get_by_role("heading", name="Account")).to_be_visible()
            check("setup with the code from the log makes the super user", setup_right_code)
            code = None
        else:
            def sign_in():
                expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
                page.get_by_label("Username").fill("Sam")      # any capitalisation
                page.get_by_label("Password").fill(PASSWORD)
                page.get_by_role("button", name="Sign in").click()
                expect(page.locator(".main h1")).to_be_visible()
            check("sign in", sign_in)

        def nav_for_super():
            if size_name == "phone":
                expect(page.locator(".side")).to_be_hidden()
                page.get_by_role("button", name="Menu").click()
            nav = page.locator(".nav a")
            expect(nav).to_have_text(["Learn", "People", "Mishearings", "Explore", "OSPRI", "Wepwawet", "Devices", "Settings", "Imports", "Connections",
                                      "Try it", "Stats", "Users", "Account", "Setup guide"])
        check("super user sees every page" + (" (menu folds on a phone)" if size_name == "phone" else ""),
              nav_for_super)

        def theme():
            page.goto(BASE + "/ui/#/account")
            page.get_by_label("Dark").check()
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            page.reload()
            assert page.evaluate("document.documentElement.dataset.theme") == "dark", "not remembered"
            page.get_by_label("Follow this device").check()
            assert page.evaluate("document.documentElement.dataset.theme") is None
        check("theme: dark, remembered, back to following the device", theme)

        def permitted_addresses():
            page.goto(BASE + "/ui/#/connections")
            panel = page.locator("#permitted")
            expect(panel.get_by_text("Open to your whole network")).to_be_visible()
            panel.get_by_label("Add an address or range").fill("10.0.0.5")
            panel.get_by_role("button", name="Add", exact=True).click()
            expect(panel.locator(".rows").first).to_contain_text("10.0.0.5")
            expect(panel.get_by_text("Open to your whole network")).to_be_hidden()
            panel.get_by_label("Add an address or range").fill("not an address")
            panel.get_by_role("button", name="Add", exact=True).click()
            expect(panel.get_by_role("alert")).to_contain_text("isn't an address")
            # a satellite port turns this computer away now, and the page offers to let it in
            import socket
            with socket.create_connection(("127.0.0.1", 10310), timeout=5) as sock:
                sock.settimeout(5)
                try:
                    sock.recv(1)
                except OSError:
                    pass
            page.reload()
            expect(panel.locator("li", has_text="on laptop").first).to_be_visible()
            panel.locator("li", has_text="on laptop").first.get_by_role("button", name="Allow").click()
            expect(panel.locator(".rows").first).to_contain_text("127.0.0.1")
            panel.get_by_role("button", name="Remove 10.0.0.5").click()
            panel.get_by_role("button", name="Remove 127.0.0.1").click()
            expect(panel.get_by_text("Open to your whole network")).to_be_visible()
            expect(page.locator("#certificate").get_by_role("link", name="Download the certificate")).to_be_visible()
        check("Connections: add, refuse, allow, remove addresses; certificate download", permitted_addresses)

        def mishearings_from_the_router():
            router = stand_in_router()
            page.goto(BASE + "/ui/#/mishearings")
            box = page.locator("#router")
            expect(box).to_contain_text("Not set up")
            expect(box.get_by_role("button", name="Pull from the router")).to_be_disabled()
            page.goto(BASE + "/ui/#/wepwawet")          # the address and token live on the Wepwawet page now
            box = page.locator("#router")
            expect(box).to_contain_text("not set: off")
            box.get_by_label("The router's address").fill("not an address")
            box.get_by_role("button", name="Save").first.click()
            expect(page.get_by_role("alert")).to_contain_text("like http://")
            box.get_by_label("The router's address").fill(f"http://127.0.0.1:{router.server_port}")
            box.get_by_role("button", name="Save").first.click()
            expect(page.locator("#router dd").first).to_contain_text(f"127.0.0.1:{router.server_port}")   # redrawn
            expect(page.locator("#router")).to_contain_text("data/wepwawet.yaml")
            page.locator("#router").get_by_label("Its token").fill("router-token")
            page.locator("#router").get_by_role("button", name="Save").nth(1).click()
            expect(page.locator("#router")).to_contain_text("in the vault as wepwawet")
            # people in step: Oread's people beside the router's, the missing ones added
            people = page.locator("details", has=page.get_by_role("heading", name="People", exact=True))
            expect(people).to_contain_text("Master")
            people.get_by_label("Keep people in step").check()
            expect(people.get_by_label("Keep people in step")).to_be_checked()
            page.goto(BASE + "/ui/#/mishearings")
            page.locator("#router").get_by_role("button", name="Pull from the router").click()
            expect(page.locator("#router")).to_contain_text(re.compile(r"2 lines \(\d new"))
            table = page.locator(".clips-table")
            expect(table.locator("tbody tr")).to_have_count(2)
            expect(table).to_contain_text("at a chore")
            expect(table).to_contain_text("not given yet")
            expect(table.locator("tr", has_text="at a chore")).to_contain_text("not here")
            router.shutdown()
            # back as it was, for the next browser and size: no address, no token
            page.goto(BASE + "/ui/#/wepwawet")
            page.locator("#router").get_by_label("The router's address").fill("")
            page.locator("#router").get_by_role("button", name="Save").first.click()
            expect(page.locator("#router")).to_contain_text("not set: off")       # redrawn before the next change
            in_step = page.locator("details", has=page.get_by_role("heading", name="People", exact=True)).get_by_label("Keep people in step")
            in_step.uncheck()
            expect(in_step).not_to_be_checked()
            assert page.evaluate("async () => (await fetch('/vault/wepwawet', {method: 'DELETE', credentials: 'same-origin', "
                                 "headers: {'X-Requested-With': 'oread'}})).status") == 200
        check("Wepwawet and Mishearings: the router's address and token, people in step, Pull, the lines in a table",
              mishearings_from_the_router)

        def her_own_voice_patch():
            page.goto(BASE + "/ui/#/people")
            expect(page.locator("main")).not_to_contain_text("her own voice")     # People is people only
            page.goto(BASE + "/ui/#/settings?tab=devices")
            card = page.locator("details.device-set").first
            card.evaluate("e => e.open = true")
            voice = card.locator(".her-voice")
            expect(voice).to_contain_text("Not learned for this device yet")
            expect(voice.get_by_text("Learning now")).to_be_hidden()               # only while it's learning
            voice.locator("details.by-hand").evaluate("e => e.open = true")
            voice.get_by_label("Add an assistant's voice by hand").fill("Test voice " + engine + str(page.viewport_size["width"]))
            voice.get_by_role("button", name="Add the voice").click()
            card = page.locator("details.device-set").first
            card.evaluate("e => e.open = true")
            voice = card.locator(".her-voice")
            voice.locator("details.by-hand").evaluate("e => e.open = true")
            expect(voice).to_contain_text("Test voice " + engine)
            expect(page.get_by_text("Patch: a device that hears itself").first).to_be_visible()
            page.goto(BASE + "/ui/#/people")
            expect(page.locator(".person[data-person^='Test voice']")).to_have_count(0)      # never a person
            page.goto(BASE + "/ui/#/settings?tab=devices")
            card = page.locator("details.device-set").first
            card.evaluate("e => e.open = true")
            voice = card.locator(".her-voice")
            voice.locator("details.by-hand").evaluate("e => e.open = true")
            voice.get_by_role("button", name="Delete").first.click()
            page.get_by_role("button", name=re.compile("^Delete Test voice")).click()
            card = page.locator("details.device-set").first
            card.evaluate("e => e.open = true")
            expect(card.locator(".her-voice summary")).to_contain_text("By hand (0)")
        check("Settings, Devices: the patch for a device that hears itself, her voice beside its switch (never on People)",
              her_own_voice_patch)

        def explore_page():
            page.goto(BASE + "/ui/#/explore")
            expect(page.locator("#pivot table.pvtTable")).to_be_visible(timeout=15000)
            expect(page.locator("#pivot")).to_contain_text("Share that are yes")
            expect(page.get_by_text(re.compile(r"^\d+ rows\."))).to_be_visible()
            page.get_by_role("tab", name="Words misheard").click()
            expect(page.get_by_role("tab", name="Words misheard")).to_have_attribute("aria-selected", "true")
            expect(page.locator("#pivot table.pvtTable")).to_be_visible()
            page.get_by_role("button", name="Start the layout over").click()
            expect(page.locator("#pivot select.pvtRenderer")).to_have_value("Table")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "sideways scroll"
        check("Explore: the pivot table of clips and of misheard words, no sideways scroll", explore_page)

        def time_goes():
            page.goto(BASE + "/ui/#/stats?tab=time")
            expect(page.get_by_role("tab", name="Where the time goes")).to_have_attribute("aria-selected", "true")
            out = page.locator("main .table-wrap table")
            expect(out.locator("thead")).to_contain_text("Speech to text")
            expect(out.locator("tbody tr")).to_have_count(14)                           # by day: two weeks
            page.get_by_label("Period").select_option("month")
            expect(out.locator("tbody tr")).to_have_count(12)
            page.get_by_label("Period").select_option("last_24_hours")
            expect(out.locator("tbody tr").first).to_contain_text("Last 24 hours")
            expect(out.locator("tbody tr").first).to_contain_text("not built yet")      # OSPRI, until it's built
            page.get_by_label("Show").select_option("p95")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "sideways scroll"
        check("Stats, where the time goes: by step, last 24 hours, day, week, month", time_goes)

        def ospri_page():
            page.goto(BASE + "/ui/#/ospri")
            box = page.locator("#ospri-records")
            expect(box).to_contain_text("Records")
            gather = box.get_by_label("Gather records")
            gather.check()
            expect(page.locator("#ospri-records").get_by_label("Gather records")).to_be_checked()
            assert page.evaluate("async () => (await (await fetch('/ospri', {headers: {'X-Requested-With': 'oread'}})).json()).gather")
            expect(page.get_by_role("link", name="Export CSV")).to_have_attribute("href", "/ospri/records?format=csv")
            got = page.evaluate("async () => (await fetch('/ospri/records?format=csv', {headers: {'X-Requested-With': 'oread'}})).text()")
            assert got.startswith("time,device,speaker"), got[:40]
            page.locator("#ospri-records").get_by_label("Gather records").uncheck()
            expect(page.locator("#ospri-records").get_by_label("Gather records")).not_to_be_checked()
        check("OSPRI: gather records on and off, export", ospri_page)

        def sample_household():
            if engine != "chromium" or size_name != "laptop":
                return   # adding sends every clip through the models: once is enough
            page.goto(BASE + "/ui/#/settings?tab=sample")
            box = page.locator("#sample-household")
            expect(box).to_contain_text("Here now")
            page.get_by_role("button", name="Add the sample household").click()
            expect(page.get_by_role("button", name="Remove the sample household")).to_be_visible(timeout=300000)
            expect(page.locator("#sample-household")).to_contain_text("Sample Ada, Sample Ben")
            page.goto(BASE + "/ui/#/people")
            expect(page.locator("article.person", has_text="Sample Ada")).to_be_visible()
            page.goto(BASE + "/ui/#/learn")
            expect(page.locator("tr.clip").first).to_be_visible()
            page.goto(BASE + "/ui/#/settings?tab=sample")
            page.get_by_role("button", name="Remove the sample household").click()
            page.get_by_role("button", name="Remove", exact=True).click()       # asked in place
            expect(page.get_by_role("button", name="Add the sample household")).to_be_visible(timeout=60000)
            got = page.evaluate("async () => { const h = {headers: {'X-Requested-With': 'oread'}};"
                                " return [await (await fetch('/sample', h)).json(), await (await fetch('/profiles?all=true', h)).json(),"
                                " await (await fetch('/clips?status=all', h)).json()]; }")
            assert not got[0]["added"] and got[0]["clips"] == 0, got[0]
            assert not [p for p in got[1] if p["name"].startswith("Sample ")], got[1]
            clips = got[2]["clips"] if isinstance(got[2], dict) else got[2]
            assert not [c for c in clips if c.get("sample")], clips
        check("Sample household: add from Settings, see it on People and Learn, remove it and nothing's left", sample_household)

        def try_it():
            if engine != "chromium":
                return   # only Chromium can stand a recording in for the microphone
            page.goto(BASE + "/ui/#/try")
            page.get_by_role("button", name="Start speaking").click()
            expect(page.get_by_role("button", name="Stop")).to_be_visible()
            page.wait_for_timeout(4500)
            page.get_by_role("button", name="Stop").click()
            expect(page.locator(".result .heard")).to_be_visible(timeout=60000)
            heard = page.locator(".result .heard").inner_text()
            assert len(heard) > 10 and "No words" not in heard, heard
            expect(page.locator(".result")).to_contain_text("Saved to Learn")
        check("Try it: speak (a recording as the microphone), see the words", try_it)

        def review_and_learn():
            if engine != "chromium":
                return   # needs the Try it clip above
            page.goto(BASE + "/ui/#/learn")
            page.get_by_text("What's worth teaching?").click()
            expect(page.get_by_text("Teach the clips Oread was unsure about.")).to_be_visible()
            card = page.locator("tr.clip").first
            expect(card).to_be_visible()
            expect(card.locator(".words")).not_to_be_empty()
            page.get_by_role("button", name="Length").click()                  # a heading sorts the table
            expect(page.locator("th[aria-sort=ascending]")).to_contain_text("Length")
            page.get_by_role("button", name=re.compile("^Length")).click()      # again: reversed
            expect(page.locator("th[aria-sort=descending]")).to_contain_text("Length")
            card.get_by_label("Who was speaking").select_option(label="New person…")
            card.get_by_label("New person's name").fill("Phoebe")
            card.get_by_role("button", name="Assign").click()
            expect(card).to_contain_text("Assigned to Phoebe.")
            card.get_by_role("button", name="Undo").click()      # changed my mind
            card = page.locator("tr.clip").first
            expect(card.get_by_role("button", name="Assign")).to_be_visible()
            card.get_by_label("Who was speaking").select_option(label="Phoebe")
            card.get_by_role("button", name="Assign").click()
            expect(card).to_contain_text("Assigned to Phoebe.")
            page.get_by_role("tab", name="Assigned").click()
            expect(page.locator("tr.clip").first).to_contain_text("Assigned to Phoebe")
            # Oread now knows the voice: the same speaker through Try it is named
            page.goto(BASE + "/ui/#/try")
            page.get_by_role("button", name="Start speaking").click()
            page.wait_for_timeout(4500)
            page.get_by_role("button", name="Stop").click()
            expect(page.locator(".result")).to_contain_text("Phoebe", timeout=60000)
            expect(page.locator(".result .status")).to_have_text("Known")
            # tidy up: discard the new clip from the waiting list
            page.goto(BASE + "/ui/#/learn")
            first = page.locator("tr.clip").first.get_attribute("data-clip")
            page.locator("tr.clip").first.get_by_label("Tick to discard").check()
            page.get_by_role("button", name="Discard ticked (1)").click()
            page.get_by_role("button", name="Discard", exact=True).click()       # asked in place, not a pop-up
            expect(page.locator(".main")).to_contain_text("Discarded 1 clip.")
            expect(page.locator(f"tr.clip[data-clip='{first}']")).to_have_count(0)
        check("Learn: assign to a new person, undo, assign; Try it then names them", review_and_learn)

        def people():
            page.goto(BASE + "/ui/#/people")
            if engine == "chromium":   # Phoebe was learned above
                tile = page.locator("article.person", has_text="Phoebe")
                expect(tile).to_contain_text("Learning:")
                tile.get_by_role("link", name="See clips").click()
                expect(page.locator(".main")).to_contain_text("Only Phoebe's clips")
                expect(page.locator("tr.clip").first).to_contain_text("Assigned to Phoebe")
                page.goto(BASE + "/ui/#/people")
            name = "Sam " + size_name
            page.get_by_label("Add a person").fill(name)
            page.get_by_role("button", name="Add", exact=True).click()
            tile = page.locator("article.person", has_text=name)
            expect(tile).to_contain_text("Not learned yet")
            tile.get_by_role("button", name="Rename").click()
            page.get_by_label("New name for " + name).fill(name.upper())     # capitals only
            page.get_by_role("button", name="Save").click()
            tile = page.locator("article.person", has_text=name.upper())
            expect(tile.locator("h2")).to_have_text(name.upper())
            tile.get_by_role("button", name="Delete").click()
            tile.get_by_role("button", name="Delete " + name.upper()).click()  # asked in place
            expect(page.locator("article.person", has_text=name.upper())).to_have_count(0)
        check("People: add, rename (capitals only), see clips, delete", people)

        def retrain():
            if engine != "chromium":
                return   # needs Phoebe's clip from Try it above
            device = page.evaluate("async () => (await (await fetch('/clips?status=assigned&person=Phoebe')).json())[0].device")
            page.goto(BASE + "/ui/#/people")
            page.get_by_role("tab", name="Retrain").click()
            page.get_by_label("Person").select_option("Phoebe")
            page.get_by_label("Device").select_option(device)
            row = page.locator("tr.clip").first
            expect(row).to_contain_text("Take back")
            page.get_by_role("button", name="When").click()                       # the table sorts
            expect(page.locator("th[aria-sort]").filter(has_text="When")).to_have_attribute("aria-sort", "ascending")
            page.get_by_role("button", name="Tick all").click()
            page.get_by_label("Why (optional)").fill("a test")
            page.get_by_role("button", name="Retrain", exact=True).click()
            expect(page.get_by_role("heading", name="Blind test")).to_be_visible(timeout=30000)
            expect(page.locator(".trial")).to_contain_text("Phoebe's clips named Phoebe")
            expect(page.locator(".verdict")).to_contain_text("Overall:")              # better, worse, mixed or no change
            page.locator(".blind-clips th button", has_text="Phoebe's score").click()   # sorts by how far the score moved
            expect(page.locator(".blind-clips th[aria-sort=ascending]")).to_contain_text("Phoebe's score")
            page.get_by_role("button", name="Reject").click()
            page.get_by_role("button", name="Cancel").click()                     # changed my mind: nothing happens
            page.get_by_role("button", name="Reject").click()
            page.get_by_role("button", name="Reject").click()                     # asked in place: yes
            expect(page.get_by_role("heading", name="Blind test")).to_have_count(0)
            page.get_by_role("button", name="Tick all").click()
            page.get_by_role("button", name="Retrain", exact=True).click()
            page.get_by_role("button", name="Accept").click()
            expect(page.locator(".main")).to_contain_text("In use")
            expect(page.locator(".main")).to_contain_text("Why: a test")
        check("People, Retrain: tick, retrain, blind test with a verdict and sorting, reject; again and accept", retrain)

        def devices():
            import socket
            page.goto(BASE + "/ui/#/devices")
            expect(page.locator(".where")).to_contain_text("localhost")
            tile_named = lambda n: page.locator("article.device").filter(has=page.get_by_role("heading", name=n, exact=True))
            laptop = tile_named("laptop")
            expect(laptop.locator(".port")).to_have_text("10310")
            expect(laptop.get_by_role("button", name="Copy localhost:10310")).to_be_visible()
            name = "kitchen-" + size_name
            page.get_by_label("Name", exact=True).fill(name)
            page.get_by_label("Type").select_option("voice-pe")
            page.get_by_role("button", name="Add device").click()
            expect(page.get_by_role("status").filter(has_text="is listening on port")).to_be_visible(timeout=60000)
            tile = tile_named(name)
            port = int(tile.locator(".port").inner_text())
            socket.create_connection(("127.0.0.1", port), timeout=5).close()     # really listening
            expect(tile).to_contain_text("Speech: Moonshine (default)")
            expect(tile.get_by_role("button", name="Models")).to_have_count(0)  # models are chosen on Settings only
            tile.get_by_role("link", name="Settings").click()                 # Settings, Devices, at this device
            card = page.locator(f".device-set[data-device={name}]")
            card.get_by_label("Speech model").select_option(label="Zipformer · about 170 MB")
            expect(card.locator(".model-note").first).to_contain_text("more memory")
            card.get_by_role("button", name="Save").click()
            card = page.locator(f".device-set[data-device={name}]")
            expect(card.locator(".ok")).to_contain_text("Saved", timeout=60000)
            socket.create_connection(("127.0.0.1", port), timeout=5).close()     # listening again
            card.get_by_label("Person named at").evaluate(
                "e => { e.value = '0.6'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
            card.get_by_role("button", name="Save").click()
            card = page.locator(f".device-set[data-device={name}]")
            expect(card).to_contain_text("Set for this device")
            live = page.evaluate(f"async () => (await (await fetch('/settings')).json())['{name}'].match_above")
            assert live == 0.6, live
            card.get_by_label("Trim the quiet after speech").check()             # a switch per device
            card.get_by_role("button", name="Save").click()
            card = page.locator(f".device-set[data-device={name}]")
            expect(card.locator(".ok")).to_contain_text("Saved", timeout=60000)
            live = page.evaluate(f"async () => (await (await fetch('/settings')).json())['{name}'].trim_silence")
            assert live is True, live
            card.locator(":scope > summary").click()                                     # the box folds
            assert not card.evaluate("e => e.open")
            card.locator(":scope > summary").click()
            card.get_by_role("button", name="Back to defaults").click()
            card = page.locator(f".device-set[data-device={name}]")
            expect(card.get_by_label("Person named at")).to_have_value("0.55")
            card.get_by_label("Speech model").select_option(value="")           # back to the default
            card.get_by_role("button", name="Save").click()
            expect(page.locator(f".device-set[data-device={name}] .ok")).to_contain_text("Saved", timeout=60000)
            page.goto(BASE + "/ui/#/devices")
            tile = tile_named(name)
            expect(tile).to_contain_text("Speech: Moonshine (default)", timeout=60000)
            tile.get_by_role("button", name="Rename").click()
            page.get_by_label("New name for " + name).fill("pantry-" + size_name)
            page.get_by_role("button", name="Save").click()
            tile = tile_named("pantry-" + size_name)
            expect(tile.locator(".port")).to_have_text(str(port))               # same port after renaming
            tile.get_by_role("button", name="Remove").click()
            tile.get_by_role("button", name="Remove pantry-" + size_name).click()   # asked in place
            expect(tile_named("pantry-" + size_name)).to_have_count(0)
            try:
                socket.create_connection(("127.0.0.1", port), timeout=2).close()
                raise AssertionError(f"port {port} still listening after removing the device")
            except ConnectionRefusedError:
                pass
        check("Devices: ports, add (really listens); Settings, Devices: change model and back, a knob and back; "
              "rename (same port), remove", devices)

        def device_types():
            page.goto(BASE + "/ui/#/devices")
            panel = page.locator("#device-types")
            expect(panel).to_contain_text("Home Assistant Voice PE")
            expect(page.locator("article.device[data-device=voice-pe] .badge")).to_have_text("Home Assistant Voice PE")
            android = panel.locator("li[data-type=android]")
            expect(android).to_contain_text("used by tablet")
            expect(android.get_by_role("button", name="Remove")).to_be_disabled()     # in use
            name, label = "den-" + size_name, "Den satellite " + size_name
            panel.get_by_text("Add a type").click()
            panel.get_by_label("Label").fill(label)
            panel.get_by_label("Short name").fill(name)
            panel.get_by_label("Voice model").select_option("titanet-small")
            panel.get_by_role("button", name="Add type").click()
            row = page.locator(f"#device-types li[data-type={name}]")
            expect(row).to_contain_text("voice: TitaNet")
            expect(page.locator("#new-device-type option", has_text=label)).to_have_count(1)   # offered at once
            row.get_by_role("button", name="Rename").click()
            row.get_by_label("Label for " + name).fill("Den speaker " + size_name)
            row.get_by_role("button", name="Save").click()
            row = page.locator(f"#device-types li[data-type={name}]")
            expect(row).to_contain_text("Den speaker " + size_name)
            row.get_by_role("button", name="Remove").click()
            row.get_by_role("button", name="Remove").click()                       # asked in place: yes
            expect(page.locator(f"#device-types li[data-type={name}]")).to_have_count(0)
        check("Device types: labels on tiles, add with a model, offered at once, rename, remove; in use can't go",
              device_types)

        def model_settings():
            if size_name == "phone" and engine != "chromium":
                return
            page.goto(BASE + "/ui/#/settings")
            expect(page.locator(".main")).to_contain_text("Speech models")
            titanet = page.locator("article.model[data-kind=voice][data-model=titanet-small]")
            expect(titanet.locator(".badge")).to_have_text("Default")
            named_at = titanet.get_by_label("Person named at")
            expect(named_at).to_have_value("0.55")
            named_at.evaluate("e => { e.value = '0.6'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
            titanet.get_by_role("button", name="Save").click()
            titanet = page.locator("article.model[data-kind=voice][data-model=titanet-small]")
            expect(titanet.locator(".ok")).to_contain_text("Saved")
            expect(titanet).to_contain_text("Shipped: 0.55")
            live = page.evaluate("async () => (await (await fetch('/settings')).json()).laptop.match_above")
            assert live == 0.6, live                                   # in use at once
            titanet.get_by_role("button", name="Back to shipped").click()
            titanet = page.locator("article.model[data-kind=voice][data-model=titanet-small]")
            expect(titanet.get_by_label("Person named at")).to_have_value("0.55")
            live = page.evaluate("async () => (await (await fetch('/settings')).json()).laptop.match_above")
            assert live == 0.55, live
            camp = page.locator("article.model[data-kind=voice][data-model=campplus-en]")
            camp.get_by_role("button", name="Make default").click()
            expect(page.locator("article.model[data-kind=voice][data-model=campplus-en] .badge")).to_have_text(
                "Default", timeout=120000)
            used = page.evaluate("async () => (await (await fetch('/settings')).json()).laptop.speaker_model")
            assert used == "campplus-en", used                         # devices without their own choice switched
            page.locator("article.model[data-kind=voice][data-model=titanet-small]").get_by_role(
                "button", name="Make default").click()
            expect(page.locator("article.model[data-kind=voice][data-model=titanet-small] .badge")).to_have_text(
                "Default", timeout=120000)
            expect(page.locator("article.model[data-kind=vad][data-model=silero-vad]")).to_contain_text("Silero VAD")
        check("Settings, Models: a model's settings saved and in use at once, back to shipped, make default",
              model_settings)

        def imports():
            if size_name != "laptop":
                return
            page.goto(BASE + "/ui/#/imports")
            pills = page.locator(".pills")
            expect(pills.get_by_role("button", name="Moonshine")).to_have_attribute("aria-pressed", "true")
            pills.get_by_role("button", name="Parakeet").click()
            card = page.locator("section.import")
            expect(card.get_by_label("Download address")).to_have_value(re.compile(r"^https://.*parakeet"))
            expect(card.get_by_label("encoder", exact=True)).to_have_value("encoder.int8.onnx")
            card.get_by_label("What to expect").fill("Changed by the test.")
            card.get_by_role("button", name="Save").click()
            card = page.locator("section.import")
            expect(card.locator(".ok")).to_contain_text("Saved")
            expect(card).to_contain_text("Shipped, changed by you")
            card.get_by_role("button", name="Back to shipped").click()
            expect(page.locator("section.import")).to_contain_text("Shipped with Oread")
            page.get_by_role("tab", name="Voice models").click()
            pills.get_by_role("button", name="+ Add a model").click()
            card = page.locator("section.import")
            card.get_by_label("Short name").fill("test-voice")
            card.get_by_label("Name shown on the pages").fill("Test voice")
            card.get_by_label("Download address").fill("https://example.com/test-voice.onnx")
            card.get_by_label("File name").fill("test-voice.onnx")
            card.get_by_role("button", name="Add model").click()
            expect(pills.get_by_role("button", name="Test voice")).to_have_attribute("aria-pressed", "true")
            page.locator("section.import").get_by_role("button", name="Remove").click()
            page.locator("section.import").get_by_role("button", name="Remove").click()   # asked in place: yes
            expect(pills.get_by_role("button", name="Test voice")).to_have_count(0)
            page.get_by_role("tab", name="Voice detectors").click()
            expect(pills.get_by_role("button", name="Silero VAD")).to_be_visible()
        check("Imports: a pill per model; change one and back; add and remove a voice model", imports)

        def setup_guide():
            page.goto(BASE + "/ui/#/guide")
            guide = page.locator("article.guide")
            expect(guide.locator("h1")).to_have_text("Oread user guide")
            guide.get_by_role("link", name="Install", exact=True).first.click()
            expect(page).to_have_url(re.compile(r"#/guide\?at=2-install$"))
            expect(page.locator("#g-2-install")).to_be_in_viewport()
            expect(guide.locator("table").first).to_be_visible()                   # tables drawn as tables
            expect(guide).not_to_contain_text("```")                               # no raw Markdown left
            expect(guide).not_to_contain_text("](#")
            page.goto(BASE + "/ui/#/guide?at=appendix-a-example-connecting-home-assistant")
            expect(page.locator("#g-appendix-a-example-connecting-home-assistant")).to_be_in_viewport()
        check("Setup guide: the user guide in the page, contents links jump, nothing raw", setup_guide)

        def refusals():
            result = page.evaluate("""async () => {
                const r = await fetch('/devices/laptop', {method: 'PATCH', credentials: 'same-origin',
                  headers: {'X-Requested-With': 'oread', 'Content-Type': 'application/json'},
                  body: JSON.stringify({stt_model: 'no-such-model'})});
                const token = await fetch('/status?token=oread_abc', {credentials: 'omit'});
                const old1 = await fetch('/phrases', {credentials: 'same-origin'});
                const old2 = await fetch('/resources/page', {credentials: 'same-origin'});
                return [r.status, (await r.json()).detail, token.status, old1.status, old2.status];
            }""")
            status, detail, token_status, old1, old2 = result
            assert status == 400 and "Unknown speech model 'no-such-model'" in detail, result
            assert token_status == 401, result                     # a token only counts in the header
            assert old1 == 404 and old2 == 404, result             # the old browser pages are gone
        check("refusals: a bad model is refused with its reason; no ?token=; old pages gone", refusals)

        def compare():
            if engine != "chromium":
                return   # needs the Try it clips made above
            page.goto(BASE + "/ui/#/devices")
            tile_named = lambda n: page.locator("article.device").filter(has=page.get_by_role("heading", name=n, exact=True))
            tile_named("laptop").get_by_role("button", name="Compare").click()
            panel = page.locator("#compare")
            expect(panel).to_contain_text("Compare models: laptop")
            panel.get_by_label("The words (speech model)").check()
            panel.get_by_label("Model to try").select_option(label="Zipformer")
            panel.get_by_role("button", name="Start comparing").click()
            expect(panel).to_contain_text("heard the same words", timeout=120000)
            if panel.locator("tr.clip").count():
                panel.locator("tr.clip").first.get_by_role("button", name="Moonshine was right").click()
                expect(panel.locator(".tally")).to_contain_text("Moonshine right 1")
            expect(panel.get_by_role("button", name="Use Zipformer for laptop")).to_be_visible()
            page.goto(BASE + "/ui/#/people")                                 # away and back: still there
            page.goto(BASE + "/ui/#/devices")
            expect(page.locator("#compare")).to_contain_text("heard the same words")
            page.locator("#compare").get_by_role("button", name="Close the comparison").click()
            expect(page.locator("#compare")).to_be_hidden()
            page.goto(BASE + "/ui/#/people")                                 # put away for good
            page.goto(BASE + "/ui/#/devices")
            expect(page.locator("article.device").first).to_be_visible()
            expect(page.locator("#compare")).to_be_hidden()
        check("Compare: side by side on the device's own clips, judge one; X puts it away for good", compare)

        def add_reviewer():
            page.goto(BASE + "/ui/#/users")
            expect(page.locator("li[data-user=sam]")).to_be_visible()          # the list has loaded
            panel = page.locator("#add-user")
            if page.locator("li[data-user=ann]").count() == 0:          # made by an earlier size or engine
                panel.get_by_label("Username").fill("ann")
                panel.get_by_label("Role").select_option("reviewer")
                panel.get_by_label("Password", exact=True).fill("lisas-password-1")
                panel.get_by_label("Password again").fill("lisas-password-1")
                panel.get_by_role("button", name="Add user").click()
                expect(panel.locator(".ok")).to_contain_text("ann can sign in now, as a reviewer")
            expect(page.locator("li[data-user=ann] .badge")).to_have_text("reviewer")
            # a throwaway user: change the role, reset the password, remove
            temp = "temp-" + size_name
            panel = page.locator("#add-user")
            panel.get_by_label("Username").fill(temp)
            panel.get_by_label("Role").select_option("viewer")
            panel.get_by_label("Password", exact=True).fill("temporary-pass-1")
            panel.get_by_label("Password again").fill("temporary-pass-1")
            panel.get_by_role("button", name="Add user").click()
            row = page.locator(f"li[data-user={temp}]")
            expect(row.locator(".badge")).to_have_text("viewer")
            row.get_by_role("button", name="Role").click()
            row.get_by_label("Role for " + temp).select_option("administrator")
            row.get_by_role("button", name="Save").click()
            expect(page.locator(f"li[data-user={temp}] .badge")).to_have_text("administrator")
            row = page.locator(f"li[data-user={temp}]")
            row.get_by_role("button", name="Reset password").click()
            row.get_by_label("New password for " + temp).fill("another-pass-22")
            row.get_by_label("New password again").fill("another-pass-22")
            row.get_by_role("button", name="Reset password").click()
            row = page.locator(f"li[data-user={temp}]")
            expect(row.get_by_role("button", name="Role")).to_be_visible()
            row.get_by_role("button", name="Remove").click()
            row.get_by_role("button", name="Remove " + temp).click()           # asked in place
            expect(page.locator(f"li[data-user={temp}]")).to_have_count(0)
            expect(page.locator("li[data-user=sam]")).to_contain_text("(you)")
            expect(page.locator(".main")).not_to_contain_text("null")             # no empty slot shown as text
            page.get_by_role("tab", name="Audit log").click()
            expect(page.locator("table.audit")).to_contain_text("user deleted")
        check("Users: add Ann as a reviewer; add, change role, reset password, remove; audit log", add_reviewer)

        def sign_out_and_in_as_reviewer():
            page.goto(BASE + "/ui/#/account")
            page.get_by_role("button", name="Sign out").click()
            expect(page.get_by_text("You're signed out.")).to_be_visible()
            page.get_by_label("Username").fill("ann")
            page.get_by_label("Password").fill("lisas-password-1")
            page.get_by_role("button", name="Sign in").click()
            if size_name == "phone":
                page.get_by_role("button", name="Menu").click()
            expect(page.locator(".nav a")).to_have_text(
                ["Learn", "People", "Mishearings", "Explore", "OSPRI", "Devices", "Settings", "Imports", "Try it", "Stats", "Account", "Setup guide"])
        check("reviewer: no Connections or Users pages", sign_out_and_in_as_reviewer)

        def reviewer_blocked_from_vault():
            status = page.evaluate("async () => (await fetch('/vault', {credentials: 'same-origin'})).status")
            assert status == 403, status
        check("reviewer can't read the vault", reviewer_blocked_from_vault)

        def api_description_says_how_it_fits_the_router():
            w = page.evaluate("async () => (await (await fetch('/openapi.json', {credentials: 'same-origin'})).json())['x-wepwawet']")
            assert w and w["version"] == 1 and w["tabs"]["voice_map"] is False, w
            assert "who_spoke" in w["offers"] and w["lists"]["people"]["from"] == "GET /profiles", w
            paths = page.evaluate("async () => Object.keys((await (await fetch('/openapi.json', {credentials: 'same-origin'})).json()).paths)")
            assert "/profiles" in paths, paths                 # its people list is one of its own commands
        check("the API description carries its x-wepwawet section (the Wepwawet standard)", api_description_says_how_it_fits_the_router)

        def stats_in_the_page():
            page.goto(BASE + "/ui/#/stats")
            expect(page.locator(".stat").first).to_contain_text("Memory")
            expect(page.locator(".main")).to_contain_text("Speed by device")
            expect(page.locator(".side")).to_be_attached()                      # the menu is still there
            box = lambda: page.locator("details.fold", has_text="Speed by device")
            box().locator("summary").click()                                     # a box folds...
            assert not box().evaluate("e => e.open")
            page.reload()
            expect(page.locator(".main")).to_contain_text("Speed by device")
            assert not box().evaluate("e => e.open")                              # ...and stays folded
            box().locator("summary").click()
            assert box().evaluate("e => e.open")
            page.get_by_role("tab", name="Phrase habits").click()
            expect(page.locator(".main")).to_contain_text(re.compile("most-used phrases|No phrases yet"))
            assert "/ui/" in page.url, page.url                                  # never left Oread's pages
        check("Stats: resources and phrase habits inside the page, menu kept", stats_in_the_page)

        check("no script errors or blocked content", lambda: _none(problems))
        context.close()
    browser.close()


def _none(problems: list[str]) -> None:
    assert not problems, "; ".join(problems[:3])


def lockout(check: Checks) -> None:
    import json
    insecure = ssl.create_default_context()
    insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE

    def attempt():
        req = urllib.request.Request(BASE + "/api/session", method="POST",
                                     data=json.dumps({"username": "ann", "password": "nope-nope-nope"}).encode(),  # Ann exists
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, context=insecure)
            return 200
        except urllib.error.HTTPError as err:
            return err.code

    def five_then_locked():
        codes = [attempt() for _ in range(6)]
        assert codes == [401] * 5 + [429], codes
    print("lockout:")
    check("five wrong passwords lock the name", five_then_locked)


def strangers(check: Checks) -> None:
    """Every API call refuses someone who isn't signed in and has no valid token, except the few
    that must be open (signing in, first-run setup, the certificate). Lists the routes from the code,
    so a call added later is checked too."""
    import re as _re
    from unittest.mock import MagicMock
    sys.path.insert(0, str(ROOT))
    from oread.api import build_app
    app = build_app(*[MagicMock() for _ in range(10)])
    insecure = ssl.create_default_context()
    insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=insecure))

    def status(method: str, path: str, token: str | None = None) -> int:
        headers = {"Content-Type": "application/json", "X-Requested-With": "oread"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(BASE + path, method=method, headers=headers,
                                     data=b"{}" if method in ("POST", "PUT", "PATCH") else None)
        try:
            return opener.open(req, timeout=10).status
        except urllib.error.HTTPError as err:
            return err.code

    def all_refused():
        open_ones, checked = [], 0
        for route in app.routes:
            tags = getattr(route, "tags", None)
            if tags is None or "public" in tags:
                continue
            path = _re.sub(r"\{[^}]+\}", "x", route.path)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                checked += 1
                for token in (None, "oread_not-a-real-token"):
                    code = status(method, path, token)
                    if code != 401:
                        open_ones.append(f"{method} {route.path} ({'bad token' if token else 'nobody'}): {code}")
        assert not open_ones, open_ones
        assert checked > 50, checked                          # the whole API, not a handful
    check("strangers: every API call refuses nobody and a made-up token (401)", all_refused)

    def api_page_hidden():
        assert status("GET", "/openapi.json") == 401
        code = status("GET", "/docs")
        assert code in (302, 307), code                       # sent to sign in first
        assert status("GET", "/redoc") == 404
    check("strangers: the API page and its description need a sign-in", api_page_hidden)


def main() -> None:
    check = Checks()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        proc, code = start_oread(tmp)
        try:
            with sync_playwright() as p:
                missing = []
                for engine in ("chromium", "firefox", "webkit"):
                    try:
                        run_engine(p, engine, code, check)
                        code = None   # setup happens once, in the first engine that runs
                    except PlaywrightError as err:
                        if "Executable doesn't exist" in str(err) or "playwright install" in str(err):
                            missing.append(engine)
                        else:
                            raise
            lockout(check)
            print("strangers:")
            strangers(check)
        finally:
            proc.terminate()
            proc.wait(timeout=20)
    if missing:
        print(f"\nNot installed here, so not tested: {', '.join(missing)} "
              "(playwright install " + " ".join(missing) + ")")
    print(f"\n{'All passed' if not check.failures else str(len(check.failures)) + ' failed'}")
    sys.exit(1 if check.failures else 0)


if __name__ == "__main__":
    main()
