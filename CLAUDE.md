# webgrab — working rules for Claude

A shared library, so the rules that matter are in the code's own docstrings and in
`README.md`. Two things load above this file: `~/.claude/CLAUDE.md` (universal rules)
and `~/Projects/meta/pipeline-conventions.md` (the `make` conventions this project's
Makefile follows, including why `.PRECIOUS` and `.DELETE_ON_ERROR:` are both needed).

Specific to this repo:

- **This is the only repo here, besides PortfolioAnalyzer, with a PUBLIC remote.**
  github.com/tomelam/webgrab, MIT. Nothing private may enter it: `sources.toml`
  records how to talk to a site, never which instruments anyone holds. A test
  enforces that (`WEBGRAB_PRIVACY_CHECK_FILE`), and it is env-var driven precisely so
  the path to a private file is not published here.
- **Fixtures are evidence.** Recorded from live sites, never hand-edited. Refresh with
  `make record`; provenance is in `tests/fixtures/README.md`.
- **A clean HTTP 200 is not evidence of liveness.** FRED's `DSWP30` returns valid CSV
  whose newest observation is 2016-10-28. That case is a permanent test.
- **User-Agent is a per-source property, never a global default.** Measured: an
  unrecognised UA token is blocked outright by Akamai-fronted hosts, so the default is
  to send no override at all. Other hosts want the opposite.
- **Offline tests are the default; `-m network` is opt-in.** Offline tests catch our
  regressions, network tests catch the sites' changes.
