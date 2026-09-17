"""Keka's public careers API, which Indian employers publish bands on.

Keka is an Indian HR platform, and its career sites are where this project's
premise gets tested from the other side.  India requires no range on a posting,
so the expectation was silence.  It is not silence: employers on Keka publish
real INR bands with no law compelling them, and until now we could not see one.

The endpoint is unauthenticated JSON, and it is reachable at exactly the path
the platform's own robots.txt permits.  Keka serves `Disallow: /` with
`Allow: /careers`, and the API answers only under that prefix -- the bare
`/api/organization/departments` is a 404, while `/careers/api/...` is a 200.
There is nothing here to weaken and no grey area to argue about.

One field decides whether this adapter is honest.  `salaryPeriod` is an enum,
and its zero value is "Not Available" -- an employer who published a band and
declined to say what period it covers.  Roughly half the published bands use
it.  Reading it as a year is how you get a number that looks authoritative and
is not: `INR 8,00,000 - 15,00,000` almost certainly is annual, and the posting
still does not say so.  `_PERIOD` therefore has no entry for 0, and the pay
dict carries `interval: None` rather than a guess.  `server.py` groups by
interval and refuses to merge across one, so an unstated interval stays out of
the annual figure instead of quietly joining it.

For the same reason this reads the numeric `minimum`/`maximum`/`salaryPeriod`
and never `salaryRangeFormat`.  That string is pre-rendered for display in
Indian digit grouping -- `INR 15,00,000.00 - 25,00,000.00` is 1.5 million, not
fifteen -- and `money.parse` does read it correctly.  But the string carries no
period at all, so parsing it throws away the one field that stops us inventing
one.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterator

import httpx

from . import __version__

BASE = "https://{tenant}.keka.com/careers/api/jobs/{portal}/active"

# The careers app sends the literal string "default" when a site has no named
# portal, which is the common case: `portalName ? portalName : "default"`.
DEFAULT_PORTAL = "default"

TIMEOUT = 30
MIN_INTERVAL = 0.25
USER_AGENT = (
    f"payband-mcp/{__version__} (+https://github.com/dheerajjha/payband-mcp)"
)

# Keka's own SalaryPeriod enum, read off its careers bundle:
#   {0: "Not Available", 1: "Hourly", 2: "Bi Weekly", 3: "Monthly", 4: "Annual"}
# 0 is deliberately absent -- see the module docstring.  2 is kept distinct
# rather than folded into "week", because a fortnightly figure reported as
# weekly is wrong by a factor of two.
_PERIOD = {1: "hour", 2: "two_weeks", 3: "month", 4: "year"}

_last_request = 0.0
_throttle_lock = threading.Lock()


class KekaNotFound(LookupError):
    """No public Keka careers site exists under this tenant."""


def _throttle() -> None:
    global _last_request
    with _throttle_lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _get(tenant: str, portal: str) -> Any:
    """Fetch one tenant's active postings.

    Redirects are not followed on purpose.  A tenant that does not exist is a
    302 to /careers/Content/TenantNotFound.html, and following it would turn a
    clear "no such employer" into an HTML page we would have to sniff.  Keeping
    the redirect visible is what lets a wrong tenant name stay distinguishable
    from a broken endpoint.
    """
    _throttle()
    try:
        response = httpx.get(
            BASE.format(tenant=tenant, portal=portal),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise KekaNotFound(tenant) from exc
    if response.is_redirect or response.status_code in (403, 404):
        raise KekaNotFound(tenant)
    response.raise_for_status()
    return response.json()


def pay(job: dict[str, Any]) -> dict[str, Any] | None:
    """The band this posting publishes, or None if it publishes none.

    `salaryRange` is present on every posting; the figures are not.  An
    employer who publishes nothing still sends currency and period, so absence
    of `maximum` -- not absence of the object -- is what says "no range here".
    """
    band = job.get("salaryRange")
    if not isinstance(band, dict):
        return None
    high = band.get("maximum")
    low = band.get("minimum")
    if not isinstance(high, (int, float)) or high <= 0:
        return None
    if not isinstance(low, (int, float)) or low <= 0:
        low = high
    if high < low:
        return None
    return {
        "min": float(low),
        "max": float(high),
        "currency": (band.get("currency") or "INR").upper(),
        # None where the posting declines to state a period.
        "interval": _PERIOD.get(band.get("salaryPeriod")),
        "basis": "base",
        "source": "structured",
    }


def location(job: dict[str, Any]) -> str:
    """Every location the posting names, as the board itself names them.

    Kept as one string to match the other adapters.  The country code travels
    with each entry, so a caller that needs the market does not have to infer
    it from the city -- which is the guesswork #17 exists because of.
    """
    out = []
    for place in job.get("jobLocations") or []:
        if not isinstance(place, dict):
            continue
        name = place.get("name") or place.get("city")
        country = place.get("countryName")
        if name and country and country not in name:
            out.append(f"{name}, {country}")
        elif name:
            out.append(str(name))
    return "; ".join(out)


def list_postings(
    tenant: str, portal: str = DEFAULT_PORTAL, role: str = ""
) -> Iterator[dict[str, Any]]:
    """Active postings for one tenant, narrowed by title if a role is given.

    The endpoint returns every active posting in one response and offers no
    server-side search, so the filtering is ours.
    """
    data = _get(tenant, portal)
    if not isinstance(data, list):
        raise KekaNotFound(tenant)
    needle = role.lower().strip()
    for job in data:
        if not isinstance(job, dict):
            continue
        title = job.get("title") or ""
        if needle and needle not in title.lower():
            continue
        yield job
