# Good first issues

Real, reproduced, and currently open. Each issue says where the code is, what
the fix probably looks like, and how to test it. `mentored` means ask questions
in the thread and you'll get walked through it — that's the point, not a
formality.

Comment on the issue to claim it and it gets assigned to you, so two people
don't collide. That has already happened once.

> This list is short on purpose. It was previously eight issues, five of which
> were already fixed and closed, and the other three unrunnable. A list padded
> with work that cannot be done wastes the time of exactly the people it is
> trying to attract.

## Available now

| # | Size | What's wrong | Why it matters |
| --- | --- | --- | --- |
| [#18](https://github.com/dheerajjha/payband-mcp/issues/18) | S | Workday tenants are only found under the company's own name | Intuit, Dell, IBM and Sony are all on Workday and all unreachable. Mostly a **data** contribution: open a careers page, follow through to a job, read the tenant and site out of the URL. One company or twenty. |
| [#13](https://github.com/dheerajjha/payband-mcp/issues/13) | M | Most Indian-headquartered employers are unreachable | The highest-value work in the repo. Many run Darwinbox, Keka or Zoho Recruit — if one has a documented public posting API, a single adapter reaches a lot of employers at once, the way SmartRecruiters did. |

## Open, but wait

| # | Size | Status |
| --- | --- | --- |
| [#23](https://github.com/dheerajjha/payband-mcp/issues/23) | XS | Blocked on [#19](https://github.com/dheerajjha/payband-mcp/pull/19) landing — the signature you'd pass to changes with it |
| [#17](https://github.com/dheerajjha/payband-mcp/issues/17) | S | Claimed, with [#19](https://github.com/dheerajjha/payband-mcp/pull/19) in review |

## Open, but currently dormant

[#1](https://github.com/dheerajjha/payband-mcp/issues/1),
[#4](https://github.com/dheerajjha/payband-mcp/issues/4) and
[#5](https://github.com/dheerajjha/payband-mcp/issues/5) are in the Blind code
path. Blind has returned 403 to every non-browser request since around
September 2026 ([#12](https://github.com/dheerajjha/payband-mcp/issues/12)), so
those tools are no longer registered unless `PAYBAND_ENABLE_BLIND=1`.

They are still real bugs, still fixable and testable offline against the
synthetic fixtures, and still reviewed and merged on the same terms as anything
else. But your fix ships dormant, and you cannot check it against reality — if
the fixture and the real page disagree, the fixture wins and neither of us finds
out. Worth doing if the logic interests you; not if you want a change users feel
this month.

## Not on this list?

**A board we can't reach.** If the tool says `BoardNotFound` for an employer
you care about, that's the most useful thing you can report — especially
outside the US, since the whole premise is markets that publish nothing. Open a
[coverage gap issue](https://github.com/dheerajjha/payband-mcp/issues/new?template=coverage_gap.md).

**A band that's wrong.** A number that looks authoritative and isn't is the
worst failure this project has. If `pay_bands` reports something that
contradicts what you know from the inside, that is a bug and we want it.

## Setup

```bash
git clone https://github.com/dheerajjha/payband-mcp && cd payband-mcp
uv sync --dev
uv run pytest -q     # 94 tests, all offline, under a second
```

Tests never touch the network — mock at the adapter boundary. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the hard rules (fixtures are
generated, never captured; don't weaken robots/cache/throttle; no defeating an
access control).
