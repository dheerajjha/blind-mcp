# Releasing

Two steps, in order. The second depends on the first.

## 1. PyPI

Publishing is not a manual step. Pushing a `v*` tag runs
[`release.yml`](.github/workflows/release.yml), which publishes to PyPI over
Trusted Publishing — GitHub's OIDC identity, no API token stored anywhere.
The job refuses to publish unless the tests pass **and** the tag matches the
version in the package, so a mistyped tag fails loudly rather than shipping
the wrong thing.

```bash
git tag v0.4.0
git push origin v0.4.0
gh run watch          # or: gh run list --workflow=release.yml
```

Bump `version` in **three** places or the registry will reject the submission:
`pyproject.toml`, `src/payband_mcp/__init__.py`, and `server.json` (twice — the
top-level `version` and `packages[0].version`). See
[#7](https://github.com/dheerajjha/payband-mcp/issues/7) — the version is
currently duplicated rather than derived, which is exactly the kind of thing
that goes stale.

## 2. The official MCP registry

**Automatic.** [`release-registry.yml`](.github/workflows/release-registry.yml)
runs after the PyPI workflow succeeds and publishes `server.json` over GitHub
Actions OIDC. Nothing to run, and no token stored — the namespace
`io.github.dheerajjha/*` is proved by the OIDC claim naming this repository's
owner.

It waits for PyPI rather than running on the tag, because the registry checks
that the package in `server.json` actually exists. Re-running a green release
is safe: an already-published version is treated as done rather than as a
failure.

If you ever need to do it by hand, the two commands **must be chained**:

```bash
mcp-publisher login github && mcp-publisher publish
```

The registry's JWT lives five minutes. Running them as separate steps means
logging in, reading the device code, clicking authorize, and publishing all
inside that window — which is how three attempts died on
`token is expired` before this was automated.

## 3. Where else to list it

Not automated, and each wants a PR to someone else's repo:

- [`punkpeye/awesome-mcp-servers`](https://github.com/punkpeye/awesome-mcp-servers)
- [`modelcontextprotocol/servers`](https://github.com/modelcontextprotocol/servers) — community list
- [Glama](https://glama.ai/mcp/servers) and [Smithery](https://smithery.ai) — both index public GitHub repos, often without a submission
