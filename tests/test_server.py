"""Unit tests for the pure logic in the server layer (no network)."""

from __future__ import annotations

from payband_mcp import server


def test_topic_matching_handles_synonyms():
    topics = ["india", "wlb", "layoffs", "interview", "rsu"]
    match = lambda q: server._match_topic(topics, set(server._keywords(q)))

    assert match("how many days in office in India") == "india"
    assert match("what is work life balance like") == "wlb"
    assert match("any recent layoffs") == "layoffs"
    assert match("how is the bangalore office") == "india"
    assert match("do they give stock refreshers") == "rsu"


def test_noise_comments_are_filtered():
    assert not server._informative("TC?")
    assert not server._informative("tc or gtfo")
    assert not server._informative("Same question")
    assert server._informative(
        "the wfo policy is enforced orgwide, you can take few times wfh"
    )
    assert server._informative("16 weeks now")
    assert server._informative("4 days mandatory")


def test_ranking_prefers_relevance_over_upvotes():
    words = set(server._keywords("how many days in office wfo policy"))
    comments = [
        {"text": "TC or GTFO", "likes": 99, "company": "X", "replies": []},
        {
            "text": "the wfo policy is enforced orgwide, 4 days in office mandatory",
            "likes": 1,
            "company": "Adobe",
            "replies": [],
        },
    ]
    top = server._rank_comments(comments, words, 5)
    assert top[0]["company"] == "Adobe"


def test_probe_terms_prefer_distinctive_words():
    terms = server._probe_terms(
        "what is the maternity leave policy", "Intuit", ["intuit", "layoffs"]
    )
    assert "maternity" in terms
    assert "policy" not in terms  # low-signal: matches hundreds of threads
    assert "intuit" not in terms  # the company name is not a useful probe
    assert terms.index("maternity") < terms.index("leave")  # longer == sharper


def test_probe_terms_lead_with_a_matched_topic():
    terms = server._probe_terms(
        "how many days in office in India", "Roku", ["india", "wlb", "culture"]
    )
    assert terms[0] == "india"


def test_referral_posts_are_dropped():
    assert server._is_junk({"title": "Looking for referrals urgently"})
    assert server._is_junk({"title": "Laid off, 7 yoe frontend. Need referral"})
    assert not server._is_junk({"title": "Maternity leave/benefits at Intuit"})
    assert not server._is_junk({"title": "Intuit India RTO Policy"})


# Synthetic pages exercise the actual parsers; only HTTP/company resolution
# are replaced, so a broken keyword pagination regex fails these tests too.
def _find_page(page, total=272, cards=3):
    return (
        f'<span>{total}</span><span class="ml-1">Results</span>'
        '<a href="/company/Acme/posts/acme-leave?page=10">10</a>'
        + ''.join(
            f'<article data-testid="article-preview-card">'
            f'<a href="/post/leave-{page}-{i}">'
            f'<span class="sr-only">Leave {page}-{i}</span></a></article>'
            for i in range(cards)
        )
    )


def test_find_pages_and_positional_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_resolve", lambda company: "Acme")

    def fetch(path):
        calls.append(path)
        page = int(path.split("?page=")[1]) if "?page=" in path else 1
        return _find_page(page)

    monkeypatch.setattr(server.http, "fetch", fetch)
    first = server.find("acme", "Leave")
    second = server.find("acme", "Leave", 2, page=2)
    last = server.find("acme", "Leave", page=10)
    assert [r["page"] for r in (first, second, last)] == [1, 2, 10]
    assert all(r["max_page"] == 10 and r["total_matches"] == 272
               for r in (first, second, last))
    assert len(first["posts"]) == 3
    assert len(second["posts"]) == 2
    assert first["posts"][0]["url"] != second["posts"][0]["url"]
    assert calls == ["/company/Acme/posts/acme-leave",
                     "/company/Acme/posts/acme-leave?page=2",
                     "/company/Acme/posts/acme-leave?page=10"]


def test_find_empty_page_does_not_fallback(monkeypatch):
    monkeypatch.setattr(server, "_resolve", lambda company: "Acme")
    calls = []

    def fetch(path):
        calls.append(path)
        return ""

    monkeypatch.setattr(server.http, "fetch", fetch)
    for page in (1, 2, 11):
        assert server.find("Acme", "missing", page=page) == {
            "company": "Acme", "keyword": "missing", "page": page,
            "max_page": 1, "total_matches": 0, "posts": [],
        }
    assert len(calls) == 3


