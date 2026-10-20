"""Wyoming speech-to-text event handler: audio in, transcript and speaker out."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler

from . import __version__, metrics, phrases
from .measures import measure
from .speaker import Voiceprinter
from .store import Store
from .stt import SpeechToText, to_float_mono
from .trim import Trimmer

_LOG = logging.getLogger(__name__)


def request_time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class DeviceRuntime:
    """Everything one device's port needs, built once at startup."""
    name: str
    info: Info
    stt: SpeechToText
    voiceprinter: Voiceprinter
    unknown_below: float
    match_above: float
    min_training_seconds: float
    phrase_from: float = 0.45
    phrase_to: float = 0.55
    phrase_mode: str = "shadow"
    publish_speaker: bool = False
    trimmer: Trimmer | None = None
    trim_silence: bool = False
    hears_own_speaker: bool = False   # the patch: its mic hears its own speaker; her voice is matched too
    assistant_device: str | None = None   # its device in the voice assistant (settings recorded with each clip)


class SttHandler(AsyncEventHandler):
    def __init__(self, device: DeviceRuntime, store: Store, limit: asyncio.Semaphore,
                 log_dir: Path, access, habits, publisher, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.device = device
        self.store = store
        self.limit = limit
        self.log_dir = log_dir
        self.habits = habits
        self.publisher = publisher
        peer = self.writer.get_extra_info("peername")
        self.address = peer[0] if peer else None
        self.client = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        self.permitted = access.allowed(self.address)
        if not self.permitted:
            access.note_refused(self.address, device.name)
        self._reset()

    async def run(self) -> None:
        if not self.permitted:  # not on the permitted list: hang up before reading anything
            self.writer.close()
            return
        await super().run()

    def _reset(self) -> None:
        self.audio = bytearray()
        self.rate, self.width, self.channels = 16000, 2, 1
        self.request: metrics.Request | None = None

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self.device.info.event())
            return True

        if Transcribe.is_type(event.type):
            return True

        if AudioStart.is_type(event.type):
            start = AudioStart.from_event(event)
            self._reset()
            self.rate, self.width, self.channels = start.rate, start.width, start.channels
            self.request = metrics.Request(self.log_dir, self.client)
            self.request.start_step()
            return True

        if AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            if self.request is None:  # audio without a start: still accept it
                self.rate, self.width, self.channels = chunk.rate, chunk.width, chunk.channels
                self.request = metrics.Request(self.log_dir, self.client)
                self.request.start_step()
            self.audio.extend(chunk.audio)
            return True

        if AudioStop.is_type(event.type):
            await self._finish()
            return False  # one request per connection, like other Wyoming STT servers

        return True

    async def _finish(self) -> None:
        request = self.request or metrics.Request(self.log_dir, self.client)
        request.end_step("receive")

        async def reply(text: str, context: dict) -> None:
            await self.write_event(Transcript(text=text, context=context).event())

        await process(self.device, self.store, self.limit, self.habits, self.publisher,
                      bytes(self.audio), self.rate, self.width, self.channels, request, reply)
        self._reset()


