"""The model list: models.yaml (shipped), plus data/models.yaml (yours) on top.

Three kinds: speech (words), voice (who spoke), and vad (the voice detector:
tools/client.py uses it on your computer, and devices that trim the quiet use it here). Each model carries its own starting
settings (`settings:`): threads for speech and voice models, plus, for voice
models, the match thresholds and the phrase range, which depend on how that
model scores voices. `defaults:` names the model of each kind used when
nothing else chooses one.

data/models.yaml uses the same layout. An entry with a new name adds a
model; one with a shipped name changes only what it names (its settings, say),
and `defaults:` there picks other default models. The Models tab on the
Settings page writes that file (settings that differ from the shipped ones,
and the defaults you pick); you can edit it by hand too and restart.

Read once, when first needed; reload() reads it again after a change.
"""

from __future__ import annotations

import copy
import re
import threading
from functools import cache
from pathlib import Path

import yaml

from . import settings as settings_mod
from .errors import OreadError, SettingsError

SPEECH_KINDS = {"moonshine", "transducer", "nemo_transducer", "whisper"}
VAD_KINDS = {"silero"}
SECTIONS = ("speech", "voice", "vad")

# The settings a model can carry: (kind, lowest, highest, what it means). The values
# themselves live in models.yaml; this only says what's allowed and how to show it.
KNOBS = {
    "speech": {
        "num_threads": ("int", 1, 16, "CPU threads one request may use. More is faster, up to the "
                                      "cores you have; Oread works on two requests at once."),
        "language": ("text", None, None, "The language spoken, as a two-letter code (en, de, fr...). "
                                         "Only models that know several languages have this."),
    },
    "voice": {
        "num_threads": ("int", 1, 8, "CPU threads for a voiceprint. Voiceprints are small; 1 is plenty."),
        "unknown_below": ("float", 0.0, 1.0, "A best match below this is “unknown”."),
        "match_above": ("float", 0.0, 1.0, "A best match at or above this names the person. In "
                                           "between is “maybe”."),
        "phrase_from": ("float", 0.0, 1.0, "From this score up to the next, a person's habit phrases "
                                           "may settle a “maybe”."),
        "phrase_to": ("float", 0.0, 1.0, "The top of the phrase range (usually the same as match_above)."),
    },
    "vad": {
        "threshold": ("float", 0.0, 1.0, "How sure the detector must be that a moment is speech."),
        "min_silence_duration": ("float", 0.05, 3.0, "Seconds of quiet that count as a pause."),
        "min_speech_duration": ("float", 0.05, 3.0, "Seconds of sound that count as speech."),
        "keep_after_speech": ("float", 0.0, 3.0, "Seconds kept after the last speech when a device "
                                                 "trims the quiet at the end."),
    },
}

# What a model's entry says about where it comes from (the Imports page edits these;
# its own settings are on the Settings page). Files each speech kind needs, by role.
DEFINITION_FIELDS = {
    "speech": ["label", "kind", "url", "folder", "files", "languages", "author", "license", "card",
               "memory_mb", "notes"],
    "voice": ["label", "url", "file", "author", "license", "card", "memory_mb", "notes"],
    "vad": ["label", "kind", "url", "file", "author", "license", "card", "notes"],
}
FILE_ROLES = {
    "moonshine": ["preprocessor", "encoder", "uncached_decoder", "cached_decoder", "tokens"],
    "transducer": ["encoder", "decoder", "joiner", "tokens"],
    "nemo_transducer": ["encoder", "decoder", "joiner", "tokens"],
    "whisper": ["encoder", "decoder", "tokens"],
}
_MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_lock = threading.Lock()
_HEADER = ("# Your models and model settings, kept by the Imports page and the Settings page's\n"
           "# Models tab (you can edit it by hand too, then restart). Applied on top of models.yaml:\n"
           "# a new name adds a model, a shipped name changes only what it names, and\n"
           "# defaults: picks the speech and voice model devices use unless chosen otherwise.\n")


