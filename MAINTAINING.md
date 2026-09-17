# Maintaining this project

For whoever holds the keys. [CONTRIBUTING.md](CONTRIBUTING.md) is for people
sending patches; this is the part that only bites the person merging them.

## The one principle

**Being confidently wrong is worse than being narrow.**

Every serious bug this project has had was a number that looked authoritative
and was not. All four were the same bug wearing different clothes — *merging
things that are not the same thing*:

| What merged | What it produced | What fixed it |
| --- | --- | --- |
| Five jobs across one ladder | Databricks "forward deployed" as `140,400–320,200`, a figure nobody is offered | per-level bands |
| Two currencies, unconverted | GitLab's Polish band reading as ~2x the US one; it is 0.48x | `fx.py` |
| Checked and unchecked postings | 101 Cisco roles called "publishes no range" when 40 were looked at | `not_checked_count` |
| Three geographic zones | Atlassian's `Zone A/B/C` as one 1.6x range | prefix-label parsing |

So when reviewing: **ask what is being averaged together, and whether a real
person is offered the result.** `distinct_bands` vs `postings`, `precision`,
`basis` (base vs OTE) and `not_checked_count` all exist for this. They look
like clutter and they are not — each one is a bug that shipped.

## Lines not to cross

- **Never defeat an access control.** Blind 403s every non-browser request
  ([#12](https://github.com/dheerajjha/payband-mcp/issues/12)). No User-Agent
  spoofing, no proxy rotation, no headless browser. PRs doing this get closed,
  and that is stated publicly.
- **Documented public JSON APIs.** Anything that only yields to HTML scraping
  lives behind its own door (`selfhosted.py`) so its breakage cannot take the
  API-backed adapters with it.
- **No modelled or crowd-sourced numbers.** Every figure traces to a specific
  posting or it does not appear.
- **Fixtures are generated, never captured.** Real captures once contained a
  named individual and real post IDs. CI enforces this.
- **Tests never touch the network.** Mock at the adapter boundary.

## Traps that have already cost hours

- **PyPI's JSON index is heavily cached.** It served a stale version three
  times and twice looked like a failed release. Check
  `https://pypi.org/simple/payband-mcp/` or `/pypi/payband-mcp/0.7.0/json`.
- **The MCP registry JWT lives five minutes.** Four manual publishes died on
  `token is expired` in the gap between reading a device code and clicking
  authorize. It is automated now over OIDC; if you ever do it by hand, chain
  `mcp-publisher login github && mcp-publisher publish` as one command.
- **Fork PRs sit in `action_required`** and their CI will not run until
  approved. Two contributors were blocked on this without either of us
  noticing:
  ```bash
  gh api -X POST repos/dheerajjha/payband-mcp/actions/runs/<id>/approve
  ```
- **The version lives in three files** (`pyproject.toml`,
  `src/payband_mcp/__init__.py`, `server.json` twice). The release workflow
  fails loudly on a mismatch. That is deliberate.

## Reviewing

**Run the contribution, do not just read it.** Both adapters merged so far were
verified against live boards first, with the numbers quoted back in the review.
It catches real bugs — a location regex that looked fine matched the `on` in
`on-site` — and it shows the contributor their work was taken seriously.

**Fix your own breakage.** A rename here broke an open PR an hour after it was
filed. The right move was to rebase it onto the renamed tree and force-push to
the contributor's branch with their authorship intact, not to ask them to redo
it. `maintainer_can_modify` is usually true.

**Correct yourself in public.** A note in this repo once claimed the
SmartRecruiters API was dead, when in fact all seven company-id guesses had
been wrong. It nearly deterred the person who went on to write that adapter.
A wrong sentence in an issue costs more than a wrong line of code.

**Do not advertise work dishonestly.** Issues in the disabled Blind path were
labelled `good first issue` and `hacktoberfest`; they ship dormant and cannot
be checked against reality. They now carry `blind-disabled` and say so.

## Releasing

Fully automatic. `git tag vX.Y.Z && git push origin vX.Y.Z` runs the tests,
publishes to PyPI over Trusted Publishing, then publishes `server.json` to the
MCP registry over OIDC. No tokens stored anywhere. See
[RELEASING.md](RELEASING.md).
