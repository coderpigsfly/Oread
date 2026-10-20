"""Speaker ID self-test: run after every change to voiceprints, matching or profiles.

    docker compose exec oread python -m oread.selftest

Uses three public LibriSpeech voices (tests/audio) and a throwaway data
folder, so real profiles are never touched. Checks every voiceprint model
in use by a device: the same voice is recognised, a stranger is not, short
clips can't be assigned, and renaming and model switching keep profiles.
"""

from __future__ import annotations

import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from . import settings as settings_mod, speaker
from .store import Store, StoreError

AUDIO = settings_mod.APP_DIR / "tests" / "audio"
VOICES = {"a": "librispeech-1.wav", "b": "librispeech-0.wav", "c": "librispeech-2.wav"}


def load(name: str) -> tuple[np.ndarray, int]:
    with wave.open(str(AUDIO / VOICES[name]), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return x, w.getframerate()


def cut(samples: np.ndarray, rate: int, start: float, end: float) -> np.ndarray:
    return samples[int(start * rate):int(end * rate)]


def check(models_root: Path, model_name: str, unknown_below: float, match_above: float) -> list[str]:
    failures: list[str] = []
    model = speaker.get(model_name)
    printer = speaker.Voiceprinter(model, speaker.ensure(model, models_root), 1)
    voices = {k: load(k) for k in VOICES}

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"{model_name}: {what}")

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.rebuild(model_name, lambda p: None)

        def save(voice: str, start: float, end: float, trainable: bool = True) -> str:
            samples, rate = voices[voice]
            part = cut(samples, rate, start, end)
            vp = printer.voiceprint(part, rate)
            pcm = (part * 32767).astype("<i2").tobytes()
            return store.save_clip(device="selftest", pcm=pcm, rate=rate, width=2, channels=1,
                                   transcript=f"voice {voice}", audio_s=len(part) / rate,
                                   trainable=trainable, model=model_name, voiceprint=vp,
                                   result={})

        def who(voice: str, start: float, end: float) -> dict:
            samples, rate = voices[voice]
            vp = printer.voiceprint(cut(samples, rate, start, end), rate)
            return store.match(model_name, vp, unknown_below, match_above)

        r = who("a", 3.3, 6.6)
        expect("nobody enrolled: unknown", r["label"] == "unknown")

        store.assign(save("a", 0, 3.3), "Voice A")
        store.assign(save("c", 0, 5), "Voice C")

        r = who("a", 3.3, 6.6)
        expect("voice A recognised from a different part", r["speaker"] == "Voice A", f"(score {r['score']})")
        r = who("c", 8, 13)
        expect("voice C recognised from a different part", r["speaker"] == "Voice C", f"(score {r['score']})")
        r = who("b", 2, 7.4)
        expect("stranger B not named", r["speaker"] is None, f"({r['label']}, closest {r['guess']} {r['score']})")

        short = save("b", 0, 1.8, trainable=False)
        try:
            store.assign(short, "Voice B")
            expect("short clip refused for training", False)
        except StoreError:
            expect("short clip refused for training", True)

        store.rename_profile("Voice C", "Voice C2")
        r = who("c", 13, 16.7)
        expect("rename keeps the voiceprint", r["speaker"] == "Voice C2", f"(score {r['score']})")

        # a fresh start rebuilds profiles from saved audio (as after a model switch)
        def from_wav(path: Path):
            with wave.open(str(path), "rb") as w:
                x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
                return printer.voiceprint(x, w.getframerate())
        restarted = Store(Path(tmp))
        for clip in restarted._clips.values():
            clip["voiceprints"] = {}
        restarted.rebuild(model_name, from_wav)
        samples, rate = voices["a"]
        r = restarted.match(model_name, printer.voiceprint(cut(samples, rate, 3.3, 6.6), rate),
                            unknown_below, match_above)
        expect("profiles rebuilt from saved audio", r["speaker"] == "Voice A", f"(score {r['score']})")
    return failures


def check_phrases() -> list[str]:
    from .phrases import top_phrases
    data = top_phrases(["Check the windows.", "Check the windows please", "Are the windows closed?",
                        "Turn on the lights", "Check the windows in the kitchen."])
    found = [p["phrase"] for p in data["phrases"]]
    ok = found[:2] == ["the windows", "check the windows"] and "check the" not in found
    print(f"phrase habits:\n  {'PASS' if ok else 'FAIL'}  top phrases counted once per clip  {found}")
    failures = [] if ok else ["phrase habits"]
    return failures + check_phrase_decisions()


