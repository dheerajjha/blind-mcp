"""MCP server exposing Blind company research.

Blind's own /search/ is robots-disallowed and ranks badly ("Roku India RTO"
returns twelve unrelated referral posts). But the company topic path accepts
*any* keyword, not only the ones Blind suggests, so
/company/Intuit/posts/intuit-maternity returns exactly the maternity threads.
That is how `find` and `research` search: precise, company-scoped, and on a
path robots.txt permits.
"""

from __future__ import annotations

import argparse
import os
import re
from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import http, parse

from . import __version__

mcp = MCPServer("blind", version=__version__)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "how", "what", "and", "or",
    "in", "at", "of", "for", "to", "on", "many", "much", "they", "give",
    "their", "from", "side", "it", "its", "with", "you", "your", "can", "i",
}


# Blind threads are dominated by low-content replies. Ranking comments by
# upvotes surfaces these over the actual answer, so they are filtered out
# before ranking rather than after.
_NOISE = re.compile(
    r"^(tc\??|tc or gtfo|tc and yoe|tc\?? ?/? ?yoe\??|yoe\??|same|same question|"
    r"watching|following|rn|bt|bt please|updoot|commenting|remindme.*|\+1|"
    r"can you refer.*|.{0,40}referral.{0,40})[\s.!?]*$",
    re.I,
)


# Referral and job-hunt posts swamp every Blind listing and never answer a
# question about the company. Dropped before ranking.
_JUNK_TITLE = re.compile(
    r"referral|refer me|looking for (a )?(job|role|referr)|seeking (a )?(job|role|referr)"
    r"|laid off|resume review|open to work|hiring\?|need referr",
    re.I,
)


def _is_junk(card: dict[str, Any]) -> bool:
    return bool(_JUNK_TITLE.search(card.get("title") or ""))


def _informative(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) > 25 and not _NOISE.match(stripped)


def _rank_comments(
    comments: list[dict[str, Any]], words: set[str], limit: int
) -> list[dict[str, Any]]:
    """Rank by overlap with the question, then by upvotes. Noise is dropped."""
    flat: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for c in comments:
        for node in (c, *(c.get("replies") or [])):
            key = (node.get("author"), node.get("text"))
            if key not in seen:
                seen.add(key)
                flat.append(node)

    def score(c: dict[str, Any]) -> tuple[int, int]:
        overlap = len(words & set(_keywords(c.get("text") or "")))
        return (overlap, c.get("likes") or 0)

    useful = [c for c in flat if _informative(c.get("text") or "")]
    ranked = sorted(useful, key=score, reverse=True)
    return [
        {k: v for k, v in c.items() if k != "replies"}
        for c in ranked
        if score(c)[0] > 0
    ][:limit] or [
        {k: v for k, v in c.items() if k != "replies"} for c in ranked[:limit]
    ]


# Blind's topic slugs are terse; questions are not. Map the common ones so
# "work life balance" still finds the `wlb` topic.
_TOPIC_ALIASES = {
    "wlb": {"work", "life", "balance", "wlb", "hours", "burnout", "overtime"},
    "rsu": {"rsu", "stock", "equity", "grant", "vest", "refresher"},
    "refresher": {"refresher", "refresh", "rsu", "grant"},
    "layoffs": {"layoff", "layoffs", "fired", "riff", "rif", "cuts", "severance"},
    "interview": {"interview", "loop", "onsite", "screen", "hiring", "rounds"},
    "culture": {"culture", "toxic", "management", "manager", "politics", "morale"},
    "india": {"india", "indian", "bengaluru", "bangalore", "blr", "hyderabad",
              "gurugram", "gurgaon", "mumbai", "noida", "pune"},
}


def _match_topic(topics: list[str], words: set[str]) -> str | None:
    """Pick the topic a question is really about."""
    best, best_score = None, 0
    for topic in topics:
        vocab = _TOPIC_ALIASES.get(topic, set()) | set(_keywords(topic.replace("-", " ")))
        score = len(words & vocab)
        if score > best_score:
            best, best_score = topic, score
    return best


