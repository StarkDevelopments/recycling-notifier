"""Pluggable notifier interface and built-in channels.

A notifier is anything with `send(title: str, body: str) -> None`. Add new
channels (smtp, ntfy, ...) as sibling modules; wire them up in `app.py`.
"""

from .pushover import PushoverNotifier

__all__ = ["PushoverNotifier"]
