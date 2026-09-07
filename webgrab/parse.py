"""Pure text -> data. No I/O here, so every one of these is testable offline
against a recorded response, and none can be blamed on the network.

Each function raises ParseError rather than returning a default. A default is a
claim, and a wrong claim that looks like data is the failure mode this whole
library exists to prevent.
"""
import html as _html
import json
import re

__all__ = ["ParseError", "csv_last_observation", "hidden_input_json", "json_body", "dig"]


class ParseError(RuntimeError):
    """The response did not have the shape we expected. Always fatal."""


def csv_last_observation(text, missing=(".", "")):
    """The newest row carrying an actual number, as (date, float).

    This is NOT the last line of the file. FRED writes '.' for holidays and for
    the tail of a series that has stopped reporting, so the last line is often
    not an observation. Returning it would be a silent lie.

    Parsing succeeds for a discontinued series -- DSWP30 parses fine and reports
    2016-10-28. Deciding that 2016 is too old is freshness's job, not parsing's,
    and keeping them separate is what lets each be tested on its own.
    """
    rows = [r for r in text.splitlines() if "," in r]
    if len(rows) < 2:
        raise ParseError("csv carried no data rows below its header")
    for row in reversed(rows[1:]):
        date, _, value = row.partition(",")
        value = value.strip()
        if value not in missing:
            try:
                return date.strip(), float(value)
            except ValueError:
                raise ParseError(f"csv value {value!r} on {date!r} is not a number") from None
    raise ParseError(f"csv carried no numeric observation in {len(rows) - 1} rows")


def hidden_input_json(text, input_id):
    """JSON carried in a hidden form input's value attribute.

    Sites that render a chart server-side often ship the whole series this way.
    Reading it beats scraping the rendered spans: it is one parse instead of many,
    and it usually carries the publication date, which the display does not.

    Raises if the input is absent, because a page that changed shape must stop the
    run rather than yield a plausible subset.
    """
    m = re.search(rf'id="{re.escape(input_id)}"[^>]*value="([^"]*)"', text)
    if not m:
        raise ParseError(f"hidden input {input_id!r} not found -- page shape changed")
    try:
        return json.loads(_html.unescape(m.group(1)))
    except json.JSONDecodeError as e:
        raise ParseError(f"hidden input {input_id!r} is not JSON ({e})") from None


def json_body(text, require_nonempty=False):
    """Parse a JSON response.

    `require_nonempty` exists for hosts that answer 200 with an empty object for
    something that does not exist -- archive.org does this for an unknown item id,
    so an HTTP status check alone cannot tell you the item is missing.
    """
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"response is not JSON ({e})") from None
    if require_nonempty and not d:
        raise ParseError("response parsed to an empty object -- item probably does not exist")
    return d


def dig(obj, path):
    """Fetch a nested value by dotted path: "data.0.date", "labels.-1".

    Raises rather than returning None. A None here would flow onward as "this
    source has no observation date", and a source with no date is one that can
    never be judged stale -- turning a missing field into permanent false
    freshness. Integer-looking segments index sequences; everything else is a key.
    """
    cur = obj
    for seg in str(path).split("."):
        try:
            if isinstance(cur, (list, tuple)):
                cur = cur[int(seg)]
            else:
                cur = cur[seg]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ParseError(
                f"path {path!r} does not resolve: failed at {seg!r} "
                f"({type(e).__name__})") from None
    return cur