# Common in questions, useless as Blind keywords: they match hundreds of
# loosely-related threads instead of narrowing. "maternity" is a good probe;
# "policy" is not.
_LOW_SIGNAL = {
    "policy", "policies", "details", "detail", "know", "want", "tell", "about",
    "like", "any", "company", "employee", "employees", "people", "actually",
    "really", "still", "need", "question", "questions", "get", "getting",
    "good", "bad", "better", "best", "worth", "there", "here", "who", "when",
    "where", "why", "which", "some", "more", "most", "new", "old", "one",
    "time", "year", "years", "guys", "anyone", "someone", "thing", "things",
    "give", "given", "does", "doing", "have", "has", "had", "was", "were",
}
_MAX_PROBES = 4


def _probe_terms(question: str, company: str, topics: list[str]) -> list[str]:
    """Keywords worth probing, most distinctive first.

    A matched suggested topic leads (Blind curates those), then the question's
    own words longest-first -- length is a cheap proxy for specificity.
    """
    words = set(_keywords(question))
    terms: list[str] = []

    topic = _match_topic(topics, words)
    if topic:
        terms.append(topic)

    skip = set(_keywords(company)) | _LOW_SIGNAL
    rest = [w for w in set(_keywords(question)) if w not in skip and len(w) > 3]
    for word in sorted(rest, key=len, reverse=True):
        if word not in terms:
            terms.append(word)
    return terms[:_MAX_PROBES]


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")


def _keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{2,}", text.lower()) if w not in _STOPWORDS]


@lru_cache(maxsize=128)
def _resolve(company: str) -> str:
    """Blind company URLs are case-sensitive; try the plausible spellings."""
    seen = []
    for name in (company, company.title(), company.capitalize(), company.upper()):
        if name in seen:
            continue
        seen.append(name)
        try:
            http.fetch(f"/company/{name}/posts")
            return name
        except Exception:
            continue
    raise ValueError(f"No Blind company page found for {company!r} (tried {seen}).")


@mcp.tool()
def company_topics(company: str) -> dict[str, Any]:
    """List the discussion topics Blind itself suggests for a company.

    These are the highest-signal entry points -- e.g. Roku exposes india, wlb,
    culture, layoffs, interview, rsu. Use one as the `topic` for company_posts.
    """
    name = _resolve(company)
    meta = parse.parse_company_topics(http.fetch(f"/company/{name}/posts"))
    prefix = f"{_slug(name)}-"
    return {
        "company": name,
        "topics": [t.removeprefix(prefix) for t in meta["topics"]],
        "total_posts": meta["total_results"],
        "max_page": meta["max_page"],
    }


@mcp.tool()
def company_posts(
    company: str, topic: str | None = None, page: int = 1, limit: int = 25
) -> dict[str, Any]:
    """List posts about a company, optionally narrowed to one topic.

    `topic` accepts a bare keyword from company_topics (e.g. "india", "wlb").
    """
    name = _resolve(company)
    path = f"/company/{name}/posts"
    if topic:
        path += f"/{_slug(name)}-{_slug(topic)}"
    if page > 1:
        path += f"?page={page}"

    posts = parse.parse_listing(http.fetch(path))
    return {
        "company": name,
        "topic": topic,
        "page": page,
        "count": len(posts[:limit]),
        "posts": posts[:limit],
    }


@mcp.tool()
def read_post(url: str, max_comments: int = 40) -> dict[str, Any]:
    """Read one Blind post in full.

    Returns the body, Blind's own AI summary of the comment thread, and the
    comments with each commenter's employer -- which is how you weigh a claim
    (an answer from someone at the company differs from a passer-by).
    """
    if "/post/" not in url:
        raise ValueError("Expected a Blind post URL containing /post/.")
    post = parse.parse_post(http.fetch(url))
    post["comments"] = post["comments"][:max_comments]
    return post