def check_phrase_decisions() -> list[str]:
    """The rules for letting phrases help a voice match."""
    from .phrases import _build, decide
    clips = [(f"g{i}", "sam", t) for i, t in enumerate([
        "check the windows", "check the windows in the kitchen", "did you check the windows",
        "turn on the lights", "what's the weather"])]
    clips += [(f"l{i}", "ann", t) for i, t in enumerate([
        "is the porch light on", "porch light off", "turn the porch light on",
        "turn on the lights", "turn on the lights in the den"])]
    habits = _build(clips)
    failures = []

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(what)

    def voice(score, close):
        return {"label": "maybe" if 0.35 <= score < 0.55 else ("known" if score >= 0.55 else "unknown"),
                "speaker": None, "guess": close[0][0], "score": score, "by": None,
                "close": [{"name": n, "score": v} for n, v in close]}

    ann_habits = {" ".join(g) for g in habits["ann"]}
    expect("a shared phrase is nobody's habit", "turn on the lights" not in ann_habits
           and "turn on the lights" not in {" ".join(g) for g in habits["sam"]}, str(sorted(ann_habits)))
    r = decide(voice(0.50, [("ann", 0.50), ("sam", 0.30)]), "porch light on", habits, 0.45, 0.55, "on")
    expect("in range + her habit: confirms Ann", r["speaker"] == "ann" and r["by"] == "voice+phrase")
    r = decide(voice(0.50, [("ann", 0.50), ("sam", 0.48)]), "check the windows", habits, 0.45, 0.55, "on")
    expect("nearly tied: Sam's habit picks Sam", r["speaker"] == "sam")
    r = decide(voice(0.50, [("ann", 0.50), ("sam", 0.30)]), "check the windows", habits, 0.45, 0.55, "on")
    expect("never names someone the voice didn't point to", r["speaker"] is None and r["label"] == "maybe")
    r = decide(voice(0.40, [("ann", 0.40)]), "porch light on", habits, 0.45, 0.55, "on")
    expect("below the range: phrases ignored", r["speaker"] is None and "phrase" not in r)
    known = {**voice(0.70, [("sam", 0.70), ("ann", 0.65)]), "speaker": "sam", "by": "voice"}
    r = decide(known, "porch light on", habits, 0.45, 0.55, "on")
    expect("a clear voice match is never overridden", r["speaker"] == "sam" and r["by"] == "voice")
    r = decide(voice(0.50, [("ann", 0.50), ("sam", 0.30)]), "what time is it", habits, 0.45, 0.55, "on")
    expect("no habit heard: stays maybe (nobody ruled out)", r["label"] == "maybe")
    r = decide(voice(0.50, [("ann", 0.50), ("sam", 0.30)]), "porch light on", habits, 0.45, 0.55, "shadow")
    expect("shadow: notes it, changes nothing", r["speaker"] is None and r["phrase"]["points_to"] == "ann")
    return failures


def check_device_types() -> list[str]:
    """Device types: shipped examples, yours on top, add / relabel / remove, saved to your file."""
    from .device_types import DeviceTypeError, DeviceTypes
    failures: list[str] = []
    print("device types:")

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"device types: {what}")

    def refused(fn, *args) -> int | None:
        try:
            fn(*args)
        except DeviceTypeError as err:
            return err.status
        return None

    with tempfile.TemporaryDirectory() as tmp:
        types = DeviceTypes(Path(tmp))
        names = set(types.all())
        expect("the shipped examples are there", {"voice-pe", "android", "laptop"} <= names, sorted(names))
        added = types.add("kitchen-speaker", "Kitchen speaker", "by the stove", None, "titanet-small")
        expect("add a type with a starting voice model",
               added["label"] == "Kitchen speaker" and added["speaker_model"] == "titanet-small")
        expect("its model is a starting setting for its devices",
               types.settings_map()["kitchen-speaker"] == {"speaker": {"model": "titanet-small"}})
        expect("a name already used is refused", refused(types.add, "kitchen-speaker", "x", None, None, None) == 409)
        expect("an unknown model is refused", refused(types.add, "den", "Den", None, "no-such-model", None) == 400)
        expect("a label is needed", refused(types.add, "den", "  ", None, None, None) == 400)
        types.relabel("voice-pe", "Voice PE (kitchen)", None)
        again = DeviceTypes(Path(tmp))      # what a restart reads back
        expect("relabel a shipped type, kept after a restart",
               again.all()["voice-pe"]["label"] == "Voice PE (kitchen)" and "note" in again.all()["voice-pe"])
        expect("a type in use can't be removed", refused(again.remove, "android", ["tablet"]) == 409)
        again.remove("android", [])
        again.remove("kitchen-speaker", [])
        after = DeviceTypes(Path(tmp)).all()
        expect("remove a shipped type and one of yours, kept after a restart",
               "android" not in after and "kitchen-speaker" not in after and "laptop" in after)
    return failures


