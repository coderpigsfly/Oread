"""The one kind of error Oread refuses a request with.

Each part of Oread names its own (StoreError, DeviceError, ...) so a message
says where it came from, but all of them are an OreadError: a message fit to
show a person, plus the web status code that goes with it. The API turns any
of them into that status and message in one place (api.py).
"""

from __future__ import annotations


class OreadError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class SettingsError(OreadError):
    """Something in settings.yaml, models.yaml or a device's choices doesn't fit.

    At startup it stops Oread with the message (see __main__.py); on a page it's
    shown like any other refusal, and nothing is changed."""
