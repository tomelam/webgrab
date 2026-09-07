# webgrab

Shared web-wrangling for a collection of local data projects: fetching, freshness,
parsing, and a registry of endpoints that a command re-verifies.

    pip install webgrab              # fetching, freshness, parsing
    pip install webgrab[browser]     # adds Playwright, for sites that need a real browser

## Why this exists

Web fetching had been rebuilt from scratch in every project. One archived directory
held ten near-copies of a single RBI scraper. Another project independently reinvented
a weaker copy of a stealth-browser layer that already existed next door. Retry was
answered three different ways: ten immediate attempts in one place, none at all in
another, and correctly in a third. And the knowledge of which endpoints work sat in
prose across half a dozen files that nothing ever checked.

## The idea

**A clean HTTP 200 is not evidence of liveness.** FRED's `DSWP30` returns valid, parseable
CSV whose newest observation is 2016-10-28. Every other signal says the endpoint is
healthy. Only reading the observation date reveals it died a decade ago.

So the library separates three things that are easy to confuse:

| Question | Answered by |
|---|---|
| Is the output older than its local inputs? | `make` |
| Did the world move on? | `webgrab.freshness` |
| Did the run survive? | make sentinels and `.PRECIOUS` |

## Modules

| Module | For |
|---|---|
| `http` | One choke point for GET and POST. Timeout, backoff, per-source User-Agent policy, loud failure. `retries=0` for hosts that ban on bursts. |
| `freshness` | Cadence checks, day-gating, and stamp-vs-file cross-checks. |
| `parse` | `csv_last_observation`, `hidden_input_json`, `json_body`, `dig`. All pure. |
| `session` | Cookie-carrying sessions, and ASP.NET `__doPostBack` pagination. |
| `browser` | Stealth Chromium for sites a plain fetch cannot reach. `[browser]` extra. |
| `replay` | Record once, replay forever. |
| `registry` | `sources.toml` — what works, what is dead, and each site's trick. |
| `testing` | The pytest plugin that blocks unmocked network calls. |

### Three failure modes these guard against

**A postback that fails does not error — it re-serves the previous page.** Code that
de-duplicates results by id then finds nothing new and reports success, having read 1 page
of 17 and lost 94% of the data silently. `session.paginate_aspnet` raises on a
non-advancing page, and caps the walk regardless of what the page claims its record count is.

**A replay that falls back to the network is worse than no replay.** The suite passes in
CI while secretly hitting live hosts. A missing fixture raises, and the error says how to
record it.

**Fetching from inside the page needs the URL JSON-encoded, not interpolated.** A crafted
URL otherwise closes the JS string literal and runs arbitrary script in the page's origin —
with the session cookies that in-page fetching exists to make use of.

## Commands

    make test          offline suite; the network is blocked, not merely unused
    make test-network  opt-in live checks
    make probe         re-verify every working source; non-zero if any failed
    make list          every source and its status

## The registry

`webgrab/sources.toml` records **mechanics only** — never which instruments anyone holds.
A test enforces that boundary. Each entry says how to reach a source, what its User-Agent
policy is, how often it publishes, and what is known to go wrong with it.

`probe` is what makes `last_verified` more than a promise. Two claims inherited from prose
failed the first time they were tested: `sanskritdocuments.org` no longer returns the
documented 406, and a "polite" custom User-Agent turned out to be blocked by FRED.

## Testing

Two kinds, deliberately separated. **Offline tests** run parsers against responses recorded
from the live sites and catch our regressions; they are the default. **Network tests**
(`-m network`) assert the live sites still have the shape the fixtures recorded, and catch
the sites' changes.

Installing this library registers a pytest plugin that makes any unmocked network call in
an unmarked test an error. Consuming projects get that guard without copying a conftest.

Fixtures are evidence: recorded from the live site, never hand-edited. Refresh with
`webgrab record <id> --out <path>`.