def check_model_settings() -> list[str]:
    """Each model's own settings and the defaults: saved to data/models.yaml, layered under the devices."""
    import os
    import yaml
    from . import catalog
    failures: list[str] = []
    print("model settings:")

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"model settings: {what}")

    def refused(**kwargs) -> bool:
        try:
            catalog.save("voice", "titanet-small", **kwargs)
        except catalog.ModelSettingsError:
            return True
        return False

    before = os.environ.get("OREAD_SETTINGS")
    with tempfile.TemporaryDirectory() as tmp:
        settings_file = Path(tmp) / "settings.yaml"
        settings_file.write_text(yaml.safe_dump({"paths": {"data": str(Path(tmp) / "data")}}))
        os.environ["OREAD_SETTINGS"] = str(settings_file)
        catalog.reload()
        try:
            listed = catalog.load()
            expect("defaults come from models.yaml",
                   listed["defaults"] == {"speech": "moonshine-base-en-int8", "voice": "titanet-small",
                                          "vad": "silero-vad"}, listed["defaults"])
            device = settings_mod.with_model_settings({"stt": {}, "speaker": {"phrase_mode": "on"}})
            expect("a device starts from its model's own settings",
                   device["speaker"]["match_above"] == 0.55 and device["speaker"]["model"] == "titanet-small"
                   and device["stt"]["num_threads"] == 4 and device["speaker"]["phrase_mode"] == "on")
            catalog.save("voice", "titanet-small", settings={"match_above": 0.6})
            mine = yaml.safe_load((Path(tmp) / "data" / "models.yaml").read_text())
            expect("saving keeps only what changed", mine == {"voice": {"titanet-small": {"settings": {"match_above": 0.6}}}},
                   mine)
            device = settings_mod.with_model_settings({"stt": {}, "speaker": {}})
            expect("devices get the saved value", device["speaker"]["match_above"] == 0.6)
            device = settings_mod.with_model_settings({"stt": {}, "speaker": {"match_above": 0.7}})
            expect("a device's own value still wins", device["speaker"]["match_above"] == 0.7)
            expect("an unknown setting is refused", refused(settings={"loudness": 1}))
            expect("out of range is refused", refused(settings={"match_above": 1.5}))
            expect("unknown above named is refused", refused(settings={"unknown_below": 0.65}))
            catalog.save("voice", "campplus-en", make_default=True)
            device = settings_mod.with_model_settings({"stt": {}, "speaker": {}})
            expect("make default: devices without a choice use it", device["speaker"]["model"] == "campplus-en")
            catalog.save("voice", "titanet-small", back_to_shipped=True)
            catalog.save("voice", "titanet-small", make_default=True)
            listed = catalog.load()
            # where a model comes from (the Imports page)
            catalog.save_definition("speech", "parakeet-tdt-0.6b-v2-int8", {"notes": "Mine now."})
            mine = yaml.safe_load((Path(tmp) / "data" / "models.yaml").read_text())
            expect("changing a shipped model keeps only what changed",
                   mine["speech"]["parakeet-tdt-0.6b-v2-int8"] == {"notes": "Mine now."}, mine.get("speech"))
            def refused_def(**kw) -> bool:
                try:
                    catalog.save_definition(**kw)
                except catalog.ModelSettingsError:
                    return True
                return False
            expect("an address that isn't https:// is refused",
                   refused_def(section="voice", name="titanet-small", fields={"url": "ftp://x/y.onnx"}))
            expect("a speech model missing a file for its kind is refused",
                   refused_def(section="speech", name="moonshine-base-en-int8", fields={"kind": "whisper"}))
            expect("a new model missing what it needs is refused",
                   refused_def(section="voice", name="my-voice", fields={"label": "Mine"}, new=True))
            catalog.save_definition("voice", "my-voice", {"label": "Mine", "url": "https://example.com/v.onnx",
                                                          "file": "v.onnx"}, new=True)
            listed = catalog.load()
            expect("add a model; it starts on the default model's settings",
                   listed["voice"]["my-voice"]["settings"]["match_above"] == 0.55)
            expect("remove a model you added", catalog.reset_definition("voice", "my-voice") == "removed"
                   and "my-voice" not in catalog.load()["voice"])
            expect("a shipped model back to its entry",
                   catalog.reset_definition("speech", "parakeet-tdt-0.6b-v2-int8") == "shipped"
                   and catalog.load()["speech"]["parakeet-tdt-0.6b-v2-int8"]["notes"] != "Mine now.")
            expect("back to shipped settings, and back to the shipped default",
                   listed["voice"]["titanet-small"]["settings"]["match_above"] == 0.55
                   and listed["defaults"]["voice"] == "titanet-small")
        finally:
            if before is None:
                os.environ.pop("OREAD_SETTINGS", None)
            else:
                os.environ["OREAD_SETTINGS"] = before
            catalog.reload()
    return failures


