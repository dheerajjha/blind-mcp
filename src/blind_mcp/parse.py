"""Parsers for Blind's server-rendered pages.

Blind is a Next.js app that ships three overlapping copies of every post: plain
HTML, a schema.org DiscussionForumPosting, and the React Server Component
payload. We read the last two. The schema block gives clean post metadata plus
Blind's own AI comment summary; the RSC payload is the only place the
commenter's employer appears, which is most of what makes a Blind comment worth
reading.
"""

from __future__ import annotations

import json
import re
from typing import Any

_RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)
_COMMENT_START = re.compile(r'\{"id":\d+,"parentCommentId":')
_CARD_SPLIT = re.compile(r'data-testid="article-preview-card"')
_TAG = re.compile(r"<[^>]+>")


def _decode_rsc(html: str) -> str:
    """Concatenate and unescape the RSC payload chunks."""
    parts = []
    for chunk in _RSC_CHUNK.findall(html):
        try:
            parts.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def _raw_decode_at(text: str, start: int) -> dict[str, Any] | None:
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _forum_posting(html: str) -> dict[str, Any] | None:
    marker = '"@type":"DiscussionForumPosting"'
    idx = html.find(marker)
    if idx == -1:
        return None
    # @context precedes @type, so the nearest preceding brace opens the object.
    return _raw_decode_at(html, html.rfind("{", 0, idx))


def _comment(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "author": node.get("memberNickname"),
        "company": node.get("companyName"),
        "date": node.get("writedAt") or node.get("createDate"),
        "likes": node.get("likeCnt", 0),
        "is_op": bool(node.get("isOp")),
        "text": node.get("contentRaw") or node.get("content") or "",
        "replies": [_comment(r) for r in node.get("recomments") or []],
    }


def parse_post(html: str) -> dict[str, Any]:
    """Full post: metadata, Blind's AI summary, and comments with employers."""
    dfp = _forum_posting(html) or {}
    rsc = _decode_rsc(html)

    # Every reply also matches _COMMENT_START on its own, so keep only roots
    # (parentCommentId == 0); replies stay nested under _comment().
    comments: list[dict[str, Any]] = []
    seen: set[int] = set()
    for match in _COMMENT_START.finditer(rsc):
        node = _raw_decode_at(rsc, match.start())
        if not node or node.get("id") in seen:
            continue
        seen.add(node["id"])
        if node.get("parentCommentId"):
            continue
        comments.append(_comment(node))

    if not comments:  # schema block is truncated but better than nothing
        comments = [
            {
                "author": (c.get("author") or {}).get("name"),
                "company": None,
                "date": c.get("datePublished", "")[:10],
                "likes": c.get("upvoteCount", 0),
                "is_op": False,
                "text": c.get("text", ""),
                "replies": [],
            }
            for c in dfp.get("comment") or []
        ]

    return {
        "title": dfp.get("headline"),
        "url": dfp.get("url"),
        "body": dfp.get("text"),
        "author": (dfp.get("author") or {}).get("name"),
        "published": (dfp.get("datePublished") or "")[:10],
        "likes": (dfp.get("interactionStatistic") or {}).get("userInteractionCount"),
        "comment_count": dfp.get("commentCount"),
        # Blind generates this itself from the full comment thread.
        "ai_summary": dfp.get("abstract"),
        "comments": comments,
    }


def _card(block: str) -> dict[str, Any] | None:
    href = re.search(r'href="(/post/[^"]+)"', block)
    title = re.search(r'<span class="sr-only">([^<]*)</span>', block)
    if not href:
        return None

    channel = re.search(r'href="/channels/([^"]+)"', block)
    tokens = [t for t in _TAG.sub("|", block).split("|") if t.strip()]
    counts = [t.replace(",", "") for t in tokens if re.fullmatch(r"[\d,]+", t.strip())]

    name = (title.group(1) if title else tokens[0] if tokens else "").strip()
    preview = max((t for t in tokens if t.strip() != name), key=len, default="").strip()

    return {
        "title": name,
        "url": "https://www.teamblind.com" + href.group(1),
        "channel": channel.group(1) if channel else None,
        "preview": preview[:400],
        "likes": int(counts[-3]) if len(counts) >= 3 else None,
        "comments": int(counts[-2]) if len(counts) >= 2 else None,
        "views": int(counts[-1]) if counts else None,
    }


def parse_listing(html: str) -> list[dict[str, Any]]:
    """Post cards from a company, channel or topic listing page."""
    blocks = _CARD_SPLIT.split(html)[1:]
    cards = (_card(b) for b in blocks)
    out, seen = [], set()
    for c in cards:
        if c and c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out


def parse_company_topics(html: str) -> dict[str, Any]:
    """Blind's own suggested topics for a company, plus the page count."""
    topics = sorted(set(re.findall(r'href="/company/[^/"]+/posts/([^"?]+)"', html)))
    pages = [int(p) for p in re.findall(
        r'href="/company/[^/"]+/posts(?:/[^/"?]+)?\?page=(\d+)"', html
    )]
    total = re.search(r'>([\d,]+)</span><span class="ml-1">Results', html)
    return {
        "topics": topics,
        "max_page": max(pages) if pages else 1,
        "total_results": int(total.group(1).replace(",", "")) if total else None,
    }
