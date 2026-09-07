"""Record once, replay forever.

The same code path records a fixture and later replays it, so fixtures are
regenerable rather than hand-curated: refreshing one after a site changes shape
is a single command, not an afternoon of copying HTML out of a browser.

Three modes:

    live     fetch, touch no fixtures
    record   fetch, and write the response to the fixture directory
    replay   read the fixture; NEVER fetch

That last rule is the load-bearing one. A replay that falls back to the network
when a fixture is missing produces a suite that passes in CI while silently
hitting live hosts -- non-deterministic, unreproducible, and impolite to the
host. So a missing fixture raises, and the error says how to record it.
"""
import hashlib
import pathlib
import re
import urllib.parse

from . import http

__all__ = ["ReplayError", "key_for", "Replay", "MODES"]

MODES = ("live", "record", "replay")


class ReplayError(RuntimeError):
    """A fixture was needed and not available, or the mode makes no sense."""


def key_for(url):
    """A stable, filesystem-safe fixture name for `url`.

    Deliberately readable rather than a bare hash: a directory of hex digests is
    useless when a fixture needs to be eyeballed. The digest suffix keeps two
    URLs that differ only in their query string apart -- FRED series differ by
    nothing else, and collapsing them would replay one series' numbers for
    another, which is silently wrong rather than loudly broken.
    """
    parts = urllib.parse.urlsplit(url)
    stem = pathlib.PurePosixPath(parts.path).name or parts.netloc
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:48].strip("._-") or "response"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}"


class Replay:
    """A fetcher that records to, or replays from, a fixture directory."""

    def __init__(self, directory, mode="replay"):
        if mode not in MODES:
            raise ReplayError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
        self.directory = pathlib.Path(directory)
        self.mode = mode

    def path_for(self, url):
        return self.directory / key_for(url)

    def get(self, url, **kwargs):
        """Fetch or replay `url`, returning text."""
        path = self.path_for(url)

        if self.mode == "replay":
            if not path.exists():
                raise ReplayError(
                    f"no recorded fixture for {url}\n"
                    f"  expected at: {path}\n"
                    f"  record it with: webgrab record <source-id> --out {path}\n"
                    f"Replay never falls back to the network: a suite that quietly "
                    f"goes live is not reproducible."
                )
            # Binary I/O on purpose: read_text/write_text apply universal-newline
            # translation, so a fixture recorded with CRLF would replay as LF. A
            # parser test would then pass against bytes that differ from the wire.
            return path.read_bytes().decode("utf-8", "replace")

        text = http.get(url, **kwargs)
        if self.mode == "record":
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return text
