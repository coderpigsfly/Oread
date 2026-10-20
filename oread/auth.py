"""API tokens: how programs use the API (people sign in to Oread's pages instead).

Tokens are stored only as fingerprints (SHA-256) in data/tokens.json, so the
file never holds a usable token. A token is shown once, when it's created.
Make them with the API (POST /tokens), or from the server:

    docker compose exec oread python -m oread.auth create <name> [role]
    docker compose exec oread python -m oread.auth list
    docker compose exec oread python -m oread.auth revoke <name>

Each token has a role, like a person (see users.py): administrator unless
another is given. Only a super user, or the server's command line, can make a
super token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .errors import OreadError

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")
_PREFIX = "oread_"


class TokenError(OreadError):
    pass


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._tokens: dict[str, dict] = {}
        self._mtime = 0.0
        self._last_write: dict[str, float] = {}
        self._reload()

    def _reload(self) -> None:
        """Pick up tokens created from the command line while Oread runs."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._tokens, self._mtime = {}, 0.0
            return
        if mtime != self._mtime:
            self._tokens = json.loads(self.path.read_text()).get("tokens", {})
            self._mtime = mtime

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tokens": self._tokens}, indent=2))
        tmp.chmod(0o600)
        tmp.replace(self.path)
        self._mtime = self.path.stat().st_mtime

    def role(self, name: str) -> str:
        with self._lock:
            return self._tokens.get(name, {}).get("role", "administrator")

    def create(self, name: str, role: str = "administrator") -> str:
        name = name.strip()
        if not _NAME.match(name):
            raise TokenError("Token names are 1-40 letters, digits, spaces, or _ . -")
        with self._lock:
            self._reload()
            if any(n.lower() == name.lower() for n in self._tokens):
                raise TokenError(f"A token named '{name}' already exists", 409)
            token = _PREFIX + secrets.token_urlsafe(32)
            self._tokens[name] = {"fingerprint": _fingerprint(token), "created": _now(),
                                  "last_used": None, "role": role}
            self._write()
            return token

    def revoke(self, name: str) -> None:
        with self._lock:
            self._reload()
            if name not in self._tokens:
                raise TokenError(f"No token named '{name}'", 404)
            del self._tokens[name]
            self._write()

    def list(self) -> list[dict]:
        with self._lock:
            self._reload()
            return [{"name": n, "role": t.get("role", "administrator"), "created": t["created"],
                     "last_used": t["last_used"]}
                    for n, t in sorted(self._tokens.items())]

    def check(self, token: str | None) -> str | None:
        """The token's name if it's permitted, else None."""
        if not token:
            return None
        fp = _fingerprint(token)
        with self._lock:
            self._reload()
            for name, info in self._tokens.items():
                if hmac.compare_digest(info["fingerprint"], fp):
                    now = time.monotonic()
                    if now - self._last_write.get(name, 0) > 60:  # note use, at most once a minute
                        info["last_used"] = _now()
                        self._last_write[name] = now
                        self._write()
                    return name
        return None


def main(argv: list[str]) -> None:
    from . import settings as settings_mod
    cfg = settings_mod.load()
    store = TokenStore(cfg["paths"]["data"] / "tokens.json")
    usage = "usage: python -m oread.auth create <name> [role] | list | revoke <name>"
    if not argv:
        sys.exit(usage)
    try:
        if argv[0] == "create" and len(argv) in (2, 3):
            from .users import ROLES
            role = argv[2] if len(argv) == 3 else "administrator"
            if role not in ROLES:
                sys.exit(f"Roles are: {', '.join(ROLES)}")
            token = store.create(argv[1], role)
            print(f"Token '{argv[1]}' (copy it now; it won't be shown again):\n{token}")
        elif argv[0] == "list":
            for t in store.list():
                print(f"{t['name']:20} {t['role']:14} created {t['created']}  "
                      f"last used {t['last_used'] or 'never'}")
        elif argv[0] == "revoke" and len(argv) == 2:
            store.revoke(argv[1])
            print(f"Revoked '{argv[1]}'")
        else:
            sys.exit(usage)
    except TokenError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main(sys.argv[1:])
