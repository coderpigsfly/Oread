"""Phrase habits: which words and phrases each person uses most.

Built from the transcripts of clips assigned to a profile. A phrase is
2 to 4 words in a row; each is counted once per clip, so the number means
"how many requests used it". Phrases made only of filler words ("of the")
are skipped, and a shorter phrase is dropped when a longer phrase holding it
was used just as often ("check the" inside "check the windows").

Phrase habits also help identify a speaker, in one narrow case: when the
voice match is in a set range (phrase_from to phrase_to: a fair guess, not
yet a sure one). Then a habit phrase in what was said can confirm the voice's
guess, or pick between two people the voice found nearly tied. Phrases never
rule anyone out, never override a clear voice match, and never name someone
the voice didn't already point to. As voiceprints improve, fewer requests
land in the range and phrases matter less on their own.

A habit is a phrase that person used in at least HABIT_MIN_CLIPS of their
clips, and that mostly belongs to them (HABIT_SHARE of all assigned clips
containing it are theirs), so "turn on the lights", which everyone says,
points to nobody.
"""

from __future__ import annotations

import re
from collections import Counter

FILLER = set("""
a an the and or but so of to in on at for with from by is are was were be been am
i me my you your it its this that these those we us our he she they them his her
do does did can could would should will just please hey ok okay um uh
""".split())


HABIT_MIN_CLIPS = 3
HABIT_SHARE = 0.6
CLOSE = 0.05          # voice scores this close to the best count as nearly tied
MODES = ("off", "shadow", "on")


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def top_phrases(transcripts: list[str], top: int = 10) -> dict:
    phrase_counts: Counter = Counter()
    word_counts: Counter = Counter()
    for text in transcripts:
        w = words(text)
        word_counts.update({x for x in w if x not in FILLER})
        seen = set()
        for n in (2, 3, 4):
            for i in range(len(w) - n + 1):
                gram = tuple(w[i:i + n])
                if all(x in FILLER for x in gram):
                    continue
                seen.add(gram)
        phrase_counts.update(seen)

    # drop a phrase when a longer phrase containing it has the same count
    kept = {}
    for gram, count in phrase_counts.items():
        if count < 2:
            continue
        covered = any(
            len(other) > len(gram) and phrase_counts[other] == count and _contains(other, gram)
            for other in phrase_counts
        )
        if not covered:
            kept[" ".join(gram)] = count
    phrases = sorted(kept.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[:top]
    return {
        "clips": len(transcripts),
        "phrases": [{"phrase": p, "clips": c} for p, c in phrases],
        "words": [{"word": w, "clips": c} for w, c in word_counts.most_common() if c >= 2][:top],
    }


def _contains(longer: tuple, shorter: tuple) -> bool:
    n = len(shorter)
    return any(longer[i:i + n] == shorter for i in range(len(longer) - n + 1))


def grams(text: str) -> set[tuple]:
    """The 2-4 word phrases in a text, skipping ones made only of filler."""
    w = words(text)
    return {tuple(w[i:i + n]) for n in (2, 3, 4) for i in range(len(w) - n + 1)
            if not all(x in FILLER for x in w[i:i + n])}


class Habits:
    """Each person's distinctive phrases, rebuilt when assignments change."""

    def __init__(self, store) -> None:
        self.store = store
        self._key = None
        self._habits: dict[str, dict[tuple, float]] = {}

    def current(self) -> dict[str, dict[tuple, float]]:
        assigned = self.store.assigned_transcripts()   # [(clip id, profile, transcript)]
        key = hash(tuple((cid, prof) for cid, prof, _ in assigned))
        if key != self._key:
            self._habits = _build(assigned)
            self._key = key
        return self._habits

    def view(self, name: str) -> list[dict]:
        habits = self.current().get(name, {})
        return [{"phrase": " ".join(g), "share": round(share, 2), "clips": clips}
                for g, (share, clips) in sorted(habits.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))]


def _build(assigned: list[tuple]) -> dict:
    per_person: dict[str, Counter] = {}
    overall: Counter = Counter()
    for _cid, profile, text in assigned:
        found = grams(text)
        per_person.setdefault(profile, Counter()).update(found)
        overall.update(found)
    habits: dict[str, dict] = {}
    for person, counts in per_person.items():
        mine = {}
        for gram, count in counts.items():
            share = count / overall[gram]
            if count >= HABIT_MIN_CLIPS and share >= HABIT_SHARE:
                mine[gram] = (share, count)
        habits[person] = mine
    return habits


def decide(result: dict, text: str, habits: dict, phrase_from: float, phrase_to: float,
           mode: str) -> dict:
    """Let phrase habits settle a voice match in the phrase range. Returns the result to use.

    result is the voice match (label, speaker, guess, score, close). The voice result is
    always kept; "phrase" says what phrases found. In shadow mode the answer is unchanged.
    """
    if mode == "off" or result.get("label") != "maybe" or not text:
        return result
    score = result.get("score")
    if score is None or not phrase_from <= score < phrase_to:
        return result
    said = grams(text)
    # people the voice already points to: the guess, and anyone nearly tied with it
    candidates = [c["name"] for c in result.get("close") or []
                  if c["score"] >= phrase_from and c["score"] >= score - CLOSE]
    hits = {}
    for person in candidates:
        found = [g for g in said if g in habits.get(person, {})]
        if found:
            hits[person] = max(found, key=lambda g: (len(g), habits[person][g][1]))
    if len(hits) != 1:   # nothing heard, or habits of more than one: stay "maybe"
        note = {"checked": candidates, "found": None if not hits else "more than one person"}
        return {**result, "phrase": note}
    person, gram = next(iter(hits.items()))
    note = {"checked": candidates, "found": " ".join(gram), "points_to": person,
            "applied": mode == "on"}
    if mode != "on":
        return {**result, "phrase": note}
    return {**result, "label": "known", "speaker": person, "by": "voice+phrase", "phrase": note}
