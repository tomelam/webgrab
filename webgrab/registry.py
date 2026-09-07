"""The endpoint registry: one home for "which sites work and how each misbehaves".

This replaces knowledge that was spread across project prose, half a dozen local
reference notes, an agent skill definition, a hand-maintained JSON state file and
several tool permission allowlists -- none of which anything ever checked.
Two of those recorded claims turned out to be wrong the first time they were
tested, which is the argument for keeping them somewhere a command can re-verify.

The entries are data. `probe` is what makes `last_verified` more than a promise.
"""
import datetime as dt
import pathlib
import string
import tomllib
from dataclasses import dataclass, field

from . import freshness

__all__ = ["RegistryError", "Entry", "load", "probeable", "DEFAULT_PATH"]

DEFAULT_PATH = pathlib.Path(__file__).parent / "sources.toml"


class RegistryError(RuntimeError):
    """The registry was asked for something it cannot honestly provide."""


@dataclass
class Entry:
    id: str
    url: str = ""
    status: str = "unconfirmed"
    format: str = ""
    cadence: str = ""
    max_age_days: int | None = None
    user_agent: str = "default"
    retries: int = 2
    day_gated: bool = False
    probe: dict | None = None
    newest_date: dict | None = None
    notes: str = ""
    last_verified: dt.date | None = None
    newest_observation: dt.date | None = None
    extra: dict = field(default_factory=dict)

    def resolve(self, **params):
        """The URL with its template filled. Raises on a missing parameter rather
        than emitting a URL containing a literal '{series}'."""
        needed = {f for _, f, _, _ in string.Formatter().parse(self.url) if f}
        missing = sorted(needed - set(params))
        if missing:
            raise RegistryError(
                f"{self.id}: url needs {', '.join(missing)} -- refusing to build a "
                f"URL with an unfilled placeholder")
        return self.url.format(**params)

    def as_source(self):
        """A freshness.Source, when this entry has a cadence to be judged against.

        A source with no cadence (a static archive item) cannot be stale, and
        inventing a max_age_days for it would be a fabricated claim."""
        if not self.cadence or self.cadence == "static" or self.max_age_days is None:
            raise RegistryError(
                f"{self.id}: no cadence/max_age_days, so freshness is not defined for it")
        return freshness.Source(id=self.id, cadence=self.cadence,
                                max_age_days=self.max_age_days, day_gated=self.day_gated)


_FIELDS = {f for f in Entry.__dataclass_fields__ if f not in ("id", "extra")}


def load(path=None):
    """Read the registry into {id: Entry}."""
    p = pathlib.Path(path or DEFAULT_PATH)
    if not p.exists():
        raise RegistryError(f"registry not found at {p}")
    with p.open("rb") as fh:
        raw = tomllib.load(fh)
    sources = raw.get("sources")
    if not sources:
        raise RegistryError(f"{p} has no [sources] table")
    out = {}
    for sid, body in sources.items():
        known = {k: v for k, v in body.items() if k in _FIELDS}
        out[sid] = Entry(id=sid, extra={k: v for k, v in body.items() if k not in _FIELDS},
                         **known)
    return out


def probeable(reg=None):
    """Sources that `probe` can re-verify: working, and with probe params declared.

    A working source that declares no probe params is skipped rather than guessed
    at -- reported by the CLI, so the gap is visible instead of silently uncovered.
    """
    reg = reg if reg is not None else load()
    return [e for e in reg.values() if e.status == "works" and e.probe is not None]
