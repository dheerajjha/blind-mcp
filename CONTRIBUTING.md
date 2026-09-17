# Contributing

Three ways in, cheapest first: a **job-board adapter**, a **parser fix**, a
**new tool**. All are small — this is a ~600 line project.

**Read [#12](https://github.com/dheerajjha/payband-mcp/issues/12) first.** Blind
now 403s every non-browser User-Agent, so the Blind tools cannot reach the site.
We will not spoof a browser to get around it, and PRs doing so will be closed.
The pay tools read public job-board APIs and are unaffected — that is where the
useful work is right now.

**The standing principle behind everything below: a wrong answer is worse than
no answer.** People ask this server whether a company will let them work from
home, how long their parental leave is, whether a team is worth joining — and
then act on it. A thread that looks relevant but isn't costs someone a real
decision; returning nothing costs them one search. So `find` returns an empty
list rather than falling back to a generic listing, `research` would rather
surface two good threads than pad to four, and every comment keeps its
**employer tag and date**, because that is how a reader weighs an anonymous
claim. If you are ever choosing between "more results" and "results the user
can trust", pick trust.

**The second principle: stay welcome.** This server reads a site that does not
owe us access. It honours `robots.txt` and fails closed if it can't read it, it
caches for six hours, it throttles to ~1.5s, and it sends an honest User-Agent
instead of impersonating a browser. It has **no `/search/` tool**, because
Blind disallows that path for every user-agent. A PR that speeds things up by
weakening any of those will not be merged, however much faster it is. Bulk
crawling is out of scope permanently.

**On AI-assisted contributions.** Plenty of this repo was written with AI help,
including the maintainer's. That's fine and you don't need to disclose it. What
isn't optional: a human has read the change and can answer questions about it.
Reviews here lean on *running the thing* — a claim like "this improves ranking"
gets checked against real output before merge.

**Review promise:** first review within 48 hours. An alias merges as soon as it
has a passing test. No bikeshedding your regex.

## 1. Add a job-board adapter (an hour, and the most useful thing you can do)

`ats.fetch_postings` reads Greenhouse, Ashby, Lever, SmartRecruiters and
Workday. Self-hosted employers — Google, Atlassian, Canva and many Indian
employers — still raise `BoardNotFound`. Each adapter you add is a whole
category of employer the tool can suddenly answer for. See
[#13](https://github.com/dheerajjha/payband-mcp/issues/13) for the candidates
and the shape of the work.

Prefer boards with a **documented public API**. If a board only yields to
scraping, keep it clearly separate so its breakage cannot affect the API-backed
paths.

## 2. Add a keyword alias (10 minutes, no HTTP knowledge needed)

`research` turns a question into keywords and probes them against Blind's
company pages. It gets this wrong whenever a question uses different words than
Blind does — "work life balance" had to learn it means `wlb`.

Two dicts in [`src/payband_mcp/server.py`](src/payband_mcp/server.py):

- `_TOPIC_ALIASES` — maps a Blind topic to the words people actually use.
- `_LOW_SIGNAL` — words that are common in questions but useless as probes.
  `maternity` is a good probe; `policy` matches hundreds of loose threads.

Add your entry, add a line to `test_probe_terms_prefer_distinctive_words` in
[`tests/test_server.py`](tests/test_server.py), and open the PR. Include the
question you asked and what it returned before and after.

## 3. Fix a parser (an hour)

Blind ships three overlapping copies of every post — plain HTML, a schema.org
`DiscussionForumPosting`, and the Next.js RSC payload. We read the last two;
see [`src/payband_mcp/parse.py`](src/payband_mcp/parse.py).

Fixtures are **synthetic** — see
[`tests/fixtures/make_fixtures.py`](tests/fixtures/make_fixtures.py). Do not
commit captured pages. Blind posts are written by anonymous people and
routinely name colleagues; a real thread in this repo republishes that
permanently, and contradicts what we tell users not to do. Extend the generator
instead: it is plain Python and reproduces the structural quirks that matter
(replies that also match the comment regex, a `commentCount` higher than the
schema list, an AI `abstract`).

```bash
uv run python tests/fixtures/make_fixtures.py
uv run pytest -q
```

## 4. Add a tool (an afternoon)

Tools live in [`src/payband_mcp/server.py`](src/payband_mcp/server.py) as
`@mcp.tool()` functions. A tool earns its place if it answers a question the
existing four answer badly. Write the docstring for the model that will read
it: say when to use it, and say what an empty result means.

Every request must go through `http.fetch` — that is where robots, caching and
throttling live. A tool that calls `httpx` directly bypasses all three.

## Setup

```bash
uv sync
uv run pytest -q          # 12 tests, all offline
uv run payband-mcp          # stdio, for an MCP client
uv run payband-mcp --http   # HTTP on :8787, for pm2
```

Tests never touch the network. If you need to check something against the real
site, do it in a scratch script, not a test.
