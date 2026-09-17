"""Self-hosted careers endpoints. No network: recorded response shapes only."""

import pytest

from payband_mcp import ats, money, selfhosted

# Trimmed from the live endpoint. Atlassian publishes three US geographic
# zones per role, and its non-US ranges with a CA$ symbol.
ROWS = [
    {
        "title": "Software Engineer, 2027 Graduate U.S.",
        "locations": ["Seattle - United States -   Seattle, Washington  United States"],
        "applyUrl": "https://example.invalid/25813",
        "payRanges": (
            "<p>In The <strong>United States</strong>, we have three geographic pay "
            "zones. For this role, our current base pay ranges for new hires in each "
            "zone are:</p>\n<p><strong>Zone A</strong>: $122,400 - $159,800</p>\n"
            "<p><strong>Zone B</strong>: $110,160 - $143,820</p>\n"
            "<p><strong>Zone C</strong>: $101,592 - $132,634</p>"
        ),
    },
    {
        "title": "Software Engineer, 2027 Graduate Canada",
        "locations": ["Canada -     Canada"],
        "applyUrl": "https://example.invalid/25812",
        "payRanges": (
            "<p>In <strong>Canada</strong>, for this role, our current base pay range "
            "for new hires is:</p>\n<p><strong>Canada</strong>: CA$94,500 - CA$123,375</p>"
        ),
    },
    {
        "title": "Software Engineer Intern, 2027 Canada",
        "locations": ["Canada -     Canada"],
        "applyUrl": "https://example.invalid/25811",
        # Atlassian really does publish zeroes on some intern postings.
        "payRanges": "<p><strong>Canada</strong>: CA$0 - CA$0</p>",
    },
    {
        "title": "Account Executive",
        "locations": ["Remote - Japan - Remote"],
        "applyUrl": "https://example.invalid/25583",
        "payRanges": "",
    },
]


@pytest.fixture
def atlassian(monkeypatch):
    monkeypatch.setattr(selfhosted, "_get", lambda url, ua: ROWS)
    return selfhosted.atlassian("test")


def test_every_row_becomes_a_posting(atlassian):
    assert len(atlassian) == 4
    assert {p["company"] for p in atlassian} == {"Atlassian"}
    assert {p["board"] for p in atlassian} == {"atlassian"}


def test_the_us_zones_are_kept_apart(atlassian):
    """Their union is 101,592-159,800, which is nobody's band."""
    pay = atlassian[0]["pay"]
    assert (pay["min"], pay["max"], pay["currency"]) == (122400, 159800, "USD")
    assert [(b["label"], b["min"]) for b in pay["bands"]] == [
        ("Zone A", 122400), ("Zone B", 110160), ("Zone C", 101592)
    ]


def test_the_ca_dollar_symbol_is_not_usd(atlassian):
    pay = atlassian[1]["pay"]
    assert (pay["min"], pay["max"], pay["currency"]) == (94500, 123375, "CAD")


def test_a_zero_range_is_not_a_published_band(atlassian):
    assert atlassian[2]["pay"] is None


def test_a_posting_with_no_payranges_is_silent_not_guessed(atlassian):
    assert atlassian[3]["pay"] is None


def test_location_is_flattened_for_reading(atlassian):
    assert atlassian[0]["location"] == (
        "Seattle, United States, Seattle, Washington United States"
    )


def test_an_empty_or_wrong_shaped_response_is_an_error(monkeypatch):
    monkeypatch.setattr(selfhosted, "_get", lambda url, ua: [])
    with pytest.raises(selfhosted.SelfHostedNotFound):
        selfhosted.atlassian("test")
    monkeypatch.setattr(selfhosted, "_get", lambda url, ua: {"jobs": []})
    with pytest.raises(selfhosted.SelfHostedNotFound):
        selfhosted.atlassian("test")


def test_fetch_postings_routes_a_known_employer_to_its_own_endpoint(monkeypatch):
    monkeypatch.setattr(selfhosted, "_get", lambda url, ua: ROWS)
    monkeypatch.setattr(
        ats, "_BOARDS", ()
    )  # no board may answer; the name alone must route
    board, postings = ats.fetch_postings("Atlassian")
    assert board == "atlassian"
    assert len(postings) == 4


def test_prefix_labels_do_not_swallow_ordinary_prose():
    """"...ranges are:" must not become a band label."""
    pay = money.parse("Our base pay range is: $120,000 - $150,000")
    assert pay["min"] == 120000
    assert "bands" not in pay or pay["bands"][0]["label"] != "is"
