"""market_rate must fix the unit before it averages or ranks (#24).

Shipped wrong from 0.3.0: pay_bands fixed the currency and the interval,
market_rate fixed only the currency. No network.
"""

import pytest

from payband_mcp import ats, fx, server


def posting(low, high, interval, title, currency="USD"):
    return {
        "title": title, "location": "X", "url": "u", "company": "c", "board": "b",
        "pay": {"min": low, "max": high, "currency": currency,
                "interval": interval, "basis": "base", "source": "t"},
    }


@pytest.fixture
def boards(monkeypatch):
    registry: dict[str, list] = {}
    monkeypatch.setattr(
        ats, "fetch_postings",
        lambda company, board=None, role="": ("b", registry[company]),
    )
    return registry


def test_an_hourly_rate_is_not_averaged_into_an_annual_band(boards):
    """It reported a senior engineer band of 95-130. It pays 200,000."""
    boards["Acme"] = [
        posting(200_000, 260_000, "year", "Senior Engineer"),
        posting(95, 130, "hour", "Senior Engineer, Contract"),
    ]
    row = server.market_rate("engineer", ["Acme"], level="senior")["rates"][0]
    assert (row["typical"]["min"], row["typical"]["max"]) == (200_000, 260_000)
    assert row["interval"] == "year"


def test_every_row_says_what_unit_it_is_in(boards):
    boards["Acme"] = [posting(200_000, 260_000, "year", "Senior Engineer")]
    row = server.market_rate("engineer", ["Acme"])["rates"][0]
    assert row["interval"] == "year"


def test_companies_in_different_units_are_never_ranked_together(boards):
    """No exchange rate converts an hourly figure into an annual one."""
    boards["AnnualCo"] = [posting(200_000, 260_000, "year", "Senior Engineer")]
    boards["HourlyCo"] = [posting(95, 130, "hour", "Senior Engineer")]

    result = server.market_rate("engineer", ["AnnualCo", "HourlyCo"], level="senior")

    assert [r["company"] for r in result["rates"]] == ["AnnualCo"]
    assert result["interval"] == "year"
    assert [(o["company"], o["interval"]) for o in result["other_intervals"]] == [
        ("HourlyCo", "hour")
    ]


def test_an_unstated_period_does_not_outvote_a_stated_one(boards):
    """Some boards publish a band with the period field set to 'not available'."""
    boards["Keka"] = [
        posting(800_000, 1_500_000, None, "Frontend Engineer", "INR"),
        posting(1_200_000, 2_000_000, None, "Backend Lead", "INR"),
        posting(1_200_000, 1_600_000, None, "AI Engineer", "INR"),
        posting(240_000, 360_000, None, "Field Engineer", "INR"),
        posting(2_000_000, 3_500_000, "year", "Tech Lead", "INR"),
        posting(1_500_000, 2_500_000, "year", "DevOps Engineer", "INR"),
    ]
    row = server.market_rate("engineer", ["Keka"])["rates"][0]
    assert row["interval"] == "year"
    # ...and the unstated ones are excluded rather than assumed to be annual.
    assert row["postings"] == 1
    assert row["typical"]["min"] == 1_500_000


def test_when_nothing_states_a_period_the_band_still_reports(boards):
    """Withholding it would discard the only pay a whole market publishes."""
    boards["Keka"] = [
        posting(800_000, 1_500_000, None, "Frontend Engineer", "INR"),
        posting(1_200_000, 2_000_000, None, "Backend Lead", "INR"),
    ]
    result = server.market_rate("engineer", ["Keka"])
    assert result["interval"] is None
    assert result["rates"][0]["interval"] is None
    assert result["rates"][0]["typical"]["min"] == 800_000


