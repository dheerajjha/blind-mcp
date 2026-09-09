# blind-mcp

[![tests](https://github.com/dheerajjha/blind-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/dheerajjha/blind-mcp/actions/workflows/test.yml)
[![good first issues](https://img.shields.io/github/issues/dheerajjha/blind-mcp/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/dheerajjha/blind-mcp/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Ask an anonymous professional network what it's actually like to work
somewhere — from your AI assistant.**

[Blind](https://www.teamblind.com) is where people say the things they won't put
on Glassdoor: whether the 4-day office policy is really enforced, what the
parental leave actually is, whether a team is worth joining. But its own search
is close to unusable — searching *"Roku India RTO"* returns twelve unrelated
referral posts — so the answers sit there unreachable.

This finds them.

```
research(company="Roku", question="how many days in office in India")

  → "Roku India - Reviews"  ·  2026-03-31
    AI summary: "...strictly enforced, with a mandatory four-day requirement,
                 though exceptions are possible at a manager's discretion"

    [Adobe]    "the wfo policy is enforced orgwide, you can take few times
                wfh based on managers discretion"
    [Carelon]  "Yes 4 days mandatory and its open culture"
```

Every comment keeps its **employer tag** and **date**, because that's how you
weigh an anonymous claim — an answer from someone at the company reads
differently from a passer-by, and a 2021 answer about policy may simply be
wrong now.

**No login. No API key.** Every read path works logged out.

## Tools

| Tool | What it does |
| --- | --- |
| `company_topics(company)` | The topics Blind itself suggests for a company — for Roku: `india`, `wlb`, `culture`, `layoffs`, `interview`, `rsu`, … |
| `company_posts(company, topic=, page=, limit=)` | Post listings, optionally scoped to one topic |
| `find(company, keyword, limit=, page=)` | Search a company's posts by keyword — `find("Intuit", "maternity")` returns exactly the 7 maternity threads |
| `read_post(url, max_comments=)` | One thread in full: body, Blind's AI summary, comments with employers |
| `research(company, question, max_posts=)` | One-shot: picks the topic, ranks its posts against the question, returns the top threads in full |

`find` fetches one page per call. Its `total_matches` covers all matches;
`posts` contains at most `limit` cards from the requested `page` (default 1).
Use `max_page` to discover further pages, e.g. `find("Intuit", "leave", page=2)`.
An empty later page is normal; stop paging. A small `limit` truncates that page,
so increase it to see the rest of its cards. `research` still probes only the
first page of each keyword and never walks pagination automatically.

## Install

```bash
uv sync
```

Register with Claude Code:

```bash
uv tool install --editable .          # puts `blind-mcp` on PATH
claude mcp add --scope user blind -- blind-mcp
```

Or in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blind": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/blind-mcp", "blind-mcp"]
    }
  }
}
```

## Do I need to log in?

**No — and you probably shouldn't.** This was measured, not assumed:

- Post bodies, full comment threads, Blind's AI comment summaries, company
  listings, topic pages, reviews and salary pages **all return HTTP 200
  anonymously**, with no gating.
- Driving an authenticated session with automation tripped Blind's anomaly
  detection after roughly six navigations: `Automatic Logout — we noticed a
  login from a new device or location (code 2009)`, with a redirect to
  `/session-out`.

So a cookie buys no extra read access and costs you session stability. The only
thing it would unlock is company-internal channels, which are gated to verified
employees of that company.

If you still want it, set `BLIND_COOKIE` to your session cookie header (copy it
from a logged-in browser request in DevTools). There is no login flow — the
server only replays a cookie you supply, read once at startup and attached to
each request. It is off by default, and the client raises immediately if Blind
invalidates it rather than silently returning logged-out HTML.

The cookie itself is never written to disk, but responses fetched with it are
cached under a separate `auth/` directory so authenticated and anonymous
results can never be served for each other. Don't commit the cookie.

## Being a good citizen

Blind's `robots.txt` disallows `/search/` for every user-agent, so **this server
has no search tool** and refuses to fetch that path. It also:

- sends an honest `User-Agent` (no browser impersonation — Blind serves it a 200 anyway)
- caches every response on disk for 6h, so repeat questions cost zero requests
- spaces requests ~1.5s apart
- fetches `robots.txt` first and fails closed if it can't be read

Configure via `BLIND_MCP_CACHE_DIR`, `BLIND_MCP_CACHE_TTL`,
`BLIND_MCP_MIN_INTERVAL`, `BLIND_MCP_USER_AGENT`.

Blind's Terms of Service restrict automated access. This reads public pages at
human pace for personal research; bulk crawling is both a ToS problem and, given
that Blind's value rests on anonymity, a privacy one. Don't build a dataset of
posts joined to employers and nicknames.

## Reading the output

Blind is anonymous and unverified. Weight claims by the commenter's employer
(`company` on each comment) and treat a single loud voice as one data point. In
testing, the Roku India RTO answer was corroborated by two independent
commenters *and* an unrelated Glassdoor review — that's when it's worth trusting.

## Contributing

Small project, easy to contribute to. The cheapest useful change is a **keyword
alias** — one dict entry plus a test — and it's the change that most improves
answers, because `research` only finds threads whose words match yours.

Start with [**good first issues**](.github/GOOD_FIRST_ISSUES.md) — nine open,
all real and reproduced, each one saying where the code is and how to test the
fix — then [CONTRIBUTING.md](CONTRIBUTING.md). Issues are labelled by size (`size: XS`
is under 30 minutes) and `mentored` means ask questions in the thread and
you'll get walked through it. First review within 48 hours.

Two hard rules, both explained in CONTRIBUTING: **don't commit captured Blind
pages** (fixtures are generated), and **don't weaken robots/cache/throttle** for
speed.

## Publishing

`mcp-name: io.github.dheerajjha/blind-mcp`

See [RELEASING.md](RELEASING.md).

## License

MIT
