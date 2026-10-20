"""Who may connect to the listening ports (one Wyoming port per device).

The Wyoming protocol can't send a token, so the listening ports are
protected by a list of permitted clients instead: single addresses
(192.168.1.50) or whole ranges (192.168.1.0/24). With an empty list only the
local network may connect (private, loopback and Tailscale addresses), never
an address from the internet. The API port needs a sign-in or a token instead.

The list starts from settings.yaml (server.allowed_clients); once changed
on the Connections page it is kept in data/access.yaml, which then takes over.
Recently refused connections are remembered, so you can see who knocked.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .errors import OreadError

_LOG = logging.getLogger("oread.access")

# Used while the list is empty: home networks, this machine, and Tailscale's range.
LOCAL = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
    "100.64.0.0/10", "::1/128", "fc00::/7", "fe80::/10")]


class AccessError(OreadError):
    pass


def parse(entries: list[str]) -> list:
    networks = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError as err:
            raise AccessError(f"'{entry}' isn't an address or range (like 192.168.1.50 "
                              "or 192.168.1.0/24)") from err
    return networks


class Access:
    def __init__(self, seed: list[str], path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        if path.exists():
            entries = (yaml.safe_load(path.read_text()) or {}).get("allowed_clients") or []
            self.source = "data/access.yaml (managed on the Connections page)"
        else:
            entries = seed or []
            self.source = "settings.yaml"
        self.entries = [str(e) for e in entries]
        self.networks = parse(self.entries)
        self.refused: deque = deque(maxlen=20)
        self._last_log: dict[str, float] = {}
        if not self.networks:
            _LOG.warning("No permitted clients set: listening ports accept any address on the local "
                         "network (none from the internet); list your clients on the Connections page")

    def allowed(self, address: str | None) -> bool:
        try:
            ip = ipaddress.ip_address(address or "")
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip in net for net in (self.networks or LOCAL))

    def note_refused(self, address: str | None, device: str) -> None:
        when = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.refused.appendleft({"address": address, "device": device, "time": when})
        now = time.monotonic()
        if now - self._last_log.get(address or "", 0) > 60:  # log each address at most once a minute
            self._last_log[address or ""] = now
            _LOG.warning("Refused %s on device %s: not a permitted address", address, device)

    def view(self) -> dict:
        return {"allowed_clients": self.entries, "source": self.source,
                "local_network_only": not self.networks, "recently_refused": list(self.refused)}

    def replace(self, entries: list[str]) -> dict:
        networks = parse(entries)
        with self._lock:
            self.entries = [str(e).strip() for e in entries]
            self.networks = networks
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("# Addresses permitted on the listening ports, managed on the Connections page.\n"
                           "# Empty list = any address on the local network, none from the internet.\n"
                           "# Delete this file to go back to settings.yaml.\n"
                           + yaml.safe_dump({"allowed_clients": self.entries}))
            tmp.replace(self.path)
            self.source = "data/access.yaml (managed on the Connections page)"
        return self.view()
