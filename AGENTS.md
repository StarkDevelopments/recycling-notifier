# AGENTS.md

Greenfield repo — the MVP below is implemented and working; extend it in place.

## What this project is

A daily recycling reminder for South Gloucestershire. A Python script runs once a day at **2pm UK time** from a cron job on a Raspberry Pi inside a Docker container, queries the council's waste API, and sends a Pushover notification about collections planned for **the next day**, plus flags any collection that was scheduled today but appears missed or is in an unexpected state. It only notifies when there is something to say: collections scheduled for tomorrow, a possibly-missed or attention-needing collection, or a day with nothing scheduled that is the user's usual collection weekday (`USUAL_COLLECTION_DAY`, default `Monday`) — that "no collections on usual date" note keeps a possible skip/move of the usual day's collection (e.g. bank holiday) visible rather than silently handled. On a **non-usual day** with nothing scheduled it stays quiet, since that outcome is expected (e.g. running on a Tuesday when collections are Mondays-only). A problem report talks about the problem only — no "no collections tomorrow" padding — and a collection whose state is `In Progress` (crew actively collecting) is not treated as a warning, so an early-afternoon run on collection day doesn't false-alarm. Works for **household UPRNs** (Refuse/Food/Recycling) and **trade UPRNs** (Trade Refuse/Trade Food/Trade Recycling) alike — nothing in the code special-cases service names.

## Flow

`hso_nextcollection` is known days/weeks ahead, so run time only affects the missed-check, never the "what's due" data.