def check_api_reference() -> list[str]:
    """The guide's API appendix must match the code (tools/api_reference.py rewrites it)."""
    import subprocess
    tool = Path(__file__).resolve().parent.parent / "tools" / "api_reference.py"
    if not tool.exists():   # inside the Docker image, where docs and tools aren't copied
        return []
    done = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True)
    ok = done.returncode == 0
    print(f"user guide:\n  {'PASS' if ok else 'FAIL'}  API appendix matches the code")
    failures = [] if ok else ["API appendix out of date (run tools/api_reference.py)"]
    import re
    guide = (tool.parent.parent / "docs" / "user-guide.md").read_text()
    anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
               for h in re.findall(r"^#{2,4} (.+)$", guide, re.M)}
    broken = [link for link in re.findall(r"\]\(#([^)]+)\)", guide) if link not in anchors]
    print(f"  {'PASS' if not broken else 'FAIL'}  every link inside the guide lands  {broken or ''}")
    headings = set(re.findall(r"^#{2,4} (.+)$", guide, re.M))
    pages = (tool.parent.parent / "oread" / "web" / "app.js").read_text()
    lost = [m for m in re.findall(r'guideMore\("([^"]+)"\)', pages) if m not in headings]
    print(f"  {'PASS' if not lost else 'FAIL'}  every page's More link names a guide heading  {lost or ''}")
    return (failures + (["guide links: " + ", ".join(broken)] if broken else [])
            + (["More links: " + ", ".join(lost)] if lost else []))


def check_measures() -> list[str]:
    """The audio measures see what a device change does: louder, gated, clipped."""
    from .measures import measure
    failures: list[str] = []

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"measures: {what}")

    print("audio measures:")
    rate = 16000
    t = np.arange(rate * 2) / rate
    rng = np.random.default_rng(1)
    voice = (0.2 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 2 * t) > 0)).astype(np.float32)
    plain = voice + 0.003 * rng.standard_normal(t.size).astype(np.float32)
    gated = np.where(np.abs(voice) > 0, plain, 0).astype(np.float32)
    hot = np.clip(plain * 8, -1, 1)
    a, g, c = measure(plain, rate), measure(gated, rate), measure(hot, rate)
    expect("a quiet room has a background level", -60 < a["noise_db"] < -40, a["noise_db"])
    expect("a noise gate shows as digital silence", g["gated_pct"] > 30 and a["gated_pct"] == 0,
           (a["gated_pct"], g["gated_pct"]))
    expect("more gain is louder and clips", c["speech_db"] > a["speech_db"] + 10 and c["clipped_pct"] > 1,
           (a["speech_db"], c["speech_db"], c["clipped_pct"]))
    expect("a 220 Hz voice sits in the 150-300 Hz band", a["bands_db"]["150-300"] > a["bands_db"]["3000-6000"] + 20)
    return failures


