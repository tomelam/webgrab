"""Is this endpoint still alive? -- answered by reading its newest observation.

Split deliberately in two:

  newest_observation() / verdict()  are PURE. They take text and return a date or
  a judgement, so 'how do I tell whether FRED is dead' is testable against a
  recorded response with no network involved.

  run() does the fetching.

That split is why the DSWP30 case -- a clean 200 carrying valid CSV that stopped
in 2016 -- can be a permanent unit test rather than something only a live run
would reveal.
"""
import datetime as dt
from dataclasses import dataclass

from . import freshness, http, parse

__all__ = ["ProbeError", "Verdict", "newest_observation", "verdict", "run"]


class ProbeError(RuntimeError):
    """The probe could not honestly judge this source."""


@dataclass
class Verdict:
    id: str
    ok: bool
    detail: str
    observed: dt.date | None = None
    age_days: int | None = None


def newest_observation(entry, text):
    """The newest observation date in `text`, or None when the source is static.

    Raises when the registry does not say where the date lives. Returning None in
    that case would make an unspecified source appear eternally fresh, which is
    the exact failure this module exists to catch.
    """
    spec = entry.newest_date
    if not spec:
        raise ProbeError(
            f"{entry.id}: no newest_date spec in the registry, so its liveness "
            f"cannot be judged. Add one, or mark the source static.")
    kind = spec.get("kind")
    if kind == "none":
        return None
    if kind == "csv_last_observation":
        date, _ = parse.csv_last_observation(text)
        return freshness.to_date(date)
    if kind == "json":
        return freshness.to_date(parse.dig(parse.json_body(text), spec["path"]))
    if kind == "hidden_input":
        d = parse.hidden_input_json(text, spec["input"])
        return freshness.to_date(parse.dig(d, spec["path"]))
    raise ProbeError(f"{entry.id}: unknown newest_date kind {kind!r}")


def verdict(entry, text, today=None):
    """Judge one fetched response."""
    today = today or dt.date.today()
    try:
        observed = newest_observation(entry, text)
    except (ProbeError, parse.ParseError, ValueError) as e:
        return Verdict(entry.id, False, f"unreadable: {e}")

    if observed is None:
        return Verdict(entry.id, True, "static source; no observation date applies")

    age = (today - observed).days
    if entry.max_age_days is None:
        return Verdict(entry.id, True, f"newest {observed.isoformat()} ({age} days); "
                                       f"no max_age_days declared", observed, age)
    try:
        freshness.assert_fresh(entry.as_source(), observed, today=today)
    except freshness.StaleError as e:
        return Verdict(entry.id, False, str(e), observed, age)
    return Verdict(entry.id, True, f"newest {observed.isoformat()} ({age} days old)",
                   observed, age)


def run(reg=None, today=None):
    """Fetch and judge every probeable source. Returns a list of Verdicts.

    Working sources that declare no probe params are reported as skipped, so an
    uncovered endpoint is visible rather than quietly absent from the results.
    """
    from . import registry
    reg = reg if reg is not None else registry.load()
    out = []
    for e in reg.values():
        if e.status != "works":
            continue
        if e.probe is None:
            out.append(Verdict(e.id, True, "SKIPPED: no probe params declared"))
            continue
        try:
            url = e.resolve(**e.probe)
            text = http.get(url, ua=e.user_agent, retries=e.retries)
        except Exception as ex:          # noqa: BLE001 -- report, never abort the sweep
            out.append(Verdict(e.id, False, f"fetch failed: {type(ex).__name__}: {ex}"))
            continue
        out.append(verdict(e, text, today=today))
    return out
