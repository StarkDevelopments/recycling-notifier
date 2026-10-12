"""Report-building and entry-point tests. Dates are compared in UK time; use
aware datetimes with a +01:00 offset as the API returns in BST."""

import os
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import app
from report import build_report
from scraper import Collection

TODAY = date(2026, 8, 3)  # Monday
TOMORROW = TODAY + timedelta(days=1)
BST = datetime.fromisoformat


def collection(service="Food", next_date=None, last_date=None, completed=None, state="Closed Completed", schedule="Monday every week"):
    def at(d):
        return BST(f"{d}T07:00:00+01:00") if d else None

    return Collection(
        service=service,
        address="BADMINTON ROAD OFFICES, BADMINTON ROAD, YATE, BRISTOL, BS37 5AF",
        schedule_description=schedule,
        state_name=state,
        next_collection=at(next_date),
        last_collection=at(last_date),
        last_collection_completed=at(completed) if completed else None,
    )


class BuildReportTest(unittest.TestCase):
    def test_upcoming_collection_is_reported(self):
        c = collection("Food", next_date=TODAY + timedelta(days=1), last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)))
        report = build_report([c], TODAY)
        self.assertIn("Food", report.body)
        self.assertIn(f"Collections tomorrow ({TOMORROW.strftime('%A %d %b')})", report.body)
        self.assertIn("Recycling collections tomorrow", report.title)

    def test_no_collections_tomorrow_stays_quiet_off_usual_day(self):
        # tomorrow (Tue) is not the usual day (Mon) and nothing is scheduled:
        # this is expected, so no notification should be produced.
        c = collection("Food", next_date=TODAY + timedelta(days=8), last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)))
        report = build_report([c], TODAY)
        self.assertIsNone(report)

    def test_no_collections_on_usual_day_is_flagged(self):
        # tomorrow (Tue) == usual_day (Tuesday); nothing scheduled.
        c = collection("Food", next_date=TODAY + timedelta(days=8), last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)))
        report = build_report([c], TODAY, usual_day=1)
        self.assertEqual(report.title, "No collections on usual date")
        self.assertIn("Tuesday", report.body)
        self.assertIn("usual", report.body.lower())

    def test_no_collections_off_usual_day_is_generic(self):
        c = collection("Food", next_date=TODAY + timedelta(days=8), last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)))
        report = build_report([c], TODAY, usual_day=0)  # Monday; tomorrow is Tuesday
        self.assertIsNone(report)

    def test_missed_collection_notifies_even_off_usual_day(self):
        # Nothing tomorrow and not the usual day, but today's collection was
        # missed: must still notify.
        c = collection("Food", next_date=TODAY + timedelta(days=8), last_date=TODAY, completed=None)
        report = build_report([c], TODAY)
        self.assertIsNotNone(report)
        self.assertIn("haven't been confirmed as collected", report.body)
        self.assertIn("- Food: no completion recorded", report.body)
        self.assertNotIn("No collections tomorrow", report.body)
        self.assertEqual(report.title, "Recycling: action needed")

    def test_usual_day_with_collections_is_normal(self):
        c = collection("Food", next_date=TODAY + timedelta(days=1), last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)))
        report = build_report([c], TODAY, usual_day=1)  # tomorrow IS Tuesday and has collections
        self.assertEqual(report.title, "Recycling collections tomorrow")
        self.assertIn("Collections tomorrow", report.body)

    def test_healthy_todays_collection_is_not_missed(self):
        c = collection("Food", next_date=TOMORROW, last_date=TODAY, completed=TODAY)
        report = build_report([c], TODAY)
        self.assertIsNotNone(report)
        self.assertNotIn("missed", report.body.lower())

    def test_missing_completion_timestamp_flags_missed(self):
        c = collection("Food", last_date=TODAY, completed=None, state="Closed Completed")
        report = build_report([c], TODAY)
        self.assertIn("haven't been confirmed as collected", report.body)
        self.assertIn("- Food: no completion recorded", report.body)
        self.assertEqual(report.title, "Recycling: action needed")

    def test_non_healthy_state_flags_missed(self):
        c = collection("Food", last_date=TODAY, completed=None, state="Some Other State")
        report = build_report([c], TODAY)
        self.assertIn("haven't been confirmed as collected", report.body)
        self.assertIn("- Food: Some Other State", report.body)
        self.assertNotIn("No collections tomorrow", report.body)
        self.assertEqual(report.title, "Recycling: action needed")

    def test_problems_override_collections_tomorrow_text(self):
        # Missed today AND a collection due tomorrow: the report talks about
        # the problem only, never the (obvious) tomorrow line.
        c = collection("Food", next_date=TOMORROW, last_date=TODAY, completed=None)
        report = build_report([c], TODAY)
        self.assertEqual(report.title, "Recycling: action needed")
        self.assertNotIn("Collections tomorrow", report.body)
        self.assertNotIn("No collections tomorrow", report.body)

    def test_in_progress_state_is_quiet(self):
        # 2pm on collection day: crew is still collecting, nothing scheduled
        # tomorrow, tomorrow isn't the usual day => nothing to say.
        c = collection("Food", next_date=TODAY + timedelta(days=8), last_date=TODAY, completed=None, state="In Progress")
        report = build_report([c], TODAY)
        self.assertIsNone(report)

    def test_in_progress_state_never_reported_as_missed(self):
        c = collection("Food", last_date=TODAY, completed=None, state="In Progress")
        report = build_report([c], TODAY, usual_day=1)
        self.assertIsNotNone(report)
        self.assertIn("No collections tomorrow", report.body)
        self.assertNotIn("Food", report.body)

    def test_non_healthy_state_on_old_collection_flags_attention(self):
        c = collection("Food", last_date=TODAY - timedelta(days=7), completed=(TODAY - timedelta(days=7)), state="Delayed")
        report = build_report([c], TODAY)
        self.assertIn("Collection states need attention", report.body)
        self.assertEqual(report.title, "Recycling: check status")

    def test_refuse_three_weekly_schedule_handled(self):
        refuse = collection("Refuse", next_date=TODAY + timedelta(days=1), last_date=TODAY - timedelta(days=21), completed=(TODAY - timedelta(days=21)))
        refuse = Collection(
            service="Refuse",
            address="BADMINTON ROAD OFFICES, BADMINTON ROAD, YATE, BRISTOL, BS37 5AF",
            schedule_description="Monday every 3rd week",
            state_name="Closed Completed",
            next_collection=BST(f"{TODAY + timedelta(days=1)}T00:00:00+01:00"),
            last_collection=BST(f"{TODAY - timedelta(days=21)}T07:00:00+01:00"),
            last_collection_completed=BST(f"{TODAY - timedelta(days=21)}T09:13:50+01:00"),
        )
        report = build_report([refuse], TODAY)
        self.assertIn("Refuse", report.body)


