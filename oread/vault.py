"""Keys Oread uses to talk to other programs (Home Assistant, the router, MQTT...).

API tokens (auth.py) are for things calling Oread: those are kept only as
fingerprints. The keys here are the other way round: Oread has to send them,
so it must be able to read them back. They are encrypted (Fernet: AES with a
tamper check) in data/vault.json, and the encryption key lives apart from the
data, in keys/oread.key (or the OREAD_VAULT_KEY environment variable).

So a copy of data/ alone (a backup, a clip export) holds no usable keys.
Back up keys/oread.key separately; without it the stored keys can't be read
and have to be entered again.

The API never gives a key back: it shows the name, what it's for and the last
4 characters. Keys can be set with the API (PUT /vault/{name}) or from the server:

    docker compose exec oread python -m oread.vault set <name> [service]   (asks for the key)
    docker compose exec oread python -m oread.vault list
    docker compose exec oread python -m oread.vault delete <name>
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .errors import OreadError

_LOG = logging.getLogger("oread.vault")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
_ENV = "OREAD_VAULT_KEY"


class VaultError(OreadError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hint(value: str) -> str:
    return "…" + value[-4:] if len(value) >= 12 else "(short)"


def load_key(keys_dir: Path) -> tuple[Fernet, str]:
    """The encryption key: from the environment, else keys/oread.key (made on first use)."""
    env = os.environ.get(_ENV)
    if env:
        return Fernet(env.encode()), f"the {_ENV} environment variable"
    path = keys_dir / "oread.key"
    if not path.exists():
        keys_dir.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            path.write_bytes(Fernet.generate_key())
        finally:
            os.umask(old)
        _LOG.warning("Created a new vault key in %s. Back it up apart from data/: "
                     "without it, stored keys can't be read.", path)
    path.chmod(0o600)
    return Fernet(path.read_bytes().strip()), "keys/oread.key"


class Vault:
    def __init__(self, path: Path, keys_dir: Path) -> None:
        self.path = path
        self.fernet, self.key_source = load_key(keys_dir)
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        self._mtime = 0.0
        self._reload()
        unreadable = [n for n in self._items if not self._readable(n)]
        if unreadable:
            _LOG.error("Vault keys %s can't be read with the current vault key "
                       "(was keys/oread.key replaced?). Set them again.", ", ".join(unreadable))

    # ---------- file ----------

    def _reload(self) -> None:
        """Pick up keys set from the command line while Oread runs."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._items, self._mtime = {}, 0.0
            return
        if mtime != self._mtime:
            self._items = json.loads(self.path.read_text()).get("keys", {})
            self._mtime = mtime

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        old = os.umask(0o077)
        try:
            tmp.write_text(json.dumps({"keys": self._items}, indent=2))
        finally:
            os.umask(old)
        tmp.chmod(0o600)
        tmp.replace(self.path)
        self._mtime = self.path.stat().st_mtime

    def _readable(self, name: str) -> bool:
        try:
            self.fernet.decrypt(self._items[name]["secret"].encode())
            return True
        except (InvalidToken, KeyError):
            return False

    # ---------- what the API and other parts of Oread use ----------

    def set(self, name: str, value: str, service: str | None = None,
            note: str | None = None) -> dict:
        """Create or replace a key. Service and note are kept if not given again."""
        name = name.strip().lower()
        value = value.strip()
        if not _NAME.match(name):
            raise VaultError("Key names are 1-40 lowercase letters, digits, or _ . -")
        if not value:
            raise VaultError("The key is empty")
        if len(value) > 8192:
            raise VaultError("That key is longer than 8 KB")
        with self._lock:
            self._reload()
            old = self._items.get(name, {})
            self._items[name] = {
                "service": (service if service is not None else old.get("service")) or None,
                "note": (note if note is not None else old.get("note")) or None,
                "hint": _hint(value),
                "created": old.get("created", _now()),
                "updated": _now(),
                "last_used": old.get("last_used"),
                "secret": self.fernet.encrypt(value.encode()).decode(),
            }
            self._write()
            _LOG.info("Vault key '%s' %s", name, "replaced" if old else "added")
            return self._public(name)

    def get(self, name: str) -> str:
        """The key itself, for Oread's own use when it calls another program. Never for the API."""
        with self._lock:
            self._reload()
            if name not in self._items:
                raise VaultError(f"No key named '{name}' in the vault", 404)
            item = self._items[name]
            try:
                value = self.fernet.decrypt(item["secret"].encode()).decode()
            except InvalidToken as err:
                raise VaultError(f"Key '{name}' can't be read with the current vault key; "
                                 "set it again", 409) from err
            today = _now()[:10]
            if (item.get("last_used") or "")[:10] != today:  # note use at most once a day
                item["last_used"] = _now()
                self._write()
            return value

    def delete(self, name: str) -> None:
        with self._lock:
            self._reload()
            if name not in self._items:
                raise VaultError(f"No key named '{name}' in the vault", 404)
            del self._items[name]
            self._write()
            _LOG.info("Vault key '%s' deleted", name)

    def list(self) -> dict:
        with self._lock:
            self._reload()
            return {"encryption_key_from": self.key_source,
                    "keys": [self._public(n) for n in sorted(self._items)]}

    def _public(self, name: str) -> dict:
        item = self._items[name]
        return {"name": name, "service": item.get("service"), "note": item.get("note"),
                "ends_with": item["hint"], "created": item["created"],
                "updated": item["updated"], "last_used": item.get("last_used"),
                "readable": self._readable(name)}


def main(argv: list[str]) -> None:
    from . import settings as settings_mod
    cfg = settings_mod.load()
    cfg["paths"]["data"].mkdir(parents=True, exist_ok=True)
    vault = Vault(cfg["paths"]["data"] / "vault.json", cfg["paths"]["keys"])
    usage = "usage: python -m oread.vault set <name> [service] | list | delete <name>"
    if not argv:
        sys.exit(usage)
    try:
        if argv[0] == "set" and len(argv) in (2, 3):
            # read from a prompt (or a pipe), never from the command line, so it isn't in shell history
            value = getpass.getpass("Key: ") if sys.stdin.isatty() else sys.stdin.read()
            item = vault.set(argv[1], value, argv[2] if len(argv) == 3 else None)
            print(f"Saved '{item['name']}' (ends with {item['ends_with']})")
        elif argv[0] == "list" and len(argv) == 1:
            listing = vault.list()
            print(f"Encryption key from {listing['encryption_key_from']}")
            for k in listing["keys"]:
                flag = "" if k["readable"] else "  CAN'T BE READ: set it again"
                print(f"{k['name']:24} {k['service'] or '-':16} {k['ends_with']:8} "
                      f"updated {k['updated']}  last used {k['last_used'] or 'never'}{flag}")
        elif argv[0] == "delete" and len(argv) == 2:
            vault.delete(argv[1])
            print(f"Deleted '{argv[1]}'")
        else:
            sys.exit(usage)
    except VaultError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main(sys.argv[1:])
