"""Unit tests for the pure logic in the server layer (no network)."""

from __future__ import annotations

from blind_mcp import server


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


def test_find_mcp_schema_exposes_page():
    import asyncio

    tools = asyncio.run(server.mcp.list_tools())
    schema = next(tool for tool in tools if tool.name == "find").input_schema
    assert schema["properties"]["page"]["type"] == "integer"
    assert schema["properties"]["page"]["default"] == 1
    assert schema["properties"]["limit"]["default"] == 25
    assert schema["required"] == ["company", "keyword"]
