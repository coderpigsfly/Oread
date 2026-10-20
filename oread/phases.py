"""Developer flags for a staged build (the phased-build rule, as in the house router's veil/phases.py).
Each stage's new code runs only while its flag is on; the old path stays in the else. Hard-coded on
purpose, for the developers only, not a setting: the tests run with each flag on and off, then the
household tries it by voice; a refactor pulls the flags out once that's done."""

PHASES: dict[str, bool] = {
    # none now: oread1 to oread4 (stage 1, Explore and her voice, her voice from the echoes, where the time
    # goes) were taken out Oct 20, after they'd been lived on: their new paths are the only ones
}


def on(name: str) -> bool:
    return bool(PHASES.get(name))