class ModelSettingsError(OreadError):
    pass


def _paths() -> tuple[Path, Path]:
    return settings_mod.APP_DIR / "models.yaml", settings_mod.load()["paths"]["data"] / "models.yaml"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@cache
def load() -> dict:
    """{"speech": {...}, "voice": {...}, "vad": {...}, "defaults": {kind: name}}: name -> entry,
    every entry checked and carrying its full `settings`."""
    shipped_path, mine_path = _paths()
    if not shipped_path.exists():
        raise SettingsError(f"{shipped_path} is missing; it lists the models Oread can use")
    return _compose(_read(shipped_path), _read(mine_path), shipped_path, mine_path)


def _compose(shipped: dict, mine: dict, shipped_path: Path, mine_path: Path) -> dict:
    catalog: dict = {section: {} for section in SECTIONS}
    catalog["defaults"] = {}
    for section in SECTIONS:
        names = list(shipped.get(section) or {}) + [n for n in (mine.get(section) or {})
                                                     if n not in (shipped.get(section) or {})]
        for name in names:
            entry = _merge((shipped.get(section) or {}).get(name) or {},
                           (mine.get(section) or {}).get(name) or {})
            path = mine_path if name in (mine.get(section) or {}) else shipped_path
            catalog[section][str(name)] = _check(section, str(name), entry, path)
        default = (mine.get("defaults") or {}).get(section) or (shipped.get("defaults") or {}).get(section)
        if not default or default not in catalog[section]:
            raise SettingsError(f"models.yaml: defaults: {section} should name one of the {section} "
                                f"models ({', '.join(catalog[section])})")
        catalog["defaults"][section] = default
    # a model listed without settings starts from the default model's
    for section in SECTIONS:
        base = catalog[section][catalog["defaults"][section]].get("settings") or {}
        for entry in catalog[section].values():
            entry["settings"] = _merge(base, entry.get("settings") or {})
    return catalog


def reload() -> None:
    """Read the files again (after the Models tab saved a change)."""
    from . import models, speaker
    load.cache_clear()
    models.all_models.cache_clear()
    speaker.all_models.cache_clear()


def _check(section: str, name: str, entry: dict, path: Path) -> dict:
    needed = {"speech": ["kind", "url", "folder", "files"], "voice": ["url", "file"],
              "vad": ["kind", "url", "file"]}[section]
    missing = [k for k in needed if not entry.get(k)]
    if missing:
        raise SettingsError(f"{path}: {section} model '{name}' needs {', '.join(missing)}")
    if section == "speech" and entry["kind"] not in SPEECH_KINDS:
        raise SettingsError(f"{path}: speech model '{name}' has kind '{entry['kind']}'; "
                            f"kinds are {', '.join(sorted(SPEECH_KINDS))}")
    for key in ("url", "card"):
        if entry.get(key) and not str(entry[key]).startswith(("https://", "http://")):
            raise SettingsError(f"{path}: {section} model '{name}': {key} should start with https://")
    if section == "speech" and entry["kind"] in FILE_ROLES:
        files = entry.get("files") or {}
        missing_roles = [r for r in FILE_ROLES[entry["kind"]] if not files.get(r)]
        if missing_roles or not isinstance(files, dict):
            raise SettingsError(f"{path}: speech model '{name}' ({entry['kind']}) needs files for "
                                f"{', '.join(missing_roles or FILE_ROLES[entry['kind']])}")
    if section == "vad" and entry["kind"] not in VAD_KINDS:
        raise SettingsError(f"{path}: voice detector '{name}' has kind '{entry['kind']}'; "
                            f"kinds are {', '.join(sorted(VAD_KINDS))}")
    try:
        check_settings(section, entry.get("settings") or {})
    except ModelSettingsError as err:
        raise SettingsError(f"{path}: {section} model '{name}': {err}") from err
    return entry


