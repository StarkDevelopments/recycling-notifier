# Recycling Notifier

A daily recycling reminder for [South Gloucestershire](https://www.southglos.gov.uk/). A Python script runs once a day from cron (on a Raspberry Pi, in Docker), queries the council's waste API, and sends a [Pushover](https://pushover.net/) notification about collections planned for **the next day**. It stays quiet when there's nothing to say.

## What it notifies about

Works for **household** UPRNs (Refuse, Food, Recycling) and **trade/commercial** UPRNs (Trade Refuse, Trade Food, Trade Recycling) alike — set your UPRN in `.env` and it just works.

| Situation | Example |
|---|---|
| Collections scheduled for tomorrow | "Collections tomorrow (Monday 07 Sep): - Recycling (Monday every week)" |
| Collection due today but not confirmed collected | "Collections due today haven't been confirmed as collected: - Refuse: no completion recorded" |
| Collection in an unexpected state | "Collection states need attention: - Recycling: Closed Not Completed" |
| Nothing scheduled on your usual collection day (possible bank-holiday skip) | "No collections tomorrow (Monday 7th Sep), which is the usual collection day (Monday)." |
| Nothing scheduled on a non-usual day | Silent — that's expected, no ping |

A collection that is `In Progress` (crew actively collecting) is treated as normal and never warns. `Closed Completed with Exception` (common on trade rounds — collected, but with a note e.g. resident issue) also counts as a normal completion.

## How it works

- Queries the public South Gloucestershire waste API (`GetCollectionDetails`) for your property's UPRN — no auth needed.
- Compares collection dates against "today" in `Europe/London` (handles GMT/BST).
- Sends via Pushover (the notifier interface is pluggable if you want SMTP/ntfy later).
- Runs once and exits: host cron is the scheduler, the container is stateless.

The runtime is **Python 3.14 stdlib-only** (`urllib` + `zoneinfo`) — nothing is pip-installed into the image.

## Find your UPRN

A UPRN (Unique Property Reference Number) is a unique ID for every addressable property in Great Britain. The council API needs yours. Any of these works:

1. **[FindMyAddress](https://www.findmyaddress.co.uk/)** — free, official address/UPRN lookup (Ordnance Survey / GeoPlace data). Search by postcode or address and copy the UPRN.
2. **Council tax bill** — most councils print the UPRN on it (often near the top or on the remittance slip). Look for "UPRN" or "Property Ref".
3. **Doogal postcode lookup** — `https://www.doogal.co.uk/UPRN?postcode=YOUR+POSTCODE` lists every UPRN in a postcode with coordinates (addresses may be hidden behind a lookup, but the UPRN list is free).
4. **Your council's bin-day website** — many council bin lookups embed the UPRN in the page URL or network requests after you enter your address; the browser dev tools (Network tab) will show it being sent.

Once you have it, sanity-check against the live API:

```sh
curl -s "https://api.southglos.gov.uk/wastecomp/GetCollectionDetails?uprn=YOUR_UPRN"
```

You should get a JSON body with one record per service (e.g. Refuse, Food, Recycling). If `value` is empty, the UPRN is wrong or has no collection data.

> The example UPRN used in this repo's fixtures and `.env.example` is **`661911`** — South Gloucestershire Council's own Badminton Road offices in Yate. It's a public building, safe to use as demo data; replace it with your own.

## Setup

```sh
cp .env.example .env        # then fill in your UPRN and Pushover secrets
docker compose build        # or: docker build -t recycling-notifier:latest .
./run.sh                    # run once, right now (exits 0 = ran, 1 = failed)
```

Or without the helper script:

```sh
docker run --rm --env-file .env recycling-notifier:latest
```

### `.env`

| Variable | Required | Meaning |
|---|---|---|
| `UPRN` | yes | Your property's UPRN (see above) |
| `PUSHOVER_TOKEN` | yes | Your Pushover application token |
| `PUSHOVER_USER_KEY` | yes | Your Pushover user/group key |
| `USUAL_COLLECTION_DAY` | no | Normal collection weekday, default `Monday` — used for the "nothing on the usual day" dead-man's check |
| `LOG_LEVEL` | no | Python log level, default `INFO` |

Never commit `.env` — it's gitignored and holds your secrets. `.env.example` is the committed template.

### Pushover

1. Create a free account at [pushover.net](https://pushover.net/).
2. Create an application (Dashboard → Applications → Create a New Application) to get an **API token/Key**.
3. Your **user key** is on the dashboard after signing in.
4. Install the Pushover app on your phone to receive the pushes.

## Schedule with cron (Raspberry Pi)

The container runs once and exits, so host cron fires it daily:

```sh
crontab -e
# 2pm UK time (the app computes "today" itself in Europe/London,
# so only the firing time needs to be DST-correct — CRON_TZ handles that)
CRON_TZ=Europe/London
0 14 * * * docker run --rm --env-file /home/pi/recycling-notifier/.env recycling-notifier:latest >> /home/pi/recycling-notifier/cron.log 2>&1
```

## Tests

Tests mock HTTP (no network needed) and use a recorded API response as a fixture:

```sh
pip install -r requirements.txt   # dev only: pytest
pytest                            # or: python3 -m unittest discover -s tests -t .
```

## Project layout

- `app.py` — entry point: env config, "today" in UK time, fetch + send orchestration
- `report.py` — pure report-building logic (unit-tested in isolation, no I/O)
- `scraper.py` — API fetch + field parsing (the only module that knows the URL/field names)
- `notifiers/` — one module per channel behind a shared `send(title, body)` interface
- `Dockerfile` / `docker-compose.yml` / `run.sh` — container build and run
- `tests/` — stdlib `unittest` (also runs under pytest), fixtures in `tests/fixtures/` (household and trade responses, captured from the council's public offices)

## Gotchas

- Only the **date** part of `hso_nextcollection` is used — some services return a midnight time.
- Dates carry UTC offsets (BST/GMT); comparisons are done with timezone-aware datetimes.
- A quiet run (nothing to notify) exits 0 — that's success, not a failure. Network/API/notifier errors exit 1 so cron logs them.

## License

MIT — see [LICENSE](LICENSE).
