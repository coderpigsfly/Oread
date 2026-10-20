"""People who sign in to Oread's pages: accounts, roles, sessions and first-run setup.

Roles, highest first. Each role can grant and manage only roles below its own
(a super user can also make other super users):

    super        everything: the vault, permitted addresses, administrators
    administrator devices, settings, API tokens, Home Assistant, reviewers and viewers
    reviewer     listen to clips, assign them, create and rename profiles
    viewer       stats pages only

Passwords are hashed with scrypt (a random salt per user, settings kept with
the hash so they can be strengthened later), never encrypted: Oread only ever
checks a password, it never needs one back. Accounts live in data/users.json
(mode 600). Sessions are random IDs in the browser's cookie, stored here only
as fingerprints in data/sessions.json, so a restart signs nobody out.

First run: while there are no accounts, Oread makes a one-time setup code,
prints it in its log and keeps it in data/setup-code.txt (readable only on the
server). It stays the same across restarts until it's used, then the file is
deleted. The setup screen asks for it, then a username and password, and that
person becomes the super user. Reading the code proves you control the server.

A forgotten password is reset from the server:

    docker compose exec oread python -m oread.users reset <name>
    docker compose exec oread python -m oread.users list
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .errors import OreadError

ROLES = ("viewer", "reviewer", "administrator", "super")
RANK = {role: i for i, role in enumerate(ROLES, start=1)}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
MIN_PASSWORD = 10
LOCK_AFTER = 5            # wrong passwords in a row ...
LOCK_SECONDS = 15 * 60    # ... lock that name for this long
IDLE_SECONDS = 12 * 3600  # a session ends after this long unused
MAX_SECONDS = 30 * 86400  # and after this long in any case
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


class UserError(OreadError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str, salt: bytes | None = None, params: dict | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    params = params or _SCRYPT
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=128 * 2 ** 20, **params)
    return {"scheme": "scrypt", **params, "salt": _b64(salt), "hash": _b64(digest)}


def check_password(password: str, stored: dict) -> bool:
    params = {k: stored[k] for k in ("n", "r", "p")}
    again = hash_password(password, base64.b64decode(stored["salt"]), params)
    return hmac.compare_digest(again["hash"], stored["hash"])


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise UserError(f"Passwords need at least {MIN_PASSWORD} characters")
    if len(password) > 256:
        raise UserError("That password is longer than 256 characters")


class _JsonFile:
    """A small JSON file, private to Oread, reloaded when changed from the command line."""

    def __init__(self, path: Path, key: str) -> None:
        self.path, self.key = path, key
        self.items: dict = {}
        self._mtime = 0.0
        self.reload()

    def reload(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self.items, self._mtime = {}, 0.0
            return
        if mtime != self._mtime:
            self.items = json.loads(self.path.read_text()).get(self.key, {})
            self._mtime = mtime

    def write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        old = os.umask(0o077)
        try:
            tmp.write_text(json.dumps({self.key: self.items}, indent=2))
        finally:
            os.umask(old)
        tmp.chmod(0o600)
        tmp.replace(self.path)
        self._mtime = self.path.stat().st_mtime


class Users:
    def __init__(self, data_dir: Path, audit=None) -> None:
        self._lock = threading.Lock()
        self._users = _JsonFile(data_dir / "users.json", "users")
        self._code_file = data_dir / "setup-code.txt"
        self._sessions = _JsonFile(data_dir / "sessions.json", "sessions")
        self.audit = audit or (lambda **event: None)
        self._setup_code: str | None = None
        self._setup_failures = 0
        self._touched: dict[str, float] = {}

    # ---------- first run ----------

    def needs_setup(self) -> bool:
        with self._lock:
            self._users.reload()
            return not self._users.items

    def setup_code(self) -> str:
        """The one-time code: the same one across restarts until it's used."""
        code = None
        try:
            code = self._code_file.read_text().strip().upper() or None
        except OSError:
            pass
        if code is None:
            code = "-".join(secrets.token_hex(2).upper() for _ in range(3))   # like 3F9A-0B12-C7D4
            old = os.umask(0o077)
            try:
                self._code_file.write_text(code + "\n")
            except OSError as err:   # still works, from the log only
                logging.getLogger("oread.users").warning(
                    "Couldn't save the setup code to %s (%s). Oread can't write to its data "
                    "folder: check the folder belongs to the user Oread runs as (see the user "
                    "guide, Troubleshooting).", self._code_file, err.strerror or err)
            finally:
                os.umask(old)
        self._setup_code = _fingerprint(code)
        self._setup_failures = 0   # a restart allows five more tries
        return code

    def setup(self, code: str, name: str, password: str, client: str | None) -> dict:
        with self._lock:
            self._users.reload()
            if self._users.items:
                raise UserError("Oread is already set up; sign in instead", 409)
            if self._setup_code is None or self._setup_failures >= LOCK_AFTER:
                raise UserError("Too many wrong setup codes. Restart Oread "
                                "(docker compose restart oread) to try again.", 403)
            given = _fingerprint(code.strip().upper())
            if not hmac.compare_digest(given, self._setup_code):
                self._setup_failures += 1
                self.audit(action="setup refused", client=client, detail="wrong setup code")
                raise UserError("That setup code isn't right. On the server it's in "
                                "data/setup-code.txt, or the last line of: docker compose logs "
                                "oread | grep \"setup code\"", 403)
            self._new_user(name, password, "super")
            self._setup_code = None
            self._users.write()
            try:
                self._code_file.unlink()
            except OSError:
                pass
        self.audit(action="setup", who=name, client=client, detail="super user created")
        return self.public(name)

    # ---------- signing in ----------

    def sign_in(self, name: str, password: str, client: str | None) -> tuple[str, dict]:
        """A new session ID for the cookie, or UserError. Same message for any failure."""
        refused = UserError("Wrong username or password", 401)
        with self._lock:
            self._users.reload()
            key = self._find(name)
            user = self._users.items.get(key) if key else None
            if user is None:
                hash_password(password)   # take as long as a real check
                self.audit(action="sign-in refused", who=name, client=client, detail="no such user")
                raise refused
            if user.get("locked_until", 0) > time.time():
                minutes = int((user["locked_until"] - time.time()) // 60) + 1
                self.audit(action="sign-in refused", who=key, client=client, detail="locked")
                raise UserError(f"Too many wrong passwords. Try again in {minutes} minutes.", 429)
            if not check_password(password, user["password"]):
                user["failures"] = user.get("failures", 0) + 1
                detail = "wrong password"
                if user["failures"] >= LOCK_AFTER:
                    user["locked_until"] = time.time() + LOCK_SECONDS
                    user["failures"] = 0
                    detail = f"wrong password; locked for {LOCK_SECONDS // 60} minutes"
                self._users.write()
                self.audit(action="sign-in refused", who=key, client=client, detail=detail)
                raise refused
            user["failures"] = 0
            user.pop("locked_until", None)
            user["last_sign_in"] = _now()
            self._users.write()
            session = self._new_session(key)
        self.audit(action="sign-in", who=key, client=client)
        return session, self.public(key)

    def _new_session(self, name: str) -> str:
        session = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions.reload()
        self._expire_sessions(now)
        self._sessions.items[_fingerprint(session)] = {"user": name, "created": now, "used": now}
        self._sessions.write()
        return session

    def session_user(self, session: str | None) -> dict | None:
        """The signed-in user for a session cookie, or None."""
        if not session:
            return None
        fp = _fingerprint(session)
        with self._lock:
            self._sessions.reload()
            item = self._sessions.items.get(fp)
            now = time.time()
            if not item or now - item["used"] > IDLE_SECONDS or now - item["created"] > MAX_SECONDS:
                return None
            self._users.reload()
            if item["user"] not in self._users.items:
                return None
            if now - self._touched.get(fp, 0) > 60:   # note use at most once a minute
                item["used"] = now
                self._touched[fp] = now
                self._sessions.write()
            return self.public(item["user"])

    def sign_out(self, session: str | None) -> None:
        if not session:
            return
        with self._lock:
            self._sessions.reload()
            if self._sessions.items.pop(_fingerprint(session), None):
                self._sessions.write()

    def _expire_sessions(self, now: float) -> None:
        for fp, item in list(self._sessions.items.items()):
            if now - item["used"] > IDLE_SECONDS or now - item["created"] > MAX_SECONDS:
                del self._sessions.items[fp]

    def _end_sessions(self, name: str, keep: str | None = None) -> None:
        self._sessions.reload()
        keep_fp = _fingerprint(keep) if keep else None
        for fp, item in list(self._sessions.items.items()):
            if item["user"] == name and fp != keep_fp:
                del self._sessions.items[fp]
        self._sessions.write()

    # ---------- your own account ----------

    def change_own_password(self, name: str, current: str, new: str, session: str | None) -> None:
        check_new_password(new)
        with self._lock:
            self._users.reload()
            user = self._users.items.get(name)
            if user is None or not check_password(current, user["password"]):
                raise UserError("Your current password isn't right", 403)
            user["password"] = hash_password(new)
            self._users.write()
            self._end_sessions(name, keep=session)   # sign out everywhere else
        self.audit(action="password changed", who=name, detail="own password")

    # ---------- managing others (from the role down) ----------

    def list(self, actor: dict) -> list[dict]:
        with self._lock:
            self._users.reload()
            return [self.public(n) for n in sorted(self._users.items, key=str.lower)]

    def grantable(self, actor: dict) -> list[str]:
        if actor["role"] == "super":
            return list(ROLES)
        return [r for r in ROLES if RANK[r] < RANK[actor["role"]]]

    def create(self, actor: dict, name: str, password: str, role: str) -> dict:
        self._may_grant(actor, role)
        with self._lock:
            self._users.reload()
            self._new_user(name, password, role)
            self._users.write()
        self.audit(action="user created", who=actor["name"], target=name, detail=role)
        return self.public(name)

    def update(self, actor: dict, name: str, role: str | None, password: str | None) -> dict:
        with self._lock:
            self._users.reload()
            key = self._find(name)
            if key is None:
                raise UserError(f"No user named '{name}'", 404)
            user = self._users.items[key]
            self._may_manage(actor, key, user["role"])
            changes = []
            if role and role != user["role"]:
                self._may_grant(actor, role)
                if user["role"] == "super" and role != "super" and self._supers() == 1:
                    raise UserError("That's the last super user; make another one first", 409)
                user["role"] = role
                changes.append(f"role {role}")
            if password:
                check_new_password(password)
                user["password"] = hash_password(password)
                user["failures"] = 0
                user.pop("locked_until", None)
                changes.append("password reset")
            if changes:
                self._users.write()
                self._end_sessions(key)   # sign them in again with the new role or password
        if changes:
            self.audit(action="user changed", who=actor["name"], target=key, detail=", ".join(changes))
        return self.public(key)

    def delete(self, actor: dict, name: str) -> None:
        with self._lock:
            self._users.reload()
            key = self._find(name)
            if key is None:
                raise UserError(f"No user named '{name}'", 404)
            if key == actor["name"]:
                raise UserError("You can't delete your own account", 409)
            self._may_manage(actor, key, self._users.items[key]["role"])
            if self._users.items[key]["role"] == "super" and self._supers() == 1:
                raise UserError("That's the last super user", 409)
            del self._users.items[key]
            self._users.write()
            self._end_sessions(key)
        self.audit(action="user deleted", who=actor["name"], target=key)

    # ---------- helpers ----------

    def public(self, name: str) -> dict:
        user = self._users.items[name]
        locked = user.get("locked_until", 0) > time.time()
        return {"name": name, "role": user["role"], "created": user["created"],
                "last_sign_in": user.get("last_sign_in"), "locked": locked}

    def _find(self, name: str) -> str | None:
        """Usernames match without regard to case."""
        lowered = (name or "").strip().lower()
        return next((n for n in self._users.items if n.lower() == lowered), None)

    def _new_user(self, name: str, password: str, role: str) -> None:
        name = name.strip()
        if not _NAME.match(name):
            raise UserError("Usernames are 2-32 letters, digits, or . _ - (starting with a "
                            "letter or digit)")
        if role not in RANK:
            raise UserError(f"Roles are: {', '.join(ROLES)}")
        if self._find(name):
            raise UserError(f"A user named '{name}' already exists", 409)
        check_new_password(password)
        self._users.items[name] = {"role": role, "password": hash_password(password),
                                   "created": _now(), "last_sign_in": None, "failures": 0}

    def _supers(self) -> int:
        return sum(u["role"] == "super" for u in self._users.items.values())

    def _may_grant(self, actor: dict, role: str) -> None:
        if role not in RANK:
            raise UserError(f"Roles are: {', '.join(ROLES)}")
        if role not in self.grantable(actor):
            raise UserError(f"A {actor['role']} can't grant the {role} role", 403)

    def _may_manage(self, actor: dict, name: str, role: str) -> None:
        if name == actor["name"]:
            raise UserError("Change your own password on the Account page", 409)
        if actor["role"] != "super" and RANK[role] >= RANK[actor["role"]]:
            raise UserError(f"A {actor['role']} can't change a {role}", 403)


def main(argv: list[str]) -> None:
    from . import settings as settings_mod
    cfg = settings_mod.load()
    users = Users(cfg["paths"]["data"])
    usage = "usage: python -m oread.users reset <name> | list"
    if argv[:1] == ["list"] and len(argv) == 1:
        users._users.reload()
        for name, u in sorted(users._users.items.items()):
            print(f"{name:24} {u['role']:14} last sign-in {u.get('last_sign_in') or 'never'}")
    elif argv[:1] == ["reset"] and len(argv) == 2:
        users._users.reload()
        key = users._find(argv[1])
        if key is None:
            sys.exit(f"No user named '{argv[1]}'")
        password = getpass.getpass("New password: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
        try:
            check_new_password(password)
        except UserError as err:
            sys.exit(str(err))
        user = users._users.items[key]
        user["password"] = hash_password(password)
        user["failures"] = 0
        user.pop("locked_until", None)
        users._users.write()
        users._end_sessions(key)
        _audit_line(cfg["paths"]["logs"], action="password reset", who="server command line", target=key)
        print(f"Password for '{key}' reset; their sessions were signed out")
    else:
        sys.exit(usage)


def _audit_line(log_dir: Path, **event) -> None:
    from .audit import Audit
    Audit(log_dir).record(**event)


if __name__ == "__main__":
    main(sys.argv[1:])