def check_step_times() -> list[str]:
    """Speech to text and the voiceprint are timed apart (they run at the same time): the
    real-time factor is speech to text's own, and the log line names both."""
    import logging
    from . import metrics
    failures: list[str] = []

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"step times: {what}")

    print("step times:")
    lines: list[str] = []
    grab = logging.Handler()
    grab.emit = lambda rec: lines.append(rec.getMessage())
    log = logging.getLogger("oread.requests")
    was = log.level
    log.addHandler(grab)
    log.setLevel(logging.INFO)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            r = metrics.Request(Path(tmp), "selftest")
            r.fields["steps_ms"].update({"stt": 500.0, "voiceprint": 120.0, "stt+voiceprint": 520.0})
            f = r.finish(device="selftest", audio_s=2.0, text="yes")
    finally:
        log.removeHandler(grab)
        log.setLevel(was)
    expect("the real-time factor is speech to text's own", f.get("rtf") == 0.25, f.get("rtf"))
    expect("the log line names speech to text and the voiceprint",
           any("stt=500.0ms voiceprint=120.0ms" in x for x in lines), lines[-1:] if lines else "")
    return failures


def check_verdict() -> list[str]:
    """The trial's one-word verdict, judged on the new sound."""
    from .retrain import verdict
    failures: list[str] = []
    print("the trial's verdict:")
    tally = lambda own, wrong: {"theirs_today": own[0], "theirs_trial": own[1],   # noqa: E731
                                "others_today": wrong[0], "others_trial": wrong[1]}
    for what, counts, scores, want in (
            ("more of their own named, none wrong: better", tally((1, 9), (0, 0)), [], "better"),
            ("someone else named as them: worse", tally((1, 1), (0, 1)), [], "worse"),
            ("fewer of their own: worse", tally((5, 3), (0, 0)), [], "worse"),
            ("more of their own but someone else too: mixed", tally((1, 9), (0, 1)), [], "mixed"),
            ("same counts, scores up: better", tally((2, 2), (0, 0)), [(0.4, 0.6)], "better"),
            ("same counts, scores within 0.02: no change", tally((2, 2), (0, 0)), [(0.5, 0.51)], "no change")):
        got = verdict(counts, scores)["verdict"]
        print(f"  {'PASS' if got == want else 'FAIL'}  {what}  {got if got != want else ''}")
        if got != want:
            failures.append(f"verdict: {what}")
    return failures


