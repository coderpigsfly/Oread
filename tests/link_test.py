#!/usr/bin/env python3
"""Stage 1 (oread1): an assistant's own voice (the patch), and Oread with the house router (people in
step, the Wepwawet page's switches). Calls nothing outside: a stand-in router on this machine and a
throwaway folder. Run from the folder:  python3 tests/link_test.py"""

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oread.mishearings import Mishearings  # noqa: E402
from oread.store import Store  # noqa: E402

FAILED = []


def case(name, got, want):
    if got != want:
        FAILED.append(name)
        print(f"FAIL  {name}\n        got:  {got!r}\n        want: {want!r}")
    else:
        print(f"PASS  {name}")


tmp = Path(tempfile.mkdtemp(prefix="oread-link-"))
store = Store(tmp)
store.create_profile("Master")
store.create_profile("Tablet voice", "assistant")
v_master, v_her = np.array([1, 0, 0], dtype=np.float32), np.array([0, 1, 0], dtype=np.float32)
store._centroids = {"m": {"Master": v_master, "Tablet voice": v_her}}
case("Profiles: people only for the router, an assistant's voice too for Oread's own pages",
     ([p["name"] for p in store.profiles(everyone=False)], [(p["name"], p["kind"]) for p in store.profiles()]),
     (["Master"], [("Master", "person"), ("Tablet voice", "assistant")]))
case("Her own voice, the device's patch on: known, marked own_voice",
     {k: store.match("m", v_her, 0.35, 0.55, own_voice=True).get(k) for k in ("speaker", "label", "own_voice")},
     {"speaker": "Tablet voice", "label": "known", "own_voice": True})
case("The patch off: her voice is never matched (never a person)",
     store.match("m", v_her, 0.35, 0.55)["speaker"], None)
case("A person, the patch on: no own-voice mark", store.match("m", v_master, 0.35, 0.55, own_voice=True).get("own_voice"), None)

# a stand-in router: GET and POST /people/oread
GRID = [{"person": "Master", "names": ["Master"]}]
SEEN = []


class Router(BaseHTTPRequestHandler):
    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"people": GRID})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append((body["action"], body["name"], body.get("was"), self.headers.get("Authorization")))
        if body["action"] == "add":
            GRID.append({"person": body["name"], "names": [body["name"]]})
        self._send({"said": f"{body['name']} added to the people grid"})

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Router)
threading.Thread(target=srv.serve_forever, daemon=True).start()


class Vault:
    def list(self):
        return {"keys": [{"name": "wepwawet"}]}

    def get(self, name):
        return "router-token"


link = Mishearings({"url": f"http://127.0.0.1:{srv.server_port}"}, Vault(), store, tmp)
case("Kept in step only when switched on", link.person_changed("add", "Rachel"), None)
link.set_link({"people_sync": True, "nightly_pull": True, "pull_hour": 4})
case("Switched on: an add is told to the router, with its token",
     (link.person_changed("add", "Rachel"), SEEN[-1]), ("Rachel added to the people grid", ("add", "Rachel", None, "Bearer router-token")))
case("The switches are kept (data/wepwawet.yaml) and read again at a start",
     Mishearings({}, Vault(), store, tmp).link, {"enabled": True, "people_sync": True, "nightly_pull": True, "pull_hour": 4})
case("Oread's people beside the router's: here and at the router, and the router's not here",
     link.people_view(["Master", "Ann"]), {"here": [{"name": "Ann", "at_router": None}, {"name": "Master", "at_router": "Master"}],
                                             "only_at_router": ["Rachel"]})
case("Add the missing ones", link.sync_people(["Master", "Ann"])["added"], ["Ann"])
link.set_link({"enabled": False})
case("Switched off: nothing told, nothing pulled", (link.person_changed("add", "Zed"), link.configured), (None, False))
try:
    link.set_link({"pull_hour": 30})
    case("A pull hour past 23 is refused", "no error", "an error")
except Exception as e:
    case("A pull hour past 23 is refused", "0 to 23" in str(e), True)

srv.shutdown()
print(f"\n{'all pass' if not FAILED else str(len(FAILED)) + ' fail'}")
sys.exit(1 if FAILED else 0)
