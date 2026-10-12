"""Fetch and parse South Gloucestershire Council's waste collection API.

The endpoint is a Dataverse (Dynamics 365) OData feed with one record per
service. Household UPRNs return Refuse/Food/Recycling; trade (commercial) UPRNs
return Trade Refuse/Trade Food/Trade Recycling — often as two records per
service (a completed "Task" history record plus a future-scheduled one). This
module is the only place the URL and field mapping live, so API breakage is
contained here.
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

DEFAULT_API_URL = "https://api.southglos.gov.uk/wastecomp/GetCollectionDetails"


@dataclass(frozen=True)
class Collection:
    service: str | None
    address: str | None
    schedule_description: str | None
    state_name: str | None
    next_collection: datetime | None
    last_collection: datetime | None
    last_collection_completed: datetime | None


def fetch_collections(uprn: str | int, api_url: str = DEFAULT_API_URL, timeout: float = 10) -> list[Collection]:
    """Query the API for the given UPRN and parse every service record."""
    url = f"{api_url}?{urllib.parse.urlencode({'uprn': str(uprn)})}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return [_parse(record) for record in body.get("value", [])]


def _parse(record: dict) -> Collection:
    return Collection(
        service=record.get("hso_servicename"),
        address=record.get("hso_name"),
        schedule_description=record.get("hso_scheduledescription"),
        state_name=record.get("hso_statename"),
        next_collection=_aware_datetime(record.get("hso_nextcollection")),
        last_collection=_aware_datetime(record.get("hso_lastcollection")),
        last_collection_completed=_aware_datetime(record.get("hso_lastcollectioncompleted")),
    )


def _aware_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 (e.g. '2026-08-03T07:00:00+01:00') into an aware datetime.

    Offsets matter here: +01:00 is BST. Never fall back to naive comparisons.
    """
    if not value:
        return None
    return datetime.fromisoformat(value)