- **Day before a scheduled collection** (e.g. Sunday, Monday bins) → `Collections tomorrow (Monday 07 Sep): - <service> (<cadence>), …`, title "Recycling collections tomorrow".
- **Collection day, collection in progress or completed** (state `In Progress`, `Closed Completed`, or any `Closed Completed …` variant such as `Closed Completed with Exception`) → nothing; silent, exit 0. `In Progress` is normal at 2pm and never warns; `Closed Completed with Exception` (common on trade rounds) counts as a normal completion.
- **Collection day, today's collection not confirmed** (no completion recorded AND state other than `In Progress`, or no state at all) → problem-only report: `Collections due today haven't been confirmed as collected:` then `- <service>: <state or "no completion recorded">`, title "Recycling: action needed". No "no collections tomorrow" padding. This is the proxy for a genuine miss — the real "missed" state values are still unvalidated against a real event.
- **Unexpected state, collection not due today** → `Collection states need attention:` then `- <service>: <state>`, title "Recycling: check status".
- **Usual day, nothing scheduled** (holiday skip/move) → dead-man's check so the shift is visible: `No collections tomorrow (Monday 7th Sep), which is the usual collection day (Monday).`, title "No collections on usual date".
- **Day after the shift** (collection now due tomorrow, e.g. Tuesday) → normal `Collections tomorrow (Tuesday …): …` — `hso_lastcollection` stays the previous completed week, so there's no missed false-alarm.
- **Any non-usual day with nothing scheduled** → silent, exit 0 (expected).
- **Priority**: if problems exist the report is about the problem only; "collections tomorrow"/"no collections" wording is never mixed in.

## Schedule source (verified against the live API)

```
GET https://api.southglos.gov.uk/wastecomp/GetCollectionDetails?uprn={UPRN}
```

- South Gloucestershire Council, a Dataverse (Dynamics 365) OData endpoint. No auth. JSON body: `{ "@odata.context": ..., "value": [ ... ] }` — one record per service. Household UPRNs: `hso_servicename` is `Refuse`, `Food`, `Recycling`. Trade (commercial) UPRNs: `Trade Refuse`, `Trade Food`, `Trade Recycling`, typically **two records per service** (a completed "Task" history record plus a future-scheduled one).
- No other services to integrate; this is the only API. Example UPRN: `661911` (South Gloucestershire Council's own Badminton Road offices — a public building, used for the fixtures).
- Manual check: `curl -s "https://api.southglos.gov.uk/wastecomp/GetCollectionDetails?uprn=661911"`

Key fields per record:

- `hso_nextcollection` — scheduled date of the next collection (ISO 8601 with tz offset, e.g. `2026-08-03T07:00:00+01:00`). Drives the "collections tomorrow" message.
- `hso_lastcollection` — scheduled date of the most recent collection; `hso_lastcollectioncompleted` — timestamp it was actually completed. On a late-day run, today's scheduled collection with no completed timestamp ⇒ likely missed; at 2pm it's usually just the crew still working.
- `hso_statename` — lifecycle status of the last collection; observed `"Closed Completed"`, `"In Progress"` (crew actively collecting — treat as normal, never a warning), and on trade: `"Closed Completed with Exception"` (collected, with a note — treat as completed, don't warn) and `"Closed Not Completed"` (genuinely unresolved — flag). Treat any other value as non-success (flag), don't assume success. States beginning `Closed Completed` count as completed (`_is_completed_state` in `report.py`).
- `hso_scheduledescription` — human cadence (`"Monday every week"`, `"Monday every 3rd week"`); use for context in notifications. **Null on trade history records** — render the service name without a `(...)` suffix rather than "(None)".
- `hso_name` — display address; `hso_uprn` echoes the UPRN.

Observed quirks:

- `hso_nextcollection` for Refuse came back as `...T00:00:00+01:00` while Food/Recycling had a real time set — use only the date part, never time-of-day. Trade shows the same midnight-time quirk.
- Dates carry offsets (`+01:00` = BST). Parse aware datetimes; don't compare naive dates across a DST boundary.
- Trade UPRNs return two records per service: a "Task" history record (`hso_statesource: "Task"`, has `hso_lastcollection` + state, `hso_nextcollection` null, schedule description null) and a future-scheduled record (has `hso_nextcollection` + schedule description, state null). Only the future record can appear in "collections tomorrow", so no dedup is needed.
- Household record: `hso_statename` was observed only in the healthy/active states; the "missed/warning" values still need to be validated against a real event before shipping.
- Trade fixture (`tests/fixtures/trade_collections.json`) is a real captured response from UPRN `661911` (council offices — public building, safe to commit).

## Stack (decided)

- Python 3.14, stdlib-only runtime (`urllib` + `zoneinfo`) — no `requests`, no boto3; `requirements.txt` is dev-only (pytest)
- Runs in a **Docker container on the Raspberry Pi (arm64)**, launched by host cron once a day
- Notification channel: **Pushover** (HTTP push); the notifier interface is pluggable so SMTP/ntfy can be added without rework

## Layout

- `app.py` — entry point + orchestration: reads env config, computes "today" in UK time, fetches collections, sends via the notifier. `main()` is the container entry point (exit 0 = ran, 1 = failed, so cron sees errors). All pure report logic lives in `report.py`.
- `report.py` — pure report-building logic (`build_report`, weekday parsing): collections + a date in, `Report | None` out. No I/O and no env access, so it's unit-tested in isolation.
- `scraper.py` — fetch + parse the API. Isolate URL + field mapping here; keep breakage in one module.
- `notifiers/` — one module per channel behind a shared `send(title, body)` interface; `pushover.py` is the only channel so far.
- `Dockerfile` — arm64 image (base `python:3.14-slim-bookworm`); non-root user; tzdata installed for `Europe/London`.
- `docker-compose.yml` — build + run once with config/secrets from `.env`.
- `run.sh` — helper: build-check + one-shot container run with `--env-file .env` (same command cron fires).
- `.env.example` — template for `.env`; copy, fill in secrets, never commit `.env`.
- `README.md` — public-facing docs: what it does, how to find your UPRN, setup, cron, tests.
- `LICENSE` — MIT.
- `tests/` — stdlib `unittest` (also runs under pytest). Fixtures: real captured API responses in `tests/fixtures/collections.json` (household shape) and `tests/fixtures/trade_collections.json` (trade shape) — both scrubbed to the council offices' public address/UPRN (`661911`).

## Commands

```sh
cp .env.example .env        # then fill in Pushover secrets (and adjust UPRN/usual day if needed)
docker compose build        # or: docker build -t recycling-notifier:latest .
docker compose run --rm recycling-notifier   # run once, right now
docker run --rm --env-file .env recycling-notifier:latest
pytest                      # all tests (also: python3 -m unittest discover -s tests -t .)
```

## Cron on the Raspberry Pi

The container is stateless and exits after each run, so host cron is the scheduler (nothing runs in the background). On the Pi:

```sh
crontab -e
# CRON_TZ keeps the 14:00 firing DST-correct (GMT/BST) regardless of host
# timezone; the app also computes "today" itself in Europe/London.
# --rm leaves no containers behind, output goes to a log.
CRON_TZ=Europe/London
0 14 * * * docker run --rm --env-file /home/pi/recycling-notifier/.env recycling-notifier:latest >> /home/pi/recycling-notifier/cron.log 2>&1
```

## Gotchas

- "2pm UK time" means `Europe/London` (GMT/BST, DST changes twice a year). The app computes "today" itself via `_today()` in `app.py` using `zoneinfo.Europe/London`, so the container/host clock only needs to fire cron at the right wall-clock moment. Never hardcode a UTC offset. Because the day's only run is at 2pm, the missed-check never sees an "end of day" snapshot: it fires only on a visible sign of trouble (a non-`In Progress`/non-`Closed Completed` state, or a due-today record with no state and no completion at all), never on `In Progress` alone.
- The app reports **tomorrow's** collections; "next day" = run date + 1, compared in UK local time. Missed-detection: a collection scheduled today (`hso_lastcollection` date == today) that isn't confirmed completed (no completion timestamp, or a state not beginning `Closed Completed`) and isn't `In Progress` ⇒ probable miss. Attention states: anything other than `In Progress` or a `Closed Completed…` state on a collection not due today. `"In Progress"` is the crew actively collecting, so it never warns.
- Exit codes: a quiet run (nothing to notify) still exits 0 — that's a successful run. Only genuine failures (network/API/notifier/parse errors, missing env vars) exit 1, so cron logs them.
- Env vars (`UPRN`, `USUAL_COLLECTION_DAY`, `PUSHOVER_TOKEN`, `PUSHOVER_USER_KEY`, `LOG_LEVEL`) are read at each run from `.env` via `--env-file` / compose `env_file`. Pushover secrets live only in `.env`, never in the repo or image.
- The runtime is **stdlib-only** — keep it that way; nothing is pip-installed into the image.
- Scraper/notifier tests must mock HTTP (sites are external; don't hit the network in CI). Record a real API response as a test fixture.