def test_find_limit_boundaries(monkeypatch):
    monkeypatch.setattr(server, "_resolve", lambda company: "Acme")
    monkeypatch.setattr(server.http, "fetch", lambda path: _find_page(1))
    assert server.find("Acme", "leave", limit=0)["posts"] == []
    assert len(server.find("Acme", "leave", limit=100)["posts"]) == 3


def test_find_rejects_invalid_inputs_before_network(monkeypatch):
    import pytest

    def unexpected(company):
        pytest.fail("invalid input must not resolve or fetch a company")

    monkeypatch.setattr(server, "_resolve", unexpected)
    for page in (0, -1, 1.5, "2", True, None):
        with pytest.raises(ValueError, match="page must be a positive integer"):
            server.find("Acme", "leave", page=page)
    for limit in (-1, 1.5, "2", True, None):
        with pytest.raises(ValueError, match="limit must be a non-negative integer"):
            server.find("Acme", "leave", limit=limit)


def test_research_does_not_walk_find_pagination(monkeypatch):
    monkeypatch.setattr(server, "_resolve", lambda company: "Acme")
    monkeypatch.setattr(server, "company_topics", lambda company: {"topics": []})
    monkeypatch.setattr(server, "_probe_terms", lambda *args: ["leave", "maternity"])
    calls = []

    def fetch(path):
        calls.append(path)
        return _find_page(1)

    monkeypatch.setattr(server.http, "fetch", fetch)
    monkeypatch.setattr(server, "read_post", lambda url: {"url": url, "comments": []})
    result = server.research("Acme", "maternity leave")
    assert result["considered"] == 3
    assert calls == ["/company/Acme/posts/acme-leave",
                     "/company/Acme/posts/acme-maternity"]


def test_find_mcp_schema_exposes_page(monkeypatch):
    import asyncio
    import importlib

    # Blind tools are not registered by default while Blind 403s every
    # automated request, so the schema only exists with them switched on.
    monkeypatch.setenv("PAYBAND_ENABLE_BLIND", "1")
    with_blind = importlib.reload(server)
    try:
        tools = asyncio.run(with_blind.mcp.list_tools())
        schema = next(tool for tool in tools if tool.name == "find").input_schema
    finally:
        monkeypatch.delenv("PAYBAND_ENABLE_BLIND")
        importlib.reload(server)
    assert schema["properties"]["page"]["type"] == "integer"
    assert schema["properties"]["page"]["default"] == 1
    assert schema["properties"]["limit"]["default"] == 25
    assert schema["required"] == ["company", "keyword"]


def test_only_working_tools_are_offered_by_default():
    """A tool list that can only raise costs the model context and misleads it."""
    import asyncio

    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert names == {"job_openings", "pay_bands", "market_rate"}
    assert server.BLIND_ENABLED is False


def test_company_candidates_are_cheapest_first():
    """Each candidate is a throttled request, so order is a cost decision."""
    cands = server._company_candidates("Goldman Sachs")
    assert cands[0] == "goldman-sachs"          # resolves most companies in one
    assert "Goldman-Sachs" in cands             # hyphenated, as Blind writes it
    assert len(cands) == len(set(cands))        # no wasted duplicate requests
    assert server._company_candidates("Roku")[0] == "roku"


def test_old_env_var_names_still_work(monkeypatch):
    """The project was blind-mcp; a rename must not ignore existing config."""
    from payband_mcp import http

    monkeypatch.delenv("PAYBAND_CACHE_TTL", raising=False)
    monkeypatch.setenv("BLIND_MCP_CACHE_TTL", "99")
    assert http.env("CACHE_TTL") == "99"

    # ...but the new name wins when both are set.
    monkeypatch.setenv("PAYBAND_CACHE_TTL", "7")
    assert http.env("CACHE_TTL") == "7"

    monkeypatch.delenv("BLIND_MCP_CACHE_TTL")
    monkeypatch.delenv("PAYBAND_CACHE_TTL")
    assert http.env("CACHE_TTL", "fallback") == "fallback"


