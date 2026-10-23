#!/usr/bin/env python3
"""Stage 2 (oread2): an assistant's own voice learned from her text-to-speech, and the Explore page's
rows. Calls nothing outside: a stand-in Home Assistant on this machine (its REST calls and its
websocket) and a throwaway folder. Run from the folder:  python3 tests/voice_test.py"""

import json
import struct
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from websockets.sync.server import serve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oread import explore  # noqa: E402
from oread.assistant_voice import AssistantVoices  # noqa: E402
from oread.publish import HomeAssistant, wav_samples  # noqa: E402
from oread.store import Store  # noqa: E402

FAILED = []


def case(name, got, want):
    if got != want:
        FAILED.append(name)
        print(f"FAIL  {name}\n        got:  {got!r}\n        want: {want!r}")
    else:
        print(f"PASS  {name}")


PIPELINES = {"preferred_pipeline": "p1", "pipelines": [
    {"id": "p1", "name": "Home", "tts_engine": "tts.piper", "tts_voice": "en_GB-cori-medium", "tts_language": "en_GB"},
    {"id": "p2", "name": "Voice PE", "tts_engine": "tts.piper", "tts_voice": "en_US-hfc_female-medium", "tts_language": "en_US"},
    {"id": "p3", "name": "Quiet", "tts_engine": None}]}
SELECTS = {"aaa111": {"select.g_assistant": "Voice PE", "select.g_wake_word": "okay_nabu", "select.g_detect": "default"},
           # the tablet: its second assistant names a pipeline, but its wake word is off, so it isn't used
           "bbb222": {"select.t_assistant": "preferred", "select.t_assistant_2": "Voice PE", "select.t_wake_word": "no_wake_word",
                      "select.t_wake_word_2": "no_wake_word", "select.t_sens": "Moderately sensitive"}}
SAID = []


def streamed_wav(seconds=2.2, rate=16000):
    """A WAV as Home Assistant streams it: its lengths say "very long"."""
    pcm = (np.sin(np.arange(int(seconds * rate)) * 0.05) * 8000).astype("<i2").tobytes()
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm)


