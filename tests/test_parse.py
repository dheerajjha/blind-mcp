"""Parser tests.

Fixtures are synthetic -- see tests/fixtures/make_fixtures.py for why and how.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from blind_mcp import parse

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8")


@pytest.fixture(scope="module")
def post() -> dict:
    return parse.parse_post(_fixture("acme_post.html.gz"))


@pytest.fixture(scope="module")
def company_html() -> str:
    return _fixture("acme_company.html.gz")


def test_post_metadata(post):
    assert post["title"] == "Acme India - office policy"
    assert post["published"] == "2026-03-31"
    assert post["comment_count"] == 9
    assert "4-day office policy" in post["body"]


def test_ai_summary_is_captured(post):
    # Blind generates this itself; it is the highest-value field on the page.
    assert "four-day" in post["ai_summary"]


def test_comments_carry_employer(post):
    by_company = {c["company"] for c in post["comments"]}
    assert {"Northwind", "Initech", "Globex"} <= by_company


def test_replies_are_nested_not_duplicated(post):
    """Every reply also matches the comment regex; roots only at top level."""
    texts = [c["text"] for c in post["comments"]]
    assert len(texts) == len(set(texts))
    assert any(c["replies"] for c in post["comments"])


def test_listing_cards(company_html):
    posts = parse.parse_listing(company_html)
    assert len(posts) == 3
    first = posts[0]
    assert first["url"].startswith("https://www.teamblind.com/post/")
    assert first["title"]
    assert all(p["url"] != posts[0]["url"] for p in posts[1:])


def test_company_topics(company_html):
    meta = parse.parse_company_topics(company_html)
    assert "acme-india" in meta["topics"]
    assert meta["total_results"] == 1842
    assert meta["max_page"] > 1


@pytest.mark.parametrize("path", ["/company/Acme/posts", "/company/Acme/posts/acme-leave"])
def test_pagination_for_company_and_keyword_pages(path):
    html = '<span>272</span><span class="ml-1">Results</span>' + ''.join(
        f'<a href="{path}?page={page}">{page}</a>' for page in (1, 2, 3, 10)
    )
    html += '<a href="/company/Acme/posts/acme-leave">leave</a>'
    meta = parse.parse_company_topics(html)
    assert meta == {"topics": ["acme-leave"], "max_page": 10, "total_results": 272}


def test_empty_listing_metadata():
    assert parse.parse_company_topics("") == {
        "topics": [], "max_page": 1, "total_results": None,
    }
