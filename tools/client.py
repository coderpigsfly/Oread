#!/usr/bin/env python3
"""Talk to Oread from your laptop, the same way a satellite would.

Record from the microphone (stops on its own when you stop talking, like a satellite):
    python3 tools/client.py --host <server address>
Record a fixed length instead:
    python3 tools/client.py --host <server address> --fixed --seconds 5
Send a WAV file instead:
    python3 tools/client.py --host <server address> --file clip.wav
Use another voice detector (one listed under vad: in models.yaml or data/models.yaml):
    python3 tools/client.py --host <server address> --vad <name>

Laptop setup (once):  pip install wyoming numpy pyyaml sounddevice sherpa-onnx
The laptop is the capture for development only; real voice profiles come
from clips heard on the satellites.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from wyoming_client import describe_speaker, transcribe_full  # noqa: E402

RATE = 16000
BLOCK = 512            # 32 ms of audio per block (the Silero detector's window)
WARMUP_BLOCKS = 5      # skip the mic's first 0.16 s, which is often a startup pop
LEAD_BLOCKS = 16       # keep 0.5 s before speech is detected
TAIL_SECONDS = 0.6     # stop after this much non-speech once you've spoken


def voice_detector(name: str | None) -> tuple[str, dict]:
    """The voice detector to use, from the vad: section of models.yaml (and data/models.yaml):
    the one named, else the default. Downloaded into models/ on first use.
    Returns (its file, its entry)."""
    from oread import catalog
    listed = catalog.load()["vad"]
    name = name or catalog.load()["defaults"]["vad"]
    if name not in listed:
        sys.exit(f"No voice detector named '{name}'. Listed in models.yaml: {', '.join(sorted(listed))}")
    entry = {**listed[name], "name": name}
    path = ROOT / "models" / entry["file"]
    if not path.exists():
        import urllib.request
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading the voice detector {entry['label']} (first use only)...")
        part = path.with_suffix(".part")
        urllib.request.urlretrieve(entry["url"], part)
        part.rename(path)
    return str(path), entry


class SpeechGate:
    """Decides, block by block, when speech has started and ended.

    Uses the Silero neural voice detector (through sherpa-onnx), which tells
    speech from background noise like fans, hum and mic hiss, not just by
    loudness. Recording ends after TAIL_SECONDS of non-speech after speech.
    """

    def __init__(self, vad: str | None = None, tail_seconds: float = TAIL_SECONDS) -> None:
        try:
            import sherpa_onnx
        except ImportError:
            sys.exit("Stop-when-you-stop needs: pip install sherpa-onnx  (or use --fixed)")
        path, entry = voice_detector(vad)
        settings = entry["settings"]
        config = sherpa_onnx.VadModelConfig()
        if entry["kind"] == "silero":
            config.silero_vad.model = path
            config.silero_vad.threshold = float(settings["threshold"])
            config.silero_vad.min_silence_duration = float(settings["min_silence_duration"])
            config.silero_vad.min_speech_duration = float(settings["min_speech_duration"])
            config.silero_vad.window_size = BLOCK
        else:
            sys.exit(f"This client can't load a {entry['kind']} voice detector yet")
        config.sample_rate = RATE
        print(f"Voice detector: {entry['label']} ({entry['name']}; sure at {settings['threshold']}, "
              f"pause {settings['min_silence_duration']} s)")
        self.vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        self.tail_blocks = int(tail_seconds * RATE / BLOCK)
        self.blocks: list[bytes] = []
        self.start_at: int | None = None
        self.quiet = 0
        self.voiced = 0
        self.seen = 0

    @property
    def started(self) -> bool:
        return self.start_at is not None

    def feed(self, block: bytes) -> bool:
        """Add a block; returns True when the recording is complete."""
        import numpy as np
        self.seen += 1
        if self.seen <= WARMUP_BLOCKS:
            return False
        self.blocks.append(block)
        self.vad.accept_waveform(np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768.0)
        is_speech = self.vad.is_speech_detected()
        self.voiced += is_speech
        if not self.started:
            if is_speech:
                self.start_at = len(self.blocks) - 1
            return False
        self.quiet = 0 if is_speech else self.quiet + 1
        return self.quiet >= self.tail_blocks

    def audio(self) -> bytes:
        """Speech plus a short lead-in; everything if speech was never detected."""
        if not self.started:
            return b"".join(self.blocks)
        return b"".join(self.blocks[max(0, self.start_at - LEAD_BLOCKS):])


def record(seconds: float, fixed: bool, vad: str | None = None) -> bytes:
    try:
        import sounddevice as sd
    except ImportError:
        sys.exit("Recording needs sounddevice: pip install sounddevice")
    if fixed:
        input(f"Press Enter, then speak for {seconds:g} seconds...")
        print("Listening...")
        audio = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="int16")
        sd.wait()
        print("Got it.")
        return audio.tobytes()

    gate = SpeechGate(vad)
    input(f"Press Enter, then speak (stops when you stop, {seconds:g} s at most)...")
    print("Listening...")
    with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as stream:
        for _ in range(int(seconds * RATE / BLOCK)):
            block, _overflow = stream.read(BLOCK)
            if gate.feed(bytes(block)):
                break
    kept = len(gate.audio()) / 2 / RATE
    print(f"Got it. ({gate.voiced} of {len(gate.blocks)} blocks sounded like speech; sending {kept:.1f} s)")
    if not gate.started:
        print("Never detected speech, so sent the whole recording.")
    return gate.audio()


def read_wav(path: str) -> tuple[bytes, int, int, int]:
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()


def main() -> None:
    p = argparse.ArgumentParser(description="Send speech to Oread and print the transcript")
    p.add_argument("--host", default="localhost", help="server running Oread")
    p.add_argument("--port", type=int, default=10310)
    p.add_argument("--file", help="WAV file to send instead of recording")
    p.add_argument("--seconds", type=float, default=10,
                   help="longest recording (with --fixed: exact length)")
    p.add_argument("--fixed", action="store_true",
                   help="record exactly --seconds instead of stopping when you stop talking")
    p.add_argument("--save", help="also save the recording to this WAV file")
    p.add_argument("--vad", help="voice detector to use (a name under vad: in models.yaml); "
                                 "default: the one models.yaml names")
    args = p.parse_args()

    if args.file:
        pcm, rate, width, channels = read_wav(args.file)
    else:
        pcm, rate, width, channels = record(args.seconds, args.fixed, args.vad), RATE, 2, 1
        if args.save:
            with wave.open(args.save, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm)

    text, ms, context = asyncio.run(transcribe_full(args.host, args.port, pcm, rate, width, channels))
    seconds = len(pcm) / (rate * width * channels)
    print(f"Heard ({seconds:.1f} s of audio, answered {ms:.0f} ms after it ended):")
    print(f"  {text!r}")
    print(f"  {describe_speaker(context)}")
    if context.get("model"):
        print(f"  models on {context.get('device', 'that port')}: speech {context['model']}, "
              f"voice {context.get('speaker_model', '?')}")
    if context.get("clip"):
        print(f"  saved as clip {context['clip']}")


if __name__ == "__main__":
    main()