def test_cli_version_flag(capsys):
    """The bug template tells reporters to run this; it used to error."""
    import sys

    from payband_mcp import __version__

    old = sys.argv
    try:
        sys.argv = ["payband-mcp", "--version"]
        try:
            server.main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("expected SystemExit from --version")
    finally:
        sys.argv = old
    assert capsys.readouterr().out.strip() == __version__


# --- intervals: a band whose period nobody stated ---------------------------
#
# Most sources state the period a range covers. Keka publishes figures and
# sends salaryPeriod 0, "Not Available", so `interval` can be None -- which no
# other adapter has ever produced. These cover what that does to aggregation.


def _priced(title, low, high, interval, currency="INR"):
    return {
        "title": title, "location": "Chennai, India", "url": "u",
        "company": "Acme", "board": "keka", "pay_known": True,
        "pay": {"min": low, "max": high, "currency": currency,
                "interval": interval, "basis": "base", "source": "structured"},
    }


def _bands(monkeypatch, hits):
    from payband_mcp import ats

    monkeypatch.setattr(ats, "fetch_postings", lambda c, b=None, role="": ("keka", hits))
    monkeypatch.setattr(ats, "matching", lambda postings, role: hits)
    monkeypatch.setattr(ats, "enrich_pay", lambda hits, limit=40: None)
    return server.pay_bands("Acme", "engineer")


def test_an_unstated_interval_does_not_outvote_a_stated_one(monkeypatch):
    """Four postings that say nothing must not outrank two that say "year".

    `interval` was the modal value over every posting, and None is a perfectly
    good dict key, so on a board where most employers decline to state a period
    None won the vote and the postings carrying real evidence were the ones
    discarded. The better-attested data has to win.
    """
    out = _bands(monkeypatch, [
        _priced("Frontend Engineer", 800_000, 1_500_000, None),
        _priced("Backend Lead", 1_200_000, 2_000_000, None),
        _priced("AI Engineer", 1_200_000, 1_600_000, None),
        _priced("Field Service Engineer", 240_000, 360_000, None),
        _priced("Tech Lead", 2_000_000, 3_500_000, "year"),
        _priced("DevOps Engineer", 1_500_000, 2_500_000, "year"),
    ])
    assert out["interval"] == "year"
    assert sum(b["postings"] for b in out["by_level"].values()) == 2


def test_postings_left_out_for_an_unstated_interval_are_counted(monkeypatch):
    """Dropping them silently is the failure not_checked_count exists against."""
    out = _bands(monkeypatch, [
        _priced("Frontend Engineer", 800_000, 1_500_000, None),
        _priced("Backend Lead", 1_200_000, 2_000_000, None),
        _priced("Tech Lead", 2_000_000, 3_500_000, "year"),
    ])
    assert out["interval_unstated_count"] == 2
    # They published a range, so they are not silent and were not unchecked.
    assert out["no_range_count"] == 0
    assert out["not_checked_count"] == 0


def test_an_unstated_interval_is_not_reported_as_another_interval(monkeypatch):
    """None is the absence of a value, so it is not an "other interval".

    It also cannot be sorted against strings: mixing the two in the set that
    builds other_intervals_present raised TypeError and took the whole tool
    down rather than mislabelling anything.
    """
    out = _bands(monkeypatch, [
        _priced("A", 2_000_000, 3_000_000, "year"),
        _priced("B", 2_100_000, 3_100_000, "year"),
        _priced("C", 2_200_000, 3_200_000, "year"),
        _priced("D", 800_000, 1_500_000, None),
        _priced("E", 60_000, 90_000, "month"),
    ])
    assert out["other_intervals_present"] == ["month"]
    assert out["interval_unstated_count"] == 1


def test_bands_still_report_when_no_posting_states_an_interval(monkeypatch):
    """With nothing to prefer, the figures are still real and still published.

    Reporting interval None says what is known. Withholding the bands entirely
    would throw away the only pay a whole market publishes.
    """
    out = _bands(monkeypatch, [
        _priced("Frontend Engineer", 800_000, 1_500_000, None),
        _priced("Backend Lead", 1_200_000, 2_000_000, None),
    ])
    assert out["interval"] is None
    assert sum(b["postings"] for b in out["by_level"].values()) == 2
    # Not left out of anything, so nothing to count as left out.
    assert out["interval_unstated_count"] == 0