class HA(BaseHTTPRequestHandler):
    def _send(self, data, kind="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/template":
            device = next(d for d in SELECTS if d in body["template"])
            self._send(json.dumps(SELECTS[device]).encode())
        elif self.path == "/api/tts_get_url":
            SAID.append((body["engine_id"], body["options"].get("voice"), body["language"], body["message"]))
            self._send(json.dumps({"path": "/api/tts_proxy/x.wav"}).encode())

    def do_GET(self):
        self._send(streamed_wav(), "audio/wav")

    def log_message(self, *args):
        pass


def ws_handler(ws):
    ws.send(json.dumps({"type": "auth_required"}))
    auth = json.loads(ws.recv())
    ws.send(json.dumps({"type": "auth_ok" if auth["access_token"] == "ha-token" else "auth_invalid"}))
    ask = json.loads(ws.recv())
    ws.send(json.dumps({"id": ask["id"], "type": "result", "success": True, "result": PIPELINES}))


rest = HTTPServer(("127.0.0.1", 0), HA)
threading.Thread(target=rest.serve_forever, daemon=True).start()
ws_server = serve(ws_handler, "127.0.0.1", 0)
threading.Thread(target=ws_server.serve_forever, daemon=True).start()
ws_port = ws_server.socket.getsockname()[1]


class Vault:
    def get(self, key):
        return "ha-token"

    def list(self):
        return {"keys": [{"name": "home-assistant"}]}


tmp = Path(tempfile.mkdtemp(prefix="oread-voice-"))
store = Store(tmp)
store.create_profile("Chief")
ha = HomeAssistant({"url": f"http://127.0.0.1:{rest.server_port}"}, Vault())
ha.pipelines = HomeAssistant({"url": f"http://127.0.0.1:{ws_port}"}, Vault()).pipelines   # its websocket elsewhere here
rebuilt = []
devices = SimpleNamespace(runtimes={
    "voice-pe": SimpleNamespace(hears_own_speaker=True, assistant_device="aaa111"),
    "tablet": SimpleNamespace(hears_own_speaker=True, assistant_device="bbb222"),
    "laptop": SimpleNamespace(hears_own_speaker=False, assistant_device="ccc333")},
    rebuild_profiles=lambda: rebuilt.append(1))
voices = AssistantVoices(ha, store, devices, tmp)

case("A streamed WAV from Home Assistant: its samples, though its header says 'very long'",
     (len(wav_samples(streamed_wav(1.0))[0]), wav_samples(streamed_wav(1.0))[1]), (32000, 16000))
case("Home Assistant's pipelines, over its websocket", [p["id"] for p in ha.pipelines()["pipelines"]], ["p1", "p2", "p3"])
case("The voices the devices with the switch on answer in ('preferred' is Home Assistant's preferred pipeline; a second "
     "assistant without its wake word doesn't count)",
     sorted((v["voice"], v["language"], tuple(v["devices"])) for v in voices.wanted()),
     [("en_GB-cori-medium", "en_GB", ("tablet",)), ("en_US-hfc_female-medium", "en_US", ("voice-pe",))])

lines = voices.lines()
view = voices.learn_all()
made = [p for p in store.profiles() if p.get("voice")]
case("Learned: one assistant's profile per voice, named after it, with every line said in it",
     sorted((p["name"], p["kind"], p["clips"], p["clips_by_device"]) for p in made),
     [("en_GB-cori-medium", "assistant", len(lines), {"tts": len(lines)}),
      ("en_US-hfc_female-medium", "assistant", len(lines), {"tts": len(lines)})])
case("Home Assistant was asked for each line in each voice, in its language",
     (len(SAID), SAID[0][:3] in {("tts.piper", "en_GB-cori-medium", "en_GB"), ("tts.piper", "en_US-hfc_female-medium", "en_US")},
      SAID[0][3] == lines[0]), (2 * len(lines), True, True))
case("Their voiceprints rebuilt once; the view says which and that they're new",
     (len(rebuilt), sorted(v["new"] for v in view["last"]["voices"]), view["last"]["error"], view["learning"]),
     (1, [True, True], None, False))
case("A made line never waits on the Learn page, and it isn't a person for the router",
     (len(store.clips("unassigned")), [p["name"] for p in store.profiles(everyone=False)]), (0, ["Chief"]))

SAID.clear()
again = voices.learn_all()
case("Looked again: nothing said twice, nothing new", (len(SAID), [v["new"] for v in again["last"]["voices"]], len(rebuilt)),
     (0, [False, False], 1))
store.rename_profile("en_GB-cori-medium", "Tablet voice")
voices.learn_all()
case("Renamed by hand: still known as that voice's (not learned twice)", (len(SAID), len([p for p in store.profiles() if p.get("voice")])),
     (0, 2))

wav = next(tmp.glob("clips/*-tts.wav"))
voices.learn_all(again=True)
case("Learn them over: the old lines gone, the voices said again, under the names they have now",
     (wav.exists(), len(SAID), len(rebuilt), sorted(p["name"] for p in store.profiles() if p.get("voice"))),
     (False, 2 * len(lines), 2, ["Tablet voice", "en_US-hfc_female-medium"]))
store.delete_profile("en_US-hfc_female-medium")
case("Deleting a learned voice takes its lines with it (they don't go to the review list)",
     (len(store.clips("unassigned")), sum(1 for c in store.clips("all", limit=10_000) if c.get("made"))), (0, len(lines)))

(tmp / "voice_lines.txt").write_text("# mine\nHello there.\n\nGood night.\n")
case("data/voice_lines.txt replaces the shipped lines", (voices.lines(), voices.view()["lines_file"]),
     (["Hello there.", "Good night."], "data/voice_lines.txt"))
(tmp / "voice_lines.txt").unlink()

ha.url = ""
case("Home Assistant not set up: why, kept for the page", voices.learn_all()["last"]["error"], "Home Assistant isn't set up (the Connections page)")

# stage 2, part 2 (oread3): her voice taught from the router's echoes
ha.url = f"http://127.0.0.1:{rest.server_port}"
voices.learn_all()
learned = {p["name"]: p["voice"].get("devices") for p in store.profiles() if p.get("voice")}
case("A learned voice knows the devices that answer in it", learned,
     {"Tablet voice": ["tablet"], "en_US-hfc_female-medium": ["voice-pe"]})


def heard(device, seconds=2.5, vec=(0, 1, 0)):
    cid = store.save_clip(device=device, pcm=b"\x00\x01" * int(16000 * seconds), rate=16000, width=2, channels=1,
                          transcript="Here is what happened", audio_s=seconds, trainable=True, model="m",
                          voiceprint=np.array(vec, dtype=np.float32), result={})
    return cid


e1, e2, e3, e4, e5 = heard("voice-pe"), heard("voice-pe"), heard("voice-pe", 1.0), heard("tablet"), heard("laptop")
store.assign(e2, "Chief")
echoes = [{"clip": e1, "device": "voice-pe", "by": "words"}, {"clip": e2, "device": "voice-pe", "by": "words"},
          {"clip": e3, "device": "voice-pe", "by": "words"}, {"clip": e4, "device": "tablet", "by": "voice"},
          {"clip": e5, "device": "laptop", "by": "words"}, {"clip": "gone-voice-pe", "device": "voice-pe", "by": "words"}]
case("The router's echoes: each found by her words goes on the voice its device answers in; the rest say why",
     voices.teach(echoes), {"taught": 1, "already": 1, "not_here": 1, "no_voice": 1, "by_voice": 1, "refused": 1, "two_voices": 0})
case("...on that voice, by the house router", (store.clip(e1)["profile"], store.clip(e1)["assigned"]["kind"]),
     ("en_US-hfc_female-medium", "echo"))
case("Taught again: nothing twice", voices.teach(echoes[:1])["already"], 1)
from oread.publish import slot_in_use  # noqa: E402
case("A second assistant counts while its wake word is set",
     [slot_in_use("select.d_assistant_2", {"select.d_wake_word_2": w}) for w in ("okay_nabu", "no_wake_word")]
     + [slot_in_use("select.d_assistant", {})], [True, False, True])
store.set_voice_devices("Tablet voice", ["voice-pe", "tablet"])
case("A device that answers in two voices: its echoes aren't guessed onto one", voices.teach([{"clip": heard("voice-pe"), "device": "voice-pe", "by": "words"}])["two_voices"], 1)
store.set_voice_devices("Tablet voice", ["tablet"])

made_v, heard_v = np.array([1, 0, 0], dtype=np.float32), np.array([0, 1, 0], dtype=np.float32)
case("Her voiceprint: the clean lines count until real_first heard clips, then the heard ones alone",
     (len(store._counted([(made_v, True)] * 30 + [(heard_v, False)] * 4)), len(store._counted([(made_v, True)] * 30 + [(heard_v, False)] * 5))),
     (34, 5))
for c in store._clips.values():                       # every clip a voiceprint for model m: made ones one way, heard another
    c["voiceprints"]["m"] = (made_v if c.get("made") else heard_v).tolist()
store._centroids = {"m": {}}
for _ in range(3):                                    # with the echo taught above: four heard
    store.assign(heard("voice-pe"), "en_US-hfc_female-medium", {"name": "house router", "kind": "echo"})
case("...four heard: still mostly the clean lines", round(float(store._centroids["m"]["en_US-hfc_female-medium"][0]), 2) > 0.9, True)
store.assign(heard("voice-pe"), "en_US-hfc_female-medium", {"name": "house router", "kind": "echo"})
case("...five heard: her voice as the device hears it", [round(float(x), 2) for x in store._centroids["m"]["en_US-hfc_female-medium"]],
     [0.0, 1.0, 0.0])
case("The profile counts its made lines apart", next((p["made"], p["clips"]) for p in store.profiles() if p["name"] == "en_US-hfc_female-medium"),
     (len(voices.lines()), len(voices.lines()) + 5))


from oread.mishearings import Mishearings  # noqa: E402
mh = Mishearings({"url": "http://127.0.0.1:1"}, Vault(), store, tmp)
mh._fetch = lambda: {"router": "t", "mishearings": [], "echoes": [{"clip": "x", "device": "voice-pe", "by": "words"}]}
mh.echoes_to = voices.teach
case("A pull hands the echoes over and says what came of them", mh.pull()["echoes"]["not_here"], 1)

# the Explore page's rows
clips = [
    {"id": "c1", "time": "2026-10-17T16:16:35+00:00", "device": "voice-pe", "transcript": "Is the watch a runny?", "audio_s": 2.4,
     "profile": None, "result": {"label": "known", "speaker": "Ann", "score": 0.71},
     "measures": {"speech_db": -17.3, "noise_db": -36.7}, "heard_with": {"stt_model": "parakeet"}},
    {"id": "c2", "time": "2026-10-18T10:00:00+00:00", "device": "tablet", "transcript": "Good morning", "audio_s": 1.1,
     "profile": "Chief", "result": {"label": "maybe", "guess": "Chief", "score": 0.4, "own_voice": False}},
    {"id": "m1", "time": "2026-10-18T10:00:00+00:00", "device": "tts", "transcript": "Made", "audio_s": 2.0, "profile": "x",
     "made": {"engine": "tts.piper"}, "result": {}},
]
mis = [{"said": "Is the watch a runny?", "meant": "Is the washer running?", "count": 2, "clips": [{"clip": "c1", "device": "voice-pe"}]},
       {"said": "Read me my cat listen.", "meant": "Read me my task list.", "count": 1, "clips": []},
       {"said": "Never meant", "clips": []}]
out = explore.rows(clips, mis, {"voice-pe": "voice-pe"}, {"Chief"})
c1 = out["clips"][0]
case("Explore: one row per clip heard (not the made lines), with its fields",
     ([r["clip"] for r in out["clips"]], {k: c1[k] for k in ("Device", "Device type", "Speaker", "Assigned", "Voice ID",
                                                               "Speech over noise dB", "Misheard", "meant", "Words")}),
     (["c1", "c2"], {"Device": "voice-pe", "Device type": "voice-pe", "Speaker": "Ann", "Assigned": "no", "Voice ID": "known",
                     "Speech over noise dB": 19.4, "Misheard": "yes", "meant": "Is the washer running?", "Words": 5}))
case("Explore: an assigned clip is its person's; no mishearing: not flagged",
     {k: out["clips"][1][k] for k in ("Speaker", "Speaker is", "Device type", "Misheard", "Speech dB")},
     {"Speaker": "Chief", "Speaker is": "assistant's voice", "Device type": "none", "Misheard": "not flagged", "Speech dB": None})
case("Explore: each word of each mishearing with what was meant (a line with no meaning left out)",
     [(w["Kind"], w["Meant"], w["Heard"], w["Speaker"], w["Times"]) for w in out["words"]],
     [("right", "is", "is", "Ann", 2), ("right", "the", "the", "Ann", 2), ("swapped", "washer running", "watch a runny", "Ann", 2),
      ("right", "read", "read", "not found", 1), ("right", "me", "me", "not found", 1), ("right", "my", "my", "not found", 1),
      ("swapped", "task", "cat", "not found", 1), ("swapped", "list", "listen", "not found", 1)])
case("Explore: dropped and added words", [(w["Kind"], w["Meant"], w["Heard"]) for w in explore.compare("mark it as done", "mark it done now")
                                          if w["Kind"] != "right"], [("dropped", "as", ""), ("added", "", "now")])

rest.shutdown()
ws_server.shutdown()
print(f"\n{'all pass' if not FAILED else str(len(FAILED)) + ' fail'}")
sys.exit(1 if FAILED else 0)
