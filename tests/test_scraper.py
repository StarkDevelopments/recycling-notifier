"""Parser tests. The fixture is a real captured API response (see
tests/fixtures/collections.json); the fetch test mocks HTTP only."""

import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import scraper

FIXTURE = Path(__file__).parent / "fixtures" / "collections.json"
TRADE_FIXTURE = Path(__file__).parent / "fixtures" / "trade_collections.json"


class FetchCollectionsTest(unittest.TestCase):
    def test_url_uses_uprn_query_param(self):
        captured = {}

        def fake_urlopen(url, timeout=None):
            captured["url"] = url
            captured["timeout"] = timeout
            return io.BytesIO(json.dumps({"value": []}).encode())

        with mock.patch.object(scraper.urllib.request, "urlopen", side_effect=fake_urlopen):
            scraper.fetch_collections("661911", api_url="https://example.invalid/x")

        self.assertIn("https://example.invalid/x?uprn=661911", captured["url"])
        self.assertEqual(captured["timeout"], 10)

    def test_fetches_and_parses_real_fixture(self):
        payload = FIXTURE.read_text()

        def fake_urlopen(url, timeout=None):
            return io.BytesIO(payload.encode())

        with mock.patch.object(scraper.urllib.request, "urlopen", side_effect=fake_urlopen):
            collections = scraper.fetch_collections("661911")

        self.assertEqual([c.service for c in collections], ["Refuse", "Food", "Recycling"])


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.records = json.loads(FIXTURE.read_text())["value"]
        self.refuse = scraper._parse(self.records[0])
        self.food = scraper._parse(self.records[1])

    def test_field_mapping(self):
        self.assertEqual(self.refuse.service, "Refuse")
        self.assertEqual(self.refuse.address, "BADMINTON ROAD OFFICES, BADMINTON ROAD, YATE, BRISTOL, BS37 5AF")
        self.assertEqual(self.refuse.schedule_description, "Monday every 3rd week")
        self.assertEqual(self.refuse.state_name, "Closed Completed")

    def test_dates_are_aware(self):
        self.assertEqual(
            self.food.next_collection,
            datetime.fromisoformat("2026-08-03T07:00:00+01:00"),
        )
        self.assertIsNotNone(self.food.next_collection.tzinfo)

    def test_refuse_next_collection_uses_only_date_part(self):
        # Observed quirk: Refuse comes back with T00:00:00+01:00.
        self.assertEqual(self.refuse.next_collection.date(), datetime(2026, 8, 17).date())

    def test_last_collection_completed_present(self):
        self.assertEqual(self.food.last_collection_completed.date(), datetime(2026, 7, 27).date())

    def test_missing_values_become_none(self):
        parsed = scraper._parse({"hso_servicename": "Food"})
        self.assertIsNone(parsed.next_collection)
        self.assertIsNone(parsed.last_collection)
        self.assertIsNone(parsed.last_collection_completed)


class TradeParseTest(unittest.TestCase):
    """Trade UPRNs return two records per service: a completed "Task" history
    record and a future-scheduled one (see trade_collections.json, captured
    from the council's own offices)."""

    def setUp(self):
        self.records = json.loads(TRADE_FIXTURE.read_text())["value"]
        self.task = scraper._parse(self.records[0])  # Trade Food, completed task
        self.future = scraper._parse(self.records[1])  # Trade Food, next scheduled

    def test_two_records_per_service(self):
        services = [r["hso_servicename"] for r in self.records]
        self.assertEqual(services.count("Trade Food"), 2)
        self.assertEqual(services.count("Trade Refuse"), 2)
        self.assertEqual(services.count("Trade Recycling"), 2)

    def test_task_record_has_history_but_no_next(self):
        self.assertEqual(self.task.service, "Trade Food")
        self.assertIsNone(self.task.next_collection)
        self.assertIsNotNone(self.task.last_collection)
        self.assertEqual(self.task.state_name, "Closed Completed")

    def test_future_record_has_next_but_no_state(self):
        self.assertEqual(self.future.service, "Trade Food")
        self.assertIsNotNone(self.future.next_collection)
        self.assertIsNone(self.future.last_collection)
        self.assertIsNone(self.future.state_name)
        self.assertEqual(self.future.schedule_description, "Tuesday every other week")

    def test_task_record_schedule_description_is_null(self):
        # Observed trade quirk: history records carry no schedule description.
        self.assertIsNone(self.task.schedule_description)

    def test_trade_exception_state_parses(self):
        refuse_task = scraper._parse(self.records[2])
        self.assertEqual(refuse_task.service, "Trade Refuse")
        self.assertEqual(refuse_task.state_name, "Closed Completed with Exception")