def check_retrain() -> list[str]:
    """Retraining a person on one device: a trial changes nothing until accepted; a clip is
    never scored against a voiceprint made with itself; taking a clip back takes it out."""
    from .retrain import Retrain, RetrainError
    failures: list[str] = []

    def expect(what: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail}")
        if not ok:
            failures.append(f"retrain: {what}")

    print("retraining on one device:")
    rng = np.random.default_rng(2)
    unit = lambda v: (v / np.linalg.norm(v)).astype(np.float32)   # noqa: E731
    old, new, other = (unit(rng.standard_normal(16)) for _ in range(3))
    sound = lambda base: unit(base + 0.25 * unit(rng.standard_normal(16)))   # noqa: E731
    me = {"name": "tester", "kind": "user"}
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.retrain = Retrain(store, Path(tmp) / "device_profiles.json")
        store.rebuild("m", lambda p: None)

        def clip(device: str, vec, person: str | None, by=me) -> str:
            cid = store.save_clip(device=device, pcm=b"\0\0" * 48000, rate=16000, width=2, channels=1,
                                  transcript="words", audio_s=3.0, trainable=True, model="m",
                                  voiceprint=vec, result={"label": "x", "score": 0.1})
            if person:
                store.assign(cid, person, by)
            return cid

        for _ in range(8):
            clip("voice-pe", sound(old), "Ann")
            clip("kitchen", sound(old), "Ann")
            clip("voice-pe", sound(other), "Bo")
        time.sleep(1.1)   # the change: clips heard after it (clip times are to the second)
        after = [clip("kitchen", sound(new), "Ann") for _ in range(4)]
        robot = clip("kitchen", sound(new), "Ann", {"name": "a-program", "kind": "token"})
        probe = sound(new)
        before = store.match("m", probe, 0.3, 0.6, store.retrain.overrides("kitchen", "m"))
        r = store.retrain
        try:
            r.start("kitchen", "Ann", "m", after + [robot], "gain up", "tester")
            expect("a clip a program assigned can't retrain", False)
        except RetrainError:
            expect("a clip a program assigned can't retrain", True)
        r.start("kitchen", "Ann", "m", after, "gain up", "tester")
        during = store.match("m", probe, 0.3, 0.6, r.overrides("kitchen", "m"))
        expect("a trial changes nothing until accepted", during["score"] == before["score"],
               (before["score"], during["score"]))
        view = r.view("kitchen", "Ann", "m")
        flattering = float(np.dot(r.voiceprint("kitchen", "Ann", "m", "pending"),
                                  next(c for c in store.voiced("m", "kitchen", "Ann") if c["id"] == after[0])["vector"]))
        honest = next(c for c in view["clips"] if c["id"] == after[0])["trial_score"]
        expect("a ticked clip is scored without itself", honest < flattering, (honest, round(flattering, 3)))
        blind = r.blind("kitchen", "Ann", "m", 0.3, 0.6)
        expect("the blind test scores every clip on the device", len(blind["clips"]) == 8 + 5, len(blind["clips"]))
        named = lambda key: sum(c[key]["speaker"] == "Ann" for c in blind["clips"]   # noqa: E731
                                if c["id"] in after or c["id"] == robot)
        expect("the trial names Ann's new-sound clips at least as well", named("trial") >= named("today"),
               (named("today"), named("trial")))
        expect("the blind test's verdict on the new sound: better", blind["verdict"]["verdict"] == "better",
               blind["verdict"])
        waiting = clip("kitchen", sound(new), None)    # heard before the accept, not assigned
        time.sleep(1.1)
        r.accept("kitchen", "Ann", "tester")
        expect("a clip heard before the accept is old sound", store.clip(waiting)["old_sound"])
        try:
            store.assign(waiting, "Ann", me)
            expect("old sound can't be assigned", False)
        except StoreError:
            expect("old sound can't be assigned", True)
        later = store.match("m", probe, 0.3, 0.6, r.overrides("kitchen", "m"))
        expect("accepted, Ann's kitchen voiceprint decides there", later["score"] > before["score"],
               (before["score"], later["score"]))
        other_dev = store.match("m", probe, 0.3, 0.6, r.overrides("voice-pe", "m"))
        expect("other devices are untouched", other_dev["score"] == before["score"])
        expect("the accept starts a settings period", r.period("kitchen") is not None)
        joined = clip("kitchen", sound(new), "Ann")
        expect("a clip assigned there afterwards joins it",
               next(c for c in r.view("kitchen", "Ann", "m")["clips"] if c["id"] == joined)["in_accepted"])
        store.unassign(after[0])
        expect("a clip taken back leaves it",
               all(c["id"] != after[0] for c in r.view("kitchen", "Ann", "m")["clips"]))
        store.rename_profile("Ann", "Anne")
        r.rename_person("Ann", "Anne")
        expect("a renamed person keeps their device voiceprint", "Anne" in r.overrides("kitchen", "m"))
        r.start("kitchen", "Anne", "m", after[1:], "", "tester")
        r.reject("kitchen", "Anne")
        expect("a rejected trial leaves nothing", r.view("kitchen", "Anne", "m")["pending"] is None)
        saved = Retrain(store, Path(tmp) / "device_profiles.json")
        expect("it survives a restart", "Anne" in saved.overrides("kitchen", "m"))
    return failures