@mcp.tool()
def find(company: str, keyword: str, limit: int = 25) -> dict[str, Any]:
    """Find a company's posts about one keyword.

    This is how you search Blind. The company topic path accepts any keyword,
    so `find("Intuit", "maternity")` returns exactly the maternity threads --
    which paging the main listing will not surface, since they can be years
    deep. Prefer one distinctive noun ("maternity", "rto", "refresher");
    vague words like "policy" match hundreds of loosely-related posts.

    Returns no posts when nothing matches, rather than falling back to the
    generic listing, so an empty result is a real answer.
    """
    name = _resolve(company)
    html = http.fetch(f"/company/{name}/posts/{_slug(name)}-{_slug(keyword)}")
    return {
        "company": name,
        "keyword": keyword,
        "total_matches": parse.parse_company_topics(html)["total_results"] or 0,
        "posts": parse.parse_listing(html)[:limit],
    }


@mcp.tool()
def research(company: str, question: str, max_posts: int = 4) -> dict[str, Any]:
    """Answer a question about a company by pulling the most relevant threads.

    Probes the distinctive words in the question against Blind's keyword-scoped
    company pages, merges the hits, then returns the best threads in full with
    Blind's own AI summary and the comments that actually address the question.

    Ask naturally: "how many days in office in India", "what is the maternity
    leave policy", "do they require a PhD".
    """
    name = _resolve(company)
    words = set(_keywords(question))
    probes = _probe_terms(question, name, company_topics(name)["topics"])

    cards: list[dict[str, Any]] = []
    tried: dict[str, int] = {}
    seen: set[str] = set()
    for term in probes:
        try:
            hits = find(name, term, limit=40)["posts"]
        except Exception:
            continue
        tried[term] = len(hits)
        for card in hits:
            if card["url"] not in seen:
                seen.add(card["url"])
                # A term matching 7 posts is a sharper signal than one matching
                # 300: "maternity" means one thing, "leave" means three.
                card["matched_keyword"] = term
                card["_specific"] = len(hits) <= 10
                cards.append(card)

    cards = [c for c in cards if not _is_junk(c)]
    if not cards:  # no keyword matched anything; fall back to recent posts
        cards = [c for c in company_posts(name, limit=60)["posts"] if not _is_junk(c)]

    def score(card: dict[str, Any]) -> int:
        title = set(_keywords(card.get("title") or ""))
        preview = set(_keywords(card.get("preview") or ""))
        base = 3 * len(words & title) + len(words & preview)
        return base + (2 if base and card.get("_specific") else 0)

    ranked = sorted(cards, key=score, reverse=True)
    chosen = [c for c in ranked if score(c) > 0][:max_posts] or ranked[:max_posts]

    threads = []
    for card in chosen:
        card.pop("_specific", None)
        thread = read_post(card["url"])
        thread["matched_keyword"] = card.get("matched_keyword")
        # The answer is usually a quiet reply, not the top-voted one.
        thread["key_comments"] = _rank_comments(thread["comments"], words, 6)
        del thread["comments"]
        threads.append(thread)

    return {
        "company": name,
        "question": question,
        "keywords_tried": tried,
        "considered": len(cards),
        "threads": threads,
        "note": (
            "Blind is anonymous and unverified. Weigh claims by the commenter's "
            "employer and corroborate anything load-bearing. Check thread dates "
            "-- policy answers go stale."
        ),
    }


def main() -> None:
    """stdio by default; --http serves a long-lived process for pm2 et al.

    stdio servers are spawned per client and talk over stdin/stdout, so there
    is nothing for a process supervisor to keep alive. --http gives one
    persistent endpoint that any number of clients can connect to.
    """
    parser = argparse.ArgumentParser(prog="blind-mcp")
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over streamable HTTP instead of stdio",
    )
    parser.add_argument("--host", default=os.environ.get("BLIND_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("BLIND_MCP_PORT", "8787"))
    )
    args = parser.parse_args()

    if not args.http:
        mcp.run()
        return

    # Stateless: clients reconnect freely across pm2 restarts without the
    # server having to remember a session that died with the old process.
    mcp.run(
        "streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
