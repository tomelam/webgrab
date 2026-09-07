"""Is the data current? -- the question make cannot ask.

Make compares an output against its LOCAL inputs: rebuild if the script or the
config is newer. That is necessary and not sufficient. A file newer than every
local input can still hold a gold price from last week, because the thing that
moved is the world, not the filesystem. This module owns that second axis.

Three ideas, each generalized from PortfolioAnalyzer's loaders/data_update.py and
each protecting against a failure that looks exactly like success:

  A CLEAN 200 IS NOT LIVENESS. FRED's DSWP30 returns valid, parseable CSV whose
  newest observation is 2016-10-28. Code that checks only the status, or only that
  the body parsed, reports a decade-dead series as current.

  STAMP THE ATTEMPT BEFORE THE FETCH. Hosts that ban on bursts get one contact a
  day. If the stamp were written after a successful fetch, a raising fetch would
  leave the day unspent and the next run would hit the host again.

  DO NOT TRUST A STAMP THE FILE CONTRADICTS. A restored or reverted data file with
  a surviving stamp would otherwise be certified fresh on the strength of a fetch
  whose result is no longer on disk.
"""
import datetime as dt
import hashlib
import json
import pathlib
from dataclasses import dataclass

from . import parse

__all__ = ["Source", "StaleError", "age_days", "assert_fresh", "to_date", "Stamps"]


class StaleError(RuntimeError):
    """The data is older than its source's declared cadence allows. Always fatal."""


@dataclass(frozen=True)
class Source:
    id: str
    cadence: str            # business_day | month | continuous | static
    max_age_days: int
    day_gated: bool = False


def to_date(value):
    """A date from the several shapes these sites emit.

    ISO (FRED: 2026-08-28), DD-MM-YYYY (mfapi: 04-09-2026) and DD/MM/YYYY
    (IBJA: 04/09/2026). The 4-digit year's position disambiguates, so no guessing
    is involved; anything else raises rather than being coerced.
    """
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    if "T" in s:
        s = s.split("T", 1)[0]        # ISO datetime, e.g. gold-api's 2026-09-07T10:37:17Z
    for sep in ("-", "/"):
        if s.count(sep) == 2:
            a, b, c = s.split(sep)
            if len(a) == 4:
                return dt.date(int(a), int(b), int(c))
            if len(c) == 4:
                return dt.date(int(c), int(b), int(a))
            raise ValueError(
                f"ambiguous date {value!r}: no 4-digit year, so day/month/year "
                f"order cannot be determined without guessing")
    raise ValueError(f"unrecognised date {value!r}")


def age_days(observation_date, today=None):
    today = today or dt.date.today()
    return (today - to_date(observation_date)).days


def assert_fresh(source, observation_date, today=None):
    """Raise unless the newest observation is within the source's cadence.

    The message states the source, the date and the age in days. A staleness error
    that does not say how stale sends the reader back to the site to find out.
    """
    age = age_days(observation_date, today)
    if age > source.max_age_days:
        raise StaleError(
            f"{source.id}: newest observation is {to_date(observation_date).isoformat()}, "
            f"{age} days old; cadence '{source.cadence}' allows at most "
            f"{source.max_age_days}. A clean HTTP 200 is not evidence of liveness."
        )
    return age


def _digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Stamps:
    """A small JSON record of what was attempted and fetched, per source."""

    def __init__(self, path):
        self.path = pathlib.Path(path)

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.path)          # atomic: never a half-written stamp file

    def read(self, source):
        return self._read().get(source.id, {})

    def may_contact(self, source, today=None):
        """False only for a day-gated source already attempted today."""
        if not source.day_gated:
            return True
        today = today or dt.date.today()
        return self.read(source).get("attempted_at") != today.isoformat()

    def note_attempt(self, source, today=None):
        today = today or dt.date.today()
        d = self._read()
        d.setdefault(source.id, {})["attempted_at"] = today.isoformat()
        self._write(d)

    def note_success(self, source, last_date, path=None, rows=None):
        d = self._read()
        e = d.setdefault(source.id, {})
        e["fetched_at"] = dt.date.today().isoformat()
        e["last_date"] = to_date(last_date).isoformat()
        if rows is not None:
            e["rows"] = rows
        if path is not None:
            e["digest"] = _digest(path)
        self._write(d)

    def honoured(self, source, path):
        """Does the file on disk still hold what the stamp claims was fetched?

        Checked against the file's own newest observation where it is a CSV, and
        against a content digest otherwise. A missing file is never honoured.
        """
        e = self.read(source)
        p = pathlib.Path(path)
        if not e or not p.exists():
            return False
        try:
            actual, _ = parse.csv_last_observation(p.read_text(errors="replace"))
            return to_date(actual).isoformat() == e.get("last_date")
        except (parse.ParseError, ValueError):
            return "digest" in e and _digest(p) == e["digest"]

    def guarded_fetch(self, source, fetch, today=None):
        """Stamp the attempt, then fetch. The order is the point: a fetch that
        raises has still spent this source's one contact for today."""
        today = today or dt.date.today()
        if not self.may_contact(source, today):
            raise StaleError(
                f"{source.id}: already contacted today ({today.isoformat()}) and it is "
                f"day-gated. The retry is the next scheduled run, not now."
            )
        self.note_attempt(source, today)
        return fetch()