def test_mixed_currency_and_mixed_unit_together(boards, monkeypatch):
    """Currency converts, unit does not. Both must be handled at once."""
    monkeypatch.setattr(
        fx, "rates", lambda *a, **k: {"date": "2026-09-17",
                                      "rates": {"USD": 1.0, "GBP": 0.74166}}
    )
    boards["US"] = [posting(200_000, 260_000, "year", "Senior Engineer")]
    boards["UK"] = [posting(90_000, 120_000, "year", "Senior Engineer", "GBP")]
    boards["Contract"] = [posting(95, 130, "hour", "Senior Engineer")]

    result = server.market_rate("engineer", ["US", "UK", "Contract"])

    assert [r["company"] for r in result["rates"]] == ["US", "UK"]
    assert result["rates"][1]["typical_in_USD"] == {"min": 121_349, "max": 161_799}
    assert [o["company"] for o in result["other_intervals"]] == ["Contract"]


# --- the table's period must be chosen before each employer's band ---------


def test_an_employer_on_two_periods_contributes_the_comparable_band(boards):
    """Fixing the unit per company, before the table's, discards real bands.

    This employer posts two contract roles hourly and one salaried annually,
    so its own modal period is hourly. Choosing there sets it aside as an
    hourly outlier while it is holding an annual band directly comparable
    with every other row -- and with only these two employers, the table then
    ranked one contract rate and set aside the only other annual band there
    was. Nobody got the comparison they asked for.
    """
    boards["HourlyCo"] = [
        posting(95, 130, "hour", "Senior Engineer, Contract"),
        posting(100, 140, "hour", "Senior Engineer, Contract II"),
        posting(200_000, 260_000, "year", "Senior Engineer"),
    ]
    boards["AnnualCo"] = [posting(210_000, 270_000, "year", "Senior Engineer")]

    result = server.market_rate("engineer", ["HourlyCo", "AnnualCo"], level="senior")

    assert result["interval"] == "year"
    assert sorted(r["company"] for r in result["rates"]) == ["AnnualCo", "HourlyCo"]
    banded = {r["company"]: r["typical"] for r in result["rates"]}
    assert banded["HourlyCo"] == {"min": 200_000, "max": 260_000}
    assert result["other_intervals"] == []


def test_a_band_not_chosen_is_still_reported(boards):
    """"We picked one" must stay distinct from "there was only one"."""
    boards["HourlyCo"] = [
        posting(95, 130, "hour", "Senior Engineer, Contract"),
        posting(200_000, 260_000, "year", "Senior Engineer"),
    ]
    boards["AnnualCo"] = [posting(210_000, 270_000, "year", "Senior Engineer")]

    result = server.market_rate("engineer", ["HourlyCo", "AnnualCo"], level="senior")
    rows = {r["company"]: r for r in result["rates"]}

    assert rows["HourlyCo"]["other_intervals_present"] == ["hour"]
    assert rows["AnnualCo"]["other_intervals_present"] == []


def test_the_period_is_stable_when_employers_are_evenly_split(boards):
    """One employer each way must not resolve by set ordering.

    The tie breaks toward the longer period: an employer posting the same
    title salaried and as a contract rate has published two different things,
    and the salaried one is what the question is about. Picking the larger of
    a set instead would change the answer between runs.
    """
    boards["A"] = [posting(200_000, 260_000, "year", "Senior Engineer")]
    boards["B"] = [posting(95, 130, "hour", "Senior Engineer, Contract")]

    seen = {server.market_rate("engineer", ["A", "B"], level="senior")["interval"]
            for _ in range(5)}
    assert seen == {"year"}


def test_an_employer_with_nothing_on_the_table_period_is_set_aside(boards):
    boards["A"] = [posting(210_000, 270_000, "year", "Senior Engineer")]
    boards["B"] = [posting(200_000, 250_000, "year", "Senior Engineer")]
    boards["C"] = [posting(90, 120, "hour", "Senior Engineer, Contract")]

    result = server.market_rate("engineer", ["A", "B", "C"], level="senior")

    assert [r["company"] for r in result["rates"]] == ["A", "B"]
    assert [o["company"] for o in result["other_intervals"]] == ["C"]
