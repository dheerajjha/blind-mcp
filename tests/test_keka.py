"""Keka adapter. No network: every response here is a generated shape.

The postings are invented. Only the schema is real -- the field names, the
two shapes `salaryRange` comes in, and the SalaryPeriod enum values.
"""

import httpx
import pytest

from payband_mcp import keka


def job(**over):
    """A posting in the shape the endpoint returns, with no band by default."""
    out = {
        "id": 1,
        "title": "Backend Engineer",
        "departmentName": "Engineering",
        "experience": "4-6",
        "jobLocations": [
            {
                "id": 9,
                "name": "Chennai",
                "city": "Chennai",
                "state": "TN",
                "countryCode": "IN",
                "countryName": "India",
            }
        ],
        # Present on every posting, figures or not.
        "salaryRange": {
            "currency": "INR",
            "salaryPeriod": 0,
            "cultureInfo": "en-IN",
        },
    }
    out.update(over)
    return out


def band(minimum, maximum, period, currency="INR"):
    return {
        "minimum": minimum,
        "maximum": maximum,
        "currency": currency,
        "salaryPeriod": period,
        "cultureInfo": "en-IN",
    }


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(keka, "_throttle", lambda: None)


# --- the period enum, which is the whole point of this adapter -------------


def test_an_annual_band_is_read_as_annual():
    pay = keka.pay(job(salaryRange=band(2_000_000, 3_500_000, 4)))
    assert pay["min"] == 2_000_000
    assert pay["max"] == 3_500_000
    assert pay["currency"] == "INR"
    assert pay["interval"] == "year"


def test_a_band_with_no_stated_period_does_not_become_a_year():
    """SalaryPeriod 0 is "Not Available", not a missing default.

    The employer published figures and declined to say what period they cover.
    Calling it a year is the kind of confident wrong number this project keeps
    having to fix, so the interval stays None and the figures still stand.
    """
    pay = keka.pay(job(salaryRange=band(800_000, 1_500_000, 0)))
    assert pay["interval"] is None
    assert pay["min"] == 800_000
    assert pay["max"] == 1_500_000


def test_an_unstated_period_cannot_be_grouped_with_a_stated_one():
    """The two must not land in the same bucket, because they are not the same.

    `server.py` groups by interval, so None keeps an unstated band out of the
    annual figure rather than silently inflating it.
    """
    stated = keka.pay(job(salaryRange=band(800_000, 1_500_000, 4)))
    unstated = keka.pay(job(salaryRange=band(800_000, 1_500_000, 0)))
    assert stated["min"] == unstated["min"]
    assert stated["interval"] != unstated["interval"]


def test_monthly_and_hourly_periods_are_read_as_themselves():
    assert keka.pay(job(salaryRange=band(60_000, 90_000, 3)))["interval"] == "month"
    assert keka.pay(job(salaryRange=band(500, 900, 1)))["interval"] == "hour"


def test_fortnightly_is_not_reported_as_weekly():
    """Bi Weekly folded into "week" would be wrong by a factor of two."""
    assert keka.pay(job(salaryRange=band(4_000, 6_000, 2)))["interval"] == "two_weeks"


# --- publishing nothing is different from publishing zero ------------------


def test_a_posting_that_publishes_no_figures_has_no_band():
    """`salaryRange` is still sent; the figures are what is missing."""
    assert keka.pay(job()) is None


def test_a_zero_maximum_is_not_a_band():
    assert keka.pay(job(salaryRange=band(0, 0, 4))) is None


def test_a_single_figure_is_read_as_a_point_not_a_hole():
    posting = job(salaryRange={"maximum": 1_200_000, "currency": "INR",
                               "salaryPeriod": 4, "cultureInfo": "en-IN"})
    pay = keka.pay(posting)
    assert pay["min"] == pay["max"] == 1_200_000


def test_a_reversed_range_is_refused_rather_than_swapped():
    assert keka.pay(job(salaryRange=band(900_000, 300_000, 4))) is None


def test_a_missing_salary_object_is_not_an_error():
    assert keka.pay({"title": "Backend Engineer"}) is None