def check_settings(section: str, values: dict) -> dict:
    """Values made the right type and checked against KNOBS; refuses anything else."""
    out = {}
    for key, value in values.items():
        if key not in KNOBS[section]:
            raise ModelSettingsError(f"'{key}' isn't a {section} model setting "
                                     f"({', '.join(KNOBS[section])})")
        kind, low, high, _ = KNOBS[section][key]
        if kind == "text":
            value = str(value).strip().lower()
            if not value.isalpha() or not 2 <= len(value) <= 3:
                raise ModelSettingsError(f"{key} should be a language code like en")
        else:
            try:
                value = int(value) if kind == "int" else round(float(value), 3)
            except (TypeError, ValueError) as err:
                raise ModelSettingsError(f"{key} should be a number") from err
            if kind == "int" and value != float(values[key]):
                raise ModelSettingsError(f"{key} should be a whole number")
            if not low <= value <= high:
                raise ModelSettingsError(f"{key} must be from {low} to {high}")
        out[key] = value
    if out.get("unknown_below", 0) > out.get("match_above", 1):
        raise ModelSettingsError("unknown_below can't be higher than match_above")
    if out.get("phrase_from", 0) > out.get("phrase_to", 1):
        raise ModelSettingsError("phrase_from can't be higher than phrase_to")
    return out


def shipped_settings(section: str, name: str) -> dict:
    shipped, _ = _paths()
    entry = ((_read(shipped).get(section) or {}).get(name)) or {}
    return entry.get("settings") or {}


def save(section: str, name: str, settings: dict | None = None, make_default: bool = False,
         back_to_shipped: bool = False) -> None:
    """Write a change to data/models.yaml: a model's settings (only what differs from the shipped
    ones), the default model, or a model back to its shipped settings. Then reload."""
    if section not in SECTIONS:
        raise ModelSettingsError("section is speech or voice")
    current = load()
    if name not in current[section]:
        raise ModelSettingsError(f"No {section} model named '{name}'", 404)
    with _lock:
        _, mine_path = _paths()
        mine = _read(mine_path)
        entries = mine.setdefault(section, {}) or {}
        mine[section] = entries
        entry = entries.get(name) or {}
        if settings is not None:
            allowed = set(current[section][name]["settings"])
            unknown = sorted(set(settings) - allowed)
            if unknown:
                raise ModelSettingsError(f"{name} has no setting {', '.join(unknown)}")
            full = check_settings(section, {**current[section][name]["settings"], **settings})
            shipped = shipped_settings(section, name)
            changed = {k: v for k, v in full.items() if shipped.get(k) != v} if shipped else full
            if changed:
                entry["settings"] = changed
            else:
                entry.pop("settings", None)
        if back_to_shipped:
            if not shipped_settings(section, name):
                raise ModelSettingsError(f"{name} isn't a shipped model, so it has no shipped settings", 409)
            entry.pop("settings", None)
        if entry:
            entries[name] = entry
        else:
            entries.pop(name, None)
        if not entries:
            mine.pop(section, None)
        if make_default:
            mine.setdefault("defaults", {})[section] = name
        _write(mine_path, mine)
        reload()


# ---------- the Imports page: where each model comes from ----------

def shipped_entry(section: str, name: str) -> dict:
    shipped, _ = _paths()
    return copy.deepcopy(((_read(shipped).get(section) or {}).get(name)) or {})


