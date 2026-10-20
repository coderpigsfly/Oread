"""Draw the README's charts as SVG files, from the benchmark numbers written below.

    python3 docs/images/make_charts.py

The numbers come from tools/bench.py (speech, Oct 11) and the voiceprint
clip-length test (TitaNet small), both recorded in the design doc, and a\ncore-limited run (docker run --cpus) for the cores chart. Each SVG
carries its own light and dark colours and follows the reader's setting.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

# speech models: (label, word errors %, seconds per short command, memory MB)
SPEECH = [
    ("Zipformer", 17.9, 0.3, 170),
    ("Moonshine", 10.4, 0.5, 380),
    ("Parakeet", 9.4, 1.1, 810),
    ("Whisper small", 15.1, 4.6, 950),
]

# TitaNet small: clip length (s) -> same voice (lowest), different voices (highest)
CLIP_S = [1.0, 1.5, 2.0, 3.0]
SAME_LOWEST = [0.31, 0.42, 0.60, 0.66]
OTHER_HIGHEST = [0.39, 0.34, 0.41, 0.29]
UNKNOWN_BELOW, NAMED_AT = 0.35, 0.55

# seconds per short command (median) by CPU cores, Oread limited by Docker (Oct 20)
CORES = [1, 2, 4]
CORE_SECONDS = [("Moonshine", [3.2, 1.3, 0.40]), ("Parakeet", [10.9, 3.5, 1.28])]

STYLE = """<style>
  .bg { fill: #fcfcfb; } .ink { fill: #0b0b0b; } .ink2 { fill: #52514e; }
  .grid { stroke: #e4e3df; } .axis { stroke: #b9b8b2; }
  .s1 { fill: #2a78d6; stroke: #2a78d6; } .s2 { fill: #eb6834; stroke: #eb6834; }
  .rule { stroke: #8a8984; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #1a1a19; } .ink { fill: #f0efec; } .ink2 { fill: #c3c2b7; }
    .grid { stroke: #2e2e2c; } .axis { stroke: #55554f; }
    .s1 { fill: #3987e5; stroke: #3987e5; } .s2 { fill: #d95926; stroke: #d95926; }
    .rule { stroke: #8f8e88; }
  }
  .line { fill: none; }   /* after the dark colours, so a line is never filled */
  text { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
</style>"""


def svg(width: int, height: int, title: str, desc: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}" role="img" aria-labelledby="t d">\n<title id="t">{title}</title>\n'
            f'<desc id="d">{desc}</desc>\n{STYLE}\n<rect class="bg" width="{width}" height="{height}" rx="8"/>\n'
            f'{body}\n</svg>\n')


def speech_chart() -> str:
    w, h, left, right, top, bottom = 720, 420, 70, 40, 70, 60
    x0, x1, y0, y1 = 0.0, 5.0, 8.0, 20.0     # seconds, word errors %
    sx = lambda v: left + (v - x0) / (x1 - x0) * (w - left - right)
    sy = lambda v: top + (v - y0) / (y1 - y0) * (h - top - bottom)   # fewer errors sits higher
    out = [f'<text class="ink" x="{left}" y="30" font-size="17" font-weight="600">'
           'Speech models: accuracy against speed</text>',
           f'<text class="ink2" x="{left}" y="50" font-size="13">'
           'Same 17 clips on a 4-core Xeon VM without AVX2. Up and to the left is better.</text>']
    for e in range(8, 21, 2):
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{sy(e):.1f}" y2="{sy(e):.1f}"/>')
        out.append(f'<text class="ink2" x="{left - 8}" y="{sy(e) + 4:.1f}" font-size="12" '
                   f'text-anchor="end">{e}%</text>')
    for s in range(0, 6):
        out.append(f'<text class="ink2" x="{sx(s):.1f}" y="{h - bottom + 20}" font-size="12" '
                   f'text-anchor="middle">{s} s</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{w - right}" y1="{h - bottom}" y2="{h - bottom}"/>')
    out.append(f'<text class="ink2" x="{(left + w - right) / 2:.0f}" y="{h - 12}" font-size="12" '
               'text-anchor="middle">Time per short command (seconds)</text>')
    out.append(f'<text class="ink2" x="18" y="{(top + h - bottom) / 2:.0f}" font-size="12" text-anchor="middle" '
               f'transform="rotate(-90 18 {(top + h - bottom) / 2:.0f})">Word errors (fewer is higher)</text>')
    for label, err, secs, mem in SPEECH:
        cx, cy = sx(secs), sy(err)
        out.append(f'<circle class="s1" cx="{cx:.1f}" cy="{cy:.1f}" r="7"/>')
        anchor, dx = ("end", -12) if secs > 4 else ("start", 12)
        out.append(f'<text class="ink" x="{cx + dx:.1f}" y="{cy - 2:.1f}" font-size="13" font-weight="600" '
                   f'text-anchor="{anchor}">{label}</text>')
        out.append(f'<text class="ink2" x="{cx + dx:.1f}" y="{cy + 14:.1f}" font-size="12" '
                   f'text-anchor="{anchor}">{err}% errors · {secs} s · ~{mem} MB</text>')
    return svg(w, h, "Speech models: accuracy against speed",
               "Word error rate against time per command for four speech models. Parakeet makes the "
               "fewest errors (9.4%) in 1.1 s; Moonshine 10.4% in 0.5 s; Zipformer 17.9% in 0.3 s; "
               "Whisper small 15.1% in 4.6 s.", "\n".join(out))


def voice_chart() -> str:
    w, h, left, right, top, bottom = 720, 420, 70, 200, 70, 60
    x0, x1, y0, y1 = 0.75, 3.25, 0.0, 1.0
    sx = lambda v: left + (v - x0) / (x1 - x0) * (w - left - right)
    sy = lambda v: h - bottom - (v - y0) / (y1 - y0) * (h - top - bottom)
    out = [f'<text class="ink" x="{left}" y="30" font-size="17" font-weight="600">'
           'Telling voices apart (TitaNet small): longer clips separate better</text>',
           f'<text class="ink2" x="{left}" y="50" font-size="13">'
           'Worst cases on public LibriSpeech voices, by how long the person spoke.</text>']
    for v in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}"/>')
        out.append(f'<text class="ink2" x="{left - 8}" y="{sy(v) + 4:.1f}" font-size="12" '
                   f'text-anchor="end">{v:.1f}</text>')
    for c in CLIP_S:
        out.append(f'<text class="ink2" x="{sx(c):.1f}" y="{h - bottom + 20}" font-size="12" '
                   f'text-anchor="middle">{c:g} s</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{w - right}" y1="{h - bottom}" y2="{h - bottom}"/>')
    out.append(f'<text class="ink2" x="{(left + w - right) / 2:.0f}" y="{h - 12}" font-size="12" '
               'text-anchor="middle">Length of speech in the clip</text>')
    out.append(f'<text class="ink2" x="18" y="{(top + h - bottom) / 2:.0f}" font-size="12" text-anchor="middle" '
               f'transform="rotate(-90 18 {(top + h - bottom) / 2:.0f})">Match score</text>')
    for value, name in ((NAMED_AT, "Person named at 0.55"), (UNKNOWN_BELOW, "Unknown below 0.35")):
        out.append(f'<line class="rule" x1="{left}" x2="{w - right}" y1="{sy(value):.1f}" y2="{sy(value):.1f}" '
                   'stroke-dasharray="5 4" stroke-width="1.5"/>')
        out.append(f'<text class="ink2" x="{w - right + 8}" y="{sy(value) + 4:.1f}" font-size="12">{name}</text>')
    for series, values, label in (("s1", SAME_LOWEST, "Right person, lowest"),
                                  ("s2", OTHER_HIGHEST, "Anyone else, highest")):
        points = " ".join(f"{sx(c):.1f},{sy(v):.1f}" for c, v in zip(CLIP_S, values))
        out.append(f'<polyline class="{series} line" points="{points}" stroke-width="2"/>')
        for c, v in zip(CLIP_S, values):
            out.append(f'<circle class="{series}" cx="{sx(c):.1f}" cy="{sy(v):.1f}" r="5"/>')
        last_x, last_y = sx(CLIP_S[-1]), sy(values[-1])
        out.append(f'<text class="ink" x="{last_x - 10:.1f}" y="{last_y + (-12 if series == "s1" else 22):.1f}" '
                   f'font-size="13" font-weight="600" text-anchor="end">{label}</text>')
    return svg(w, h, "Telling voices apart with TitaNet small",
               "Lowest score for the right person rises from 0.31 at 1 second of speech to 0.66 at 3 seconds; "
               "the highest score for anyone else stays between 0.29 and 0.41. Oread names a person at 0.55 "
               "and calls a voice unknown below 0.35, so clips of 2 seconds or more are reliable.",
               "\n".join(out))


def cores_chart() -> str:
    w, h, left, right, top, bottom = 720, 420, 70, 120, 70, 60
    x0, x1, y0, y1 = 0.75, 4.25, 0.0, 12.0
    sx = lambda v: left + (v - x0) / (x1 - x0) * (w - left - right)
    sy = lambda v: h - bottom - (v - y0) / (y1 - y0) * (h - top - bottom)
    out = [f'<text class="ink" x="{left}" y="30" font-size="17" font-weight="600">'
           'Time per command by CPU cores</text>',
           f'<text class="ink2" x="{left}" y="50" font-size="13">'
           'Oread limited by Docker on the same Xeon VM without AVX2, 15 household commands.</text>']
    for v in range(0, 13, 2):
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}"/>')
        out.append(f'<text class="ink2" x="{left - 8}" y="{sy(v) + 4:.1f}" font-size="12" '
                   f'text-anchor="end">{v} s</text>')
    for c in CORES:
        out.append(f'<text class="ink2" x="{sx(c):.1f}" y="{h - bottom + 20}" font-size="12" '
                   f'text-anchor="middle">{c}</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{w - right}" y1="{h - bottom}" y2="{h - bottom}"/>')
    out.append(f'<text class="ink2" x="{(left + w - right) / 2:.0f}" y="{h - 12}" font-size="12" '
               'text-anchor="middle">CPU cores</text>')
    out.append(f'<text class="ink2" x="18" y="{(top + h - bottom) / 2:.0f}" font-size="12" text-anchor="middle" '
               f'transform="rotate(-90 18 {(top + h - bottom) / 2:.0f})">Seconds per command</text>')
    for series, (label, values) in zip(("s1", "s2"), CORE_SECONDS):
        points = " ".join(f"{sx(c):.1f},{sy(v):.1f}" for c, v in zip(CORES, values))
        out.append(f'<polyline class="{series} line" points="{points}" stroke-width="2"/>')
        for c, v in zip(CORES, values):
            out.append(f'<circle class="{series}" cx="{sx(c):.1f}" cy="{sy(v):.1f}" r="5"/>')
            anchor, dx = ("end", -10) if c == CORES[-1] else ("start", 10)
            out.append(f'<text class="ink2" x="{sx(c) + dx:.1f}" y="{sy(v) - 8:.1f}" font-size="12" '
                       f'text-anchor="{anchor}">{v:g} s</text>')
        out.append(f'<text class="ink" x="{sx(CORES[-1]) + 14:.1f}" y="{sy(values[-1]) + 4:.1f}" '
                   f'font-size="13" font-weight="600">{label}</text>')
    return svg(w, h, "Time per command by CPU cores",
               "Seconds per short command with Oread limited to 1, 2 and 4 cores. Moonshine: 3.2, 1.3 and "
               "0.40 s. Parakeet: 10.9, 3.5 and 1.28 s.", "\n".join(out))


if __name__ == "__main__":
    (HERE / "speech-models.svg").write_text(speech_chart())
    (HERE / "voice-separation.svg").write_text(voice_chart())
    (HERE / "cpu-cores.svg").write_text(cores_chart())
    print("Wrote", HERE / "speech-models.svg", HERE / "voice-separation.svg", "and", HERE / "cpu-cores.svg")
