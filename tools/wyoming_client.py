"""Shared helper: send audio to Oread over Wyoming, get the transcript back.

Used by client.py (laptop testing) and regress.py (test cases).
Needs only: pip install wyoming numpy
"""

from __future__ import annotations

import time

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient

CHUNK_SAMPLES = 1024


async def transcribe(host: str, port: int, pcm: bytes, rate: int, width: int = 2,
                     channels: int = 1, language: str = "en") -> tuple[str, float]:
    """Return (transcript, round-trip ms measured from the last audio sent)."""
    text, ms, _context = await transcribe_full(host, port, pcm, rate, width, channels, language)
    return text, ms


async def transcribe_full(host: str, port: int, pcm: bytes, rate: int, width: int = 2,
                          channels: int = 1, language: str = "en") -> tuple[str, float, dict]:
    """Return (transcript, round-trip ms, context). Oread puts the speaker in context."""
    async with AsyncTcpClient(host, port) as client:
        await client.write_event(Transcribe(language=language).event())
        await client.write_event(AudioStart(rate=rate, width=width, channels=channels).event())
        step = CHUNK_SAMPLES * width * channels
        for i in range(0, len(pcm), step):
            await client.write_event(
                AudioChunk(rate=rate, width=width, channels=channels, audio=pcm[i:i + step]).event()
            )
        await client.write_event(AudioStop().event())
        sent = time.perf_counter()
        while True:
            event = await client.read_event()
            if event is None:
                raise ConnectionError("Oread closed the connection without a transcript")
            if Transcript.is_type(event.type):
                ms = (time.perf_counter() - sent) * 1000
                transcript = Transcript.from_event(event)
                return transcript.text, ms, transcript.context or {}


def describe_speaker(context: dict) -> str:
    """One line saying who Oread thinks spoke."""
    label = context.get("label")
    if label is None:
        return "speaker: (this Oread doesn't do speaker ID)"
    if label == "known":
        return f"speaker: {context['speaker']}  (score {context['score']})"
    if context.get("guess"):
        return f"speaker: {label}  (closest: {context['guess']}, score {context['score']})"
    return f"speaker: {label}"