def test_the_prerendered_display_string_is_never_the_source_of_truth():
    """It carries no period, so reading it is how an interval gets invented."""
    posting = job(
        salaryRange=band(800_000, 1_500_000, 0),
        salaryRangeFormat="INR 8,00,000.00 - 15,00,000.00",
    )
    pay = keka.pay(posting)
    assert pay["interval"] is None
    assert pay["min"] == 800_000


# --- locations -------------------------------------------------------------


def test_location_names_the_country_so_it_need_not_be_guessed():
    assert keka.location(job()) == "Chennai, India"


def test_several_locations_are_all_kept():
    posting = job(jobLocations=[
        {"name": "Chennai", "countryName": "India"},
        {"name": "Singapore", "countryName": "Singapore"},
    ])
    assert keka.location(posting) == "Chennai, India; Singapore"


def test_a_posting_with_no_location_is_not_an_error():
    assert keka.location(job(jobLocations=[])) == ""


# --- the transport ---------------------------------------------------------


def respond(monkeypatch, response):
    monkeypatch.setattr(keka.httpx, "get", lambda *a, **k: response)


def reply(status, json_body=None, headers=None):
    return httpx.Response(
        status,
        json=json_body if json_body is not None else [],
        headers=headers or {},
        request=httpx.Request("GET", "https://acme.keka.com/careers/"),
    )


def test_an_unknown_tenant_is_a_redirect_not_a_404(monkeypatch):
    """Keka answers a wrong tenant with a 302 to TenantNotFound.html.

    Following it would hand us an HTML page to sniff. Refusing to follow keeps
    "no such employer" distinguishable from "the endpoint broke" -- ten wrong
    guesses say nothing about the API.
    """
    respond(monkeypatch, reply(
        302, headers={"Location": "/careers/Content/TenantNotFound.html"}
    ))
    with pytest.raises(keka.KekaNotFound):
        list(keka.list_postings("nosuchtenant"))


def test_a_404_is_also_a_missing_board(monkeypatch):
    respond(monkeypatch, reply(404))
    with pytest.raises(keka.KekaNotFound):
        list(keka.list_postings("acme"))


def test_a_transport_failure_is_a_missing_board(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no such host")

    monkeypatch.setattr(keka.httpx, "get", boom)
    with pytest.raises(keka.KekaNotFound):
        list(keka.list_postings("acme"))


def test_a_response_that_is_not_a_list_is_refused(monkeypatch):
    respond(monkeypatch, reply(200, {"error": "nope"}))
    with pytest.raises(keka.KekaNotFound):
        list(keka.list_postings("acme"))


def test_postings_come_back_whole(monkeypatch):
    respond(monkeypatch, reply(200, [job(), job(id=2, title="Tech Lead")]))
    out = list(keka.list_postings("acme"))
    assert [j["title"] for j in out] == ["Backend Engineer", "Tech Lead"]


def test_a_role_narrows_by_title(monkeypatch):
    respond(monkeypatch, reply(200, [
        job(title="Backend Engineer"),
        job(id=2, title="Tech Lead"),
        job(id=3, title="Staff Engineer"),
    ]))
    out = list(keka.list_postings("acme", role="engineer"))
    assert [j["title"] for j in out] == ["Backend Engineer", "Staff Engineer"]


def test_the_default_portal_is_the_literal_string(monkeypatch):
    """A site with no named portal is addressed as "default", not as empty."""
    seen = {}

    def capture(url, **kwargs):
        seen["url"] = url
        return reply(200, [])

    monkeypatch.setattr(keka.httpx, "get", capture)
    list(keka.list_postings("acme"))
    assert seen["url"] == "https://acme.keka.com/careers/api/jobs/default/active"


def test_the_request_names_itself(monkeypatch):
    """The same honest User-Agent the rest of the project sends."""
    seen = {}

    def capture(url, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return reply(200, [])

    monkeypatch.setattr(keka.httpx, "get", capture)
    list(keka.list_postings("acme"))
    assert "payband-mcp/" in seen["User-Agent"]
    assert "github.com/dheerajjha/payband-mcp" in seen["User-Agent"]