class TradeReportTest(unittest.TestCase):
    """Trade UPRNs: two records per service, null schedule descriptions on
    history records, and states like "Closed Completed with Exception"."""

    def test_trade_collection_tomorrow_is_reported(self):
        future = collection(
            "Trade Food",
            next_date=TOMORROW,
            state=None,
            schedule="Tuesday every other week",
        )
        report = build_report([future], TODAY)
        self.assertIn("Trade Food (Tuesday every other week)", report.body)

    def test_null_schedule_description_omitted_not_none(self):
        # Trade history records carry a null schedule description; the body
        # must not render it as "(None)".
        future = collection("Trade Refuse", next_date=TOMORROW, state=None, schedule=None)
        report = build_report([future], TODAY)
        self.assertIn("- Trade Refuse", report.body)
        self.assertNotIn("None", report.body)

    def test_closed_completed_with_exception_is_quiet(self):
        # Routine on trade rounds (e.g. resident issue noted but collected):
        # completed, so it must not raise a daily "needs attention" ping.
        task = collection(
            "Trade Refuse",
            next_date=None,
            last_date=TODAY - timedelta(days=7),
            completed=TODAY - timedelta(days=7),
            state="Closed Completed with Exception",
            schedule=None,
        )
        report = build_report([task], TODAY)
        self.assertIsNone(report)

    def test_closed_completed_with_exception_counts_as_collected(self):
        # Due today, completion timestamp present, state has the exception
        # suffix: treated as collected, no action-needed report.
        task = collection(
            "Trade Refuse",
            next_date=TODAY + timedelta(days=8),
            last_date=TODAY,
            completed=TODAY,
            state="Closed Completed with Exception",
            schedule=None,
        )
        report = build_report([task], TODAY)
        self.assertIsNone(report)

    def test_closed_not_completed_flags_attention(self):
        # Genuinely unresolved trade state (e.g. "misuse of recycling bags"):
        # still flagged, like any other non-completed state.
        task = collection(
            "Trade Recycling",
            next_date=TODAY + timedelta(days=7),
            last_date=TODAY - timedelta(days=7),
            completed=TODAY - timedelta(days=7),
            state="Closed Not Completed",
            schedule=None,
        )
        report = build_report([task], TODAY)
        self.assertIn("Collection states need attention", report.body)
        self.assertIn("- Trade Recycling: Closed Not Completed", report.body)

    def test_trade_pending_today_reports_state(self):
        # Due today with a completion timestamp but "Closed Not Completed":
        # the proxy for a genuine miss.
        task = collection(
            "Trade Recycling",
            next_date=TODAY + timedelta(days=7),
            last_date=TODAY,
            completed=TODAY,
            state="Closed Not Completed",
            schedule=None,
        )
        report = build_report([task], TODAY)
        self.assertEqual(report.title, "Recycling: action needed")
        self.assertIn("- Trade Recycling: Closed Not Completed", report.body)

    def test_trade_task_and_future_records_together(self):
        # The real shape from the API: history record + future record for the
        # same service. Tomorrow's collection is reported once, from the
        # future record; the quiet history record adds nothing.
        task = collection(
            "Trade Food",
            next_date=None,
            last_date=TODAY - timedelta(days=7),
            completed=TODAY - timedelta(days=7),
            state="Closed Completed",
            schedule=None,
        )
        future = collection(
            "Trade Food",
            next_date=TOMORROW,
            state=None,
            schedule="Tuesday every other week",
        )
        report = build_report([task, future], TODAY)
        self.assertEqual(report.title, "Recycling collections tomorrow")
        self.assertEqual(report.body.count("Trade Food"), 1)
        self.assertIn("Trade Food (Tuesday every other week)", report.body)