def check_mishearings() -> list[str]:
    """Pulling the house router's mishearings: the token is sent, clips are looked up here and
    kept from trimming, a second pull merges (no doubles), and a line the router dropped stays."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from .mishearings import Mishearings, MishearingsError
    from .vault import Vault
    failures: list[str] = []

    def expect(what: str, ok: bool, detail="") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}  {detail if not ok else ''}")
        if not ok:
            failures.append(f"mishearings: {what}")

    print("mishearings from the house router:")
    served = {"list": [], "auth": []}

    class Router(BaseHTTPRequestHandler):
        def do_GET(self):   # noqa: N802 (the library's name)
            served["auth"].append(self.headers.get("Authorization"))
            ok = self.path == "/learn/mishearings" and self.headers.get("Authorization") == "Bearer good-token"
            body = _json.dumps({"router": "0.1.0", "mishearings": served["list"]} if ok else {"detail": "An API token is needed"})
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Router)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        store = Store(data, max_unassigned=1)
        vault = Vault(data / "vault.json", data / "keys")
        cfg = {"url": "", "token_key": "wepwawet", "timeout_s": 3}
        m = Mishearings(cfg, vault, store, data)
        try:
            m.pull()
            expect("no address: pulling is off, and says so", False)
        except MishearingsError as err:
            expect("no address: pulling is off, and says so", "address" in str(err))
        m.set_url(f"http://127.0.0.1:{server.server_port}/")
        vault.set("wepwawet", "bad-token", "wepwawet")
        try:
            m.pull()
            expect("a refused token says so", False)
        except MishearingsError as err:
            expect("a refused token says so", "401" in str(err) and "token" in str(err), str(err))
        vault.set("wepwawet", "good-token", "wepwawet")
        heard = store.save_clip(device="tablet", pcm=b"\0\0" * 16000, rate=16000, width=2, channels=1,
                                transcript="at a chore", audio_s=1.0, trainable=False, model=None, voiceprint=None,
                                result={"label": "too short"}, extra={"heard_with": {"stt_model": "parakeet-x"}})
        served["list"] = [{"meant": "add a chore", "heard": [
            {"said": "At a chore.", "count": 2, "first": "2026-10-17 09:00", "last": "2026-10-17 09:10", "taken": False,
             "clips": [{"clip": heard, "device": "tablet", "when": "2026-10-17 09:00"},
                       {"clip": "20200101-000000-000-voice-pe", "device": "voice-pe", "when": "2026-10-17 09:10"}]}]},
            {"meant": None, "heard": [{"said": "are the windows hold", "count": 1}]}]
        first = m.pull()
        expect("the token goes to the router", served["auth"][-1] == "Bearer good-token")
        expect("the first pull adds every line", (first["lines"], first["new"], first["clips_new"]) == (2, 2, 2), first)
        line = next(x for x in m.view()["lines"] if x["said"] == "At a chore.")
        found = next(c for c in line["clips"] if c["clip"] == heard)
        expect("a clip Oread has is looked up here: its model", found["found"] and found["heard_with"]["stt_model"] == "parakeet-x")
        expect("a clip Oread doesn't have is kept, marked", not next(c for c in line["clips"] if c["clip"] != heard)["found"])
        for _ in range(3):   # the review list keeps one unassigned clip: these push the old ones out
            store.save_clip(device="tablet", pcm=b"\0\0" * 1600, rate=16000, width=2, channels=1, transcript="x",
                            audio_s=0.1, trainable=False, model=None, voiceprint=None, result={})
            time.sleep(0.01)
        expect("a clip a mishearing was heard in is kept from trimming", store.clip(heard)["id"] == heard)
        served["list"][0]["heard"][0].update(count=3, said="at a chore")
        served["list"] = served["list"][:1]
        second = m.pull()
        lines = m.view()["lines"]
        expect("a second pull merges: no doubles, the count follows the router",
               len([x for x in lines if x["said"].lower().startswith("at a chore")]) == 1
               and next(x for x in lines if x["said"] == "at a chore")["count"] == 3, lines)
        expect("a line the router dropped stays, marked gone",
               next(x for x in lines if x["said"] == "are the windows hold")["gone"] and second["gone"] == 1)
        again = Mishearings(cfg, vault, store, data)
        expect("it survives a restart, the address set on the page too",
               len(again.view()["lines"]) == 2 and again.url.endswith(str(server.server_port)))
    server.shutdown()
    return failures


def main() -> None:
    from .device_types import DeviceTypes
    cfg = settings_mod.load()
    cfg["device_types"] = DeviceTypes(cfg["paths"]["data"]).settings_map()
    seen, failures = set(), check_phrases()
    failures += check_device_types()
    failures += check_model_settings()
    failures += check_measures()
    failures += check_retrain()
    failures += check_verdict()
    failures += check_step_times()
    failures += check_mishearings()
    for device in settings_mod.devices(cfg):
        s = device.settings["speaker"]
        key = (s["model"], s["unknown_below"], s["match_above"])
        if key in seen:
            continue
        seen.add(key)
        print(f"{s['model']} (unknown below {s['unknown_below']}, named at {s['match_above']}):")
        failures += check(cfg["paths"]["models"], s["model"], float(s["unknown_below"]),
                          float(s["match_above"]))
    failures += check_api_reference()
    print(f"\n{'All passed' if not failures else str(len(failures)) + ' failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