async def process(dev: DeviceRuntime, store: Store, limit: asyncio.Semaphore, habits, publisher,
                  pcm: bytes, rate: int, width: int, channels: int, request: metrics.Request,
                  reply=None, publish: bool = True, sample: bool = False) -> tuple[str, dict]:
    """One request, start to finish: the same steps whether audio came from a satellite
    (through a listening port), the Try it button or the sample household. Returns the text and context.
    sample: marks the clip and its log lines, so removing the sample takes them away."""
    frame = width * channels
    audio_s = len(pcm) / (rate * frame) if frame and rate else 0.0

    def voiceprint(pcm: bytes):
        return dev.voiceprinter.voiceprint(to_float_mono(pcm, width, channels), rate)

    def sound(pcm: bytes) -> dict:
        return measure(to_float_mono(pcm, width, channels), rate)

    speech_s = None   # seconds decoded after trimming; None when the device doesn't trim

    def words(pcm: bytes) -> str:
        nonlocal speech_s
        samples = to_float_mono(pcm, width, channels)
        if dev.trim_silence and dev.trimmer is not None:
            try:
                samples = dev.trimmer.trim(samples, rate)
                speech_s = round(samples.size / rate, 2)
            except Exception as err:  # the detector is a helper; never fail a request over it
                _LOG.error("Trimming failed, decoding the whole clip: %r", err)
        return dev.stt.transcribe_samples(samples, rate) if samples.size else ""

    error = None
    text, print_ = "", None
    request.start_step()
    async with limit:
        request.end_step("queue")
        request.start_step()
        request.start_cpu()
        # transcript, voiceprint and how it sounds are worked out at the same time; each is timed
        # on its own too (steps stt, voiceprint, sound), the together time is stt+voiceprint
        def timed(name, fn):
            def run(pcm: bytes):
                t0 = time.perf_counter()
                try:
                    return fn(pcm)
                finally:
                    request.fields["steps_ms"][name] = round((time.perf_counter() - t0) * 1000, 1)
            return run
        results = await asyncio.gather(asyncio.to_thread(timed("stt", words), pcm),
                                       asyncio.to_thread(timed("voiceprint", voiceprint), pcm),
                                       asyncio.to_thread(timed("sound", sound), pcm), return_exceptions=True)
        request.end_cpu()
        request.end_step("stt+voiceprint")
    if isinstance(results[0], BaseException):
        error = repr(results[0])
        _LOG.error("Transcription failed: %s", error)
    else:
        text = results[0]
    if isinstance(results[1], BaseException):
        _LOG.error("Voiceprint failed: %r", results[1])
    else:
        print_ = results[1]
    measures = {} if isinstance(results[2], BaseException) else {**results[2], "speech_s": speech_s}

    request.start_step()
    model = dev.voiceprinter.model.name
    retrain = store.retrain
    own = retrain.overrides(dev.name, model) if retrain else None
    result = store.match(model, print_, dev.unknown_below, dev.match_above, own,
                         own_voice=dev.hears_own_speaker)
    shadow = None   # what a pending retrain on this device would have said; today's call decides
    if retrain and print_ is not None and retrain.has_trial(dev.name, model):
        trial = store.match(model, print_, dev.unknown_below, dev.match_above,
                            {**own, **retrain.overrides(dev.name, model, trial=True)}, own_voice=dev.hears_own_speaker)
        shadow = {k: trial.get(k) for k in ("label", "speaker", "guess", "score")}
    if dev.phrase_mode != "off" and result["label"] == "maybe" and text:
        try:
            result = phrases.decide(result, text, habits.current(), dev.phrase_from,
                                    dev.phrase_to, dev.phrase_mode)
        except Exception as err:  # phrases are a helper; never fail a request over them
            _LOG.error("Phrase check failed: %r", err)
    heard = {
        "measures": measures,
        "heard_with": {"stt_model": dev.stt.model.name, "voice_model": model, "trim_silence": dev.trim_silence,
                       "vad": ({"name": dev.trimmer.name, **dev.trimmer.settings}
                               if dev.trim_silence and dev.trimmer else None),
                       "oread": __version__},
        "period": retrain.period(dev.name) if retrain else None,
        "assistant_settings": publisher.device_settings(dev.assistant_device) if publisher else None,
        "shadow": shadow,
    }
    if sample:
        heard["sample"] = True
    clip_id = None
    if text:  # clips with no words are not saved
        try:
            clip_id = await asyncio.to_thread(
                store.save_clip, device=dev.name, pcm=pcm, rate=rate,
                width=width, channels=channels, transcript=text,
                audio_s=audio_s, trainable=audio_s >= dev.min_training_seconds,  # as of recording
                model=model, voiceprint=print_, result=result, extra=heard)
        except OSError as err:
            _LOG.error("Could not save clip: %s", err)
    try:   # the device's sound history, kept when the clip goes (and for requests with no words)
        store.measures.add(dev.name, {"time": request_time(), "clip": clip_id, "no_speech": not text,
                                      "try_it": not publish, "label": result["label"],
                                      "guess": result["guess"], "score": result["score"], **heard})
    except OSError as err:
        _LOG.error("Could not log the clip's measures: %s", err)
    request.end_step("match+save")

    published = None
    if publish and dev.publish_speaker and publisher and publisher.configured and text:
        # before the reply, so the sensor is current when Home Assistant passes the text on
        request.start_step()
        published = await publisher.publish(dev.name, result, clip_id)
        request.end_step("publish")

    context = {"speaker": result["speaker"], "label": result["label"],
               "guess": result["guess"], "score": result["score"], "by": result.get("by"),
               "device": dev.name, "clip": clip_id, "own_voice": bool(result.get("own_voice")),
               # Oread's own times for the caller (the house router's Stats): speech to text and the voiceprint apart
               "stt_ms": request.fields["steps_ms"].get("stt"), "voiceprint_ms": request.fields["steps_ms"].get("voiceprint")}
    if reply is not None:
        request.start_step()
        try:
            await reply(text, context)
        except (ConnectionError, OSError) as err:
            # the device hung up before the words went back (it gave up waiting): nothing more to do
            _LOG.info("%s hung up before the reply was sent (%r)", dev.name, err)
        request.end_step("reply")

    fields = {
        "device": dev.name,
        "audio_s": round(audio_s, 2),
        "text": text,
        "speech_s": speech_s,
        "model": dev.stt.model.name,
        "speaker_model": model,
        "speaker": result["speaker"],
        "label": result["label"],
        "guess": result["guess"],
        "score": result["score"],
        "by": result.get("by"),
        "phrase": result.get("phrase"),
        "shadow": shadow,
        "published": published,
        "clip": clip_id,
    }
    if error:
        fields["error"] = error
    if sample:
        fields["sample"] = True
    request.finish(**fields)
    return text, {**context, "phrase": result.get("phrase"), "audio_s": round(audio_s, 2),
                  "trainable": audio_s >= dev.min_training_seconds}