class ParseWeekdayTest(unittest.TestCase):
    def test_case_insensitive(self):
        from report import parse_weekday

        self.assertEqual(parse_weekday("monday"), 0)
        self.assertEqual(parse_weekday("  Tuesday "), 1)
        self.assertEqual(parse_weekday("SUNDAY"), 6)

    def test_unknown_weekday_raises(self):
        from report import parse_weekday

        with self.assertRaises(ValueError):
            parse_weekday("Funday")


class RunTest(unittest.TestCase):
    """run() — fetch + report orchestration (does not send)."""

    def test_quiet_run_off_usual_day_returns_none(self):
        # Runs Monday, reports Tuesday; nothing scheduled, Tuesday isn't the
        # usual day (Monday) => expected quiet, so nothing to report.
        quiet = collection(
            "Food",
            next_date=TODAY + timedelta(days=8),
            last_date=TODAY - timedelta(days=7),
            completed=(TODAY - timedelta(days=7)),
        )
        with (
            mock.patch.object(app, "_today", return_value=TODAY),
            mock.patch.object(app, "fetch_collections", return_value=[quiet]),
            mock.patch.dict(os.environ, {"UPRN": "661911"}, clear=False),
        ):
            result = app.run()
        self.assertIsNone(result)

    def test_upcoming_collections_returns_report(self):
        c = collection(
            "Food",
            next_date=TOMORROW,
            last_date=TODAY - timedelta(days=7),
            completed=(TODAY - timedelta(days=7)),
        )
        with (
            mock.patch.object(app, "_today", return_value=TODAY),
            mock.patch.object(app, "fetch_collections", return_value=[c]),
            mock.patch.dict(os.environ, {"UPRN": "661911"}, clear=False),
        ):
            result = app.run()
        self.assertIsNotNone(result)
        self.assertIn("Collections tomorrow", result.body)

    def test_no_collections_on_usual_day_returns_report(self):
        # Runs Sunday, reports Monday (usual day); nothing scheduled => report.
        quiet = collection(
            "Food",
            next_date=TODAY + timedelta(days=8),
            last_date=TODAY - timedelta(days=7),
            completed=(TODAY - timedelta(days=7)),
        )
        with (
            mock.patch.object(app, "_today", return_value=TODAY - timedelta(days=1)),
            mock.patch.object(app, "fetch_collections", return_value=[quiet]),
            mock.patch.dict(os.environ, {"UPRN": "661911"}, clear=False),
        ):
            result = app.run()
        self.assertIsNotNone(result)
        self.assertIn("No collections tomorrow (Monday 3rd Aug), which is the usual collection day (Monday).", result.body)
        self.assertIn("usual", result.body.lower())


class MainTest(unittest.TestCase):
    """Container entry point: exit 0 on a quiet run, exit 1 on failure."""

    def test_quiet_run_exits_zero(self):
        quiet = collection(
            "Food",
            next_date=TODAY + timedelta(days=8),
            last_date=TODAY - timedelta(days=7),
            completed=(TODAY - timedelta(days=7)),
        )
        with (
            mock.patch.object(app, "_today", return_value=TODAY),
            mock.patch.object(app, "fetch_collections", return_value=[quiet]),
            mock.patch.object(app, "PushoverNotifier") as notifier,
            mock.patch.dict(os.environ, {"UPRN": "661911"}, clear=False),
        ):
            app.main()
        notifier.assert_not_called()

    def test_upcoming_collections_send_and_exit_zero(self):
        c = collection(
            "Food",
            next_date=TOMORROW,
            last_date=TODAY - timedelta(days=7),
            completed=(TODAY - timedelta(days=7)),
        )
        with (
            mock.patch.object(app, "_today", return_value=TODAY),
            mock.patch.object(app, "fetch_collections", return_value=[c]),
            mock.patch.object(app, "PushoverNotifier") as notifier,
            mock.patch.dict(
                os.environ,
                {"UPRN": "661911", "PUSHOVER_TOKEN": "t", "PUSHOVER_USER_KEY": "u"},
                clear=False,
            ),
        ):
            app.main()
        notifier.assert_called_once()
        notifier.return_value.send.assert_called_once()
        sent_title = notifier.return_value.send.call_args.args[0]
        self.assertEqual(sent_title, "Recycling Notifier")

    def test_failure_exits_nonzero(self):
        with (
            mock.patch.object(app, "fetch_collections", side_effect=RuntimeError("boom")),
            mock.patch.dict(os.environ, {"UPRN": "661911"}, clear=False),
        ):
            with self.assertRaises(SystemExit) as ctx:
                app.main()
        self.assertEqual(ctx.exception.code, 1)
