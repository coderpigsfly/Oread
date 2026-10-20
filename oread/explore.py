"""The Explore page's data: every clip heard, and every word of the mishearings, as flat rows
for a pivot table (each key a field to drag, filter or count by). The page works out the day,
hour and weekday from each row's time, in the viewer's own time zone.

clips: one row per clip heard (not the lines made from an assistant's voice).
words: one row per word of each mishearing with what was meant: right, swapped (meant one word,
heard another), dropped (meant but not heard) or added (heard but not meant).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[a-z0-9']+")


def words_of(text: str | None) -> list[str]:
    return _WORD.findall((text or "").lower().replace("’", "'"))


def compare(meant: str, heard: str) -> list[dict]:
    """Each word meant against each word heard: [{Kind, Meant, Heard}] in order."""
    a, b = words_of(meant), words_of(heard)
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out += [{"Kind": "right", "Meant": w, "Heard": w} for w in a[i1:i2]]
        elif op == "replace" and i2 - i1 == j2 - j1:
            out += [{"Kind": "swapped", "Meant": m, "Heard": h} for m, h in zip(a[i1:i2], b[j1:j2])]
        elif op == "replace":                  # several words heard as a different number of words
            out.append({"Kind": "swapped", "Meant": " ".join(a[i1:i2]), "Heard": " ".join(b[j1:j2])})
        elif op == "delete":
            out += [{"Kind": "dropped", "Meant": w, "Heard": ""} for w in a[i1:i2]]
        else:
            out += [{"Kind": "added", "Meant": "", "Heard": w} for w in b[j1:j2]]
    return out


def _speaker(clip: dict) -> str:
    result = clip.get("result") or {}
    return clip.get("profile") or result.get("speaker") or "unknown"


def _db(measures: dict, key: str):
    v = measures.get(key)
    return round(v, 1) if isinstance(v, (int, float)) else None


def _kind(speaker: str, assistants: set[str]) -> str:
    return "unknown" if speaker in ("unknown", "not found") else "assistant's voice" if speaker in assistants else "person"


def rows(clips: list[dict], lines: list[dict], types: dict[str, str | None], assistants: set[str] = frozenset()) -> dict:
    """clips: the store's clips (all); lines: the mishearings pulled; types: device -> its type;
    assistants: the profiles that are an assistant's voice (Speaker is: person or not)."""
    misheard: dict[str, dict] = {}
    for line in lines:
        for c in line.get("clips") or []:
            misheard.setdefault(c["clip"], line)
    clip_rows = []
    for c in clips:
        if c.get("made"):
            continue
        result, m, heard = c.get("result") or {}, c.get("measures") or {}, c.get("heard_with") or {}
        line = misheard.get(c["id"])
        speech, noise = _db(m, "speech_db"), _db(m, "noise_db")
        clip_rows.append({
            "clip": c["id"], "time": c["time"], "Device": c["device"],
            "Device type": types.get(c["device"]) or "none",
            "Speaker": _speaker(c), "Speaker is": _kind(_speaker(c), assistants), "Assigned": "yes" if c.get("profile") else "no",
            "Voice ID": result.get("label") or "none", "Score": result.get("score"),
            "Seconds": c.get("audio_s"), "Words": len(words_of(c.get("transcript"))),
            "Speech dB": speech, "Noise dB": noise,
            "Speech over noise dB": round(speech - noise, 1) if speech is not None and noise is not None else None,
            "Speech model": heard.get("stt_model") or "unknown", "Voice model": heard.get("voice_model") or "unknown",
            "Own voice": "yes" if result.get("own_voice") else "no",
            "Misheard": "yes" if line else "not flagged",
            "heard": c.get("transcript") or "", "meant": (line or {}).get("meant") or "",
        })
    by_id = {c["id"]: c for c in clips}
    word_rows = []
    for line in lines:
        if not line.get("meant") or line.get("gone"):
            continue
        found = next((by_id[c["clip"]] for c in line.get("clips") or [] if c["clip"] in by_id), None)
        first = (line.get("clips") or [{}])[0]
        where = {"Device": found["device"] if found else first.get("device") or "not found",
                 "Speaker": _speaker(found) if found else "not found",
                 "Speaker is": _kind(_speaker(found), assistants) if found else "unknown",
                 "Speech model": ((found or {}).get("heard_with") or {}).get("stt_model") or "unknown",
                 "Times": line.get("count") or 1, "clip": found["id"] if found else None,
                 "time": found["time"] if found else first.get("heard_at"),
                 "heard": line.get("said") or "", "meant": line["meant"]}
        word_rows += [{**w, **where} for w in compare(line["meant"], line.get("said") or "")]
    return {"clips": clip_rows, "words": word_rows}
