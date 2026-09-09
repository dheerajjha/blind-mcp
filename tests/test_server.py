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