def _clean_definition(section: str, fields: dict) -> dict:
    out = {}
    for key, value in (fields or {}).items():
        if key not in DEFINITION_FIELDS[section]:
            raise ModelSettingsError(f"'{key}' isn't part of a {section} model's entry")
        if key == "memory_mb":
            try:
                value = int(value or 0)
            except (TypeError, ValueError) as err:
                raise ModelSettingsError("memory_mb should be a whole number of MB") from err
            if value < 0:
                raise ModelSettingsError("memory_mb can't be negative")
        elif key == "languages":
            items = value.split(",") if isinstance(value, str) else list(value or [])
            value = [str(v).strip().lower() for v in items if str(v).strip()] or ["en"]
        elif key == "files":
            if not isinstance(value, dict):
                raise ModelSettingsError("files should list each role and its file")
            value = {str(r).strip(): str(f).strip() for r, f in value.items() if str(f).strip()}
        else:
            value = str(value or "").strip()
        out[key] = value
    return out


def save_definition(section: str, name: str, fields: dict, new: bool = False) -> None:
    """Add a model (new=True, every needed field given) or change where one comes from. For a
    shipped model only what differs from models.yaml is kept, beside any settings of yours.
    Checked as a whole before anything is written, so a bad entry never stops Oread."""
    if section not in SECTIONS:
        raise ModelSettingsError("kind is speech, voice or vad")
    current = load()
    name = (name or "").strip()
    if new:
        if not _MODEL_NAME.match(name):
            raise ModelSettingsError("Model names are lowercase letters, digits, . _ or - (up to 64)")
        if name in current[section]:
            raise ModelSettingsError(f"There's already a {section} model named '{name}'", 409)
    elif name not in current[section]:
        raise ModelSettingsError(f"No {section} model named '{name}'", 404)
    cleaned = _clean_definition(section, fields)
    shipped = shipped_entry(section, name)
    with _lock:
        shipped_path, mine_path = _paths()
        mine = _read(mine_path)
        entries = mine.get(section) or {}
        entry = {k: v for k, v in (entries.get(name) or {}).items() if k == "settings"}
        if shipped:
            merged = {**{k: shipped.get(k) for k in DEFINITION_FIELDS[section] if k in shipped}, **cleaned}
            entry.update({k: v for k, v in merged.items() if shipped.get(k) != v})
        else:
            base = {k: v for k, v in (entries.get(name) or {}).items() if k != "settings"}
            entry.update({**base, **cleaned})
        trial = copy.deepcopy(mine)
        trial.setdefault(section, {})
        trial[section] = {**(trial[section] or {}), name: entry} if entry else \
            {k: v for k, v in (trial[section] or {}).items() if k != name}
        try:
            _compose(_read(shipped_path), trial, shipped_path, mine_path)
        except SettingsError as err:
            raise ModelSettingsError(str(err).split(": ", 1)[-1]) from err
        _write(mine_path, trial)
        reload()


def reset_definition(section: str, name: str) -> str:
    """A shipped model goes back to models.yaml's entry (your settings for it stay); a model you
    added is taken off the list. Says which: "shipped" or "removed"."""
    current = load()
    if name not in current.get(section, {}):
        raise ModelSettingsError(f"No {section} model named '{name}'", 404)
    shipped = shipped_entry(section, name)
    if not shipped and current["defaults"][section] == name:
        raise ModelSettingsError(f"{name} is the default {section} model; make another the default first", 409)
    with _lock:
        shipped_path, mine_path = _paths()
        mine = _read(mine_path)
        entries = dict(mine.get(section) or {})
        if shipped:
            kept = {k: v for k, v in (entries.get(name) or {}).items() if k == "settings"}
            if kept:
                entries[name] = kept
            else:
                entries.pop(name, None)
        else:
            entries.pop(name, None)
        trial = {**mine, section: entries} if entries else {k: v for k, v in mine.items() if k != section}
        _compose(_read(shipped_path), trial, shipped_path, mine_path)
        _write(mine_path, trial)
        reload()
    return "shipped" if shipped else "removed"


def _write(mine_path: Path, mine: dict) -> None:
    mine_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = mine_path.with_suffix(".tmp")
    tmp.write_text(_HEADER + (yaml.safe_dump(mine, sort_keys=False, allow_unicode=True) if mine else ""))
    tmp.replace(mine_path)
