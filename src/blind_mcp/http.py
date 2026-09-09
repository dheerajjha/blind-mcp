"""Polite HTTP layer for teamblind.com.

Three things happen here and nowhere else: robots.txt is enforced, responses are
cached on disk, and requests are spaced out. Everything above this module can
assume a fetch is cheap and allowed.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import httpx

BASE = "https://www.teamblind.com"
VERSION = "0.1.0"

USER_AGENT = os.environ.get(
    "BLIND_MCP_USER_AGENT",
    f"blind-mcp/{VERSION} (+https://github.com/dheerajjha/blind-mcp)",
)
CACHE_DIR = Path(
    os.environ.get("BLIND_MCP_CACHE_DIR", Path.home() / ".cache" / "blind-mcp")
)
CACHE_TTL = int(os.environ.get("BLIND_MCP_CACHE_TTL", 6 * 3600))
MIN_INTERVAL = float(os.environ.get("BLIND_MCP_MIN_INTERVAL", "1.5"))

# Opt-in only. Blind's bot detection reacts badly to automated authenticated
# traffic (it fires an "automatic logout, code 2009" and invalidates the
# session), and every read path this server uses works fine anonymously.
# See README "Do I need to log in?" before setting this.
SESSION_COOKIE = os.environ.get("BLIND_COOKIE", "").strip()


class RobotsDenied(RuntimeError):
    """Raised when robots.txt disallows the path. Not caught anywhere: a denied
    path is a bug in the caller, not a runtime condition to recover from."""


class _Throttle:
    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self._min:
                time.sleep(self._min - gap)
            self._last = time.monotonic()


_throttle = _Throttle(MIN_INTERVAL)
_robots: urllib.robotparser.RobotFileParser | None = None
_robots_lock = threading.Lock()


def _robots_parser() -> urllib.robotparser.RobotFileParser:
    global _robots
    with _robots_lock:
        if _robots is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{BASE}/robots.txt")
            try:
                with httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT}) as c:
                    rp.parse(c.get(f"{BASE}/robots.txt").text.splitlines())
            except httpx.HTTPError:
                # Unreachable robots.txt means we do not get to assume consent.
                rp.disallow_all = True
            _robots = rp
        return _robots


def allowed(url: str) -> bool:
    return _robots_parser().can_fetch(USER_AGENT, url)


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    host = urlparse(url).netloc.replace(":", "_")
    # Authenticated and anonymous responses must not share an entry, or setting
    # BLIND_COOKIE would silently replay logged-out HTML (and vice versa).
    scope = "auth" if SESSION_COOKIE else "anon"
    return CACHE_DIR / host / scope / f"{digest}.html"


def _purge_expired() -> int:
    """Remove cache entries older than CACHE_TTL.  Returns the number removed."""
    if not CACHE_DIR.exists():
        return 0
    cutoff = time.time() - CACHE_TTL
    removed = 0
    for path in CACHE_DIR.rglob("*.html"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def fetch(path_or_url: str, *, force: bool = False) -> str:
    """GET a Blind page, honouring robots.txt, the disk cache and the throttle."""
    _purge_expired()
    url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url

    if not allowed(url):
        raise RobotsDenied(
            f"robots.txt disallows {url}. Blind disallows /search/ for every "
            f"user-agent; use company topic pages or channels instead."
        )

    cached = _cache_path(url)
    if not force and cached.exists():
        if time.time() - cached.stat().st_mtime < CACHE_TTL:
            return cached.read_text(encoding="utf-8")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if SESSION_COOKIE:
        headers["Cookie"] = SESSION_COOKIE

    _throttle.wait()
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)

    if "/session-out" in str(resp.url):
        raise RuntimeError(
            "Blind invalidated the session (code 2009). Unset BLIND_COOKIE — "
            "every read path here works anonymously."
        )
    resp.raise_for_status()

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(resp.text, encoding="utf-8")
    return resp.text
