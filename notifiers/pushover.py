"""Pushover notification channel.

Docs: https://pushover.net/api  (POST /1/messages.json, form-encoded).
Requires an app token and the user key; both must come from environment
variables, never from the repo.
"""

import urllib.parse
import urllib.request

API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier:
    def __init__(self, token: str, user_key: str, api_url: str = API_URL):
        self.token = token
        self.user_key = user_key
        self.api_url = api_url

    def send(self, title: str, body: str) -> None:
        data = urllib.parse.urlencode(
            {
                "token": self.token,
                "user": self.user_key,
                "title": title,
                "message": body,
                "ttl": "86400",
            }
        ).encode("utf-8")
        with urllib.request.urlopen(self.api_url, data=data) as resp:
            resp.read()
