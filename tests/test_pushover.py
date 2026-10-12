"""Pushover channel tests. Mock HTTP; never hit the network."""

import io
import unittest
from unittest import mock

import urllib.parse

from notifiers.pushover import API_URL, PushoverNotifier


class PushoverNotifierTest(unittest.TestCase):
    def test_send_posts_form_encoded_payload(self):
        captured = {}

        def fake_urlopen(url, data=None):
            captured["url"] = url
            captured["data"] = urllib.parse.parse_qs(data.decode())
            return io.BytesIO(b"{}")

        with mock.patch(
            "notifiers.pushover.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            PushoverNotifier(token="t0k3n", user_key="u5er").send("Hi", "Body text")

        self.assertEqual(captured["url"], API_URL)
        self.assertEqual(captured["data"]["token"], ["t0k3n"])
        self.assertEqual(captured["data"]["user"], ["u5er"])
        self.assertEqual(captured["data"]["title"], ["Hi"])
        self.assertEqual(captured["data"]["message"], ["Body text"])
