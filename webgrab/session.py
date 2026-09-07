"""Cookie-carrying sessions, and ASP.NET postback pagination.

Some sites -- government portals especially -- paginate by posting the whole
form back to itself: `__doPostBack('btnUpdate','')` reads a hidden page-number
field, and the server regenerates `__VIEWSTATE` on every response. Walking that
means GET page 1, then POST pages 2..N echoing the *newest* viewstate each hop,
on a session that carries the ASP.NET cookie.

Generalized from a solved implementation for RBI's SearchResults.aspx. Two guards
here are additions, because the original shape of this code fails silently:

  A RUNAWAY CAP. The page count is derived from a number scraped off the page.
  A regex that one day matches something large turns a polite walk into a
  hammering. `max_pages` bounds it unconditionally.

  NON-ADVANCING DETECTION. When a postback fails -- stale viewstate, dropped
  cookie -- ASP.NET does not return an error. It re-serves page 1. Code that
  de-duplicates results by id then finds nothing new and reports success, having
  read 1 page of 17 and lost 94% of the data without a word. Identical
  consecutive pages therefore raise.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from . import http

__all__ = ["SessionError", "new_session", "form_fields", "total_records",
           "page_count", "paginate_aspnet"]

DEFAULT_MAX_PAGES = 200


class SessionError(RuntimeError):
    """The walk could not be trusted to have seen every page."""


def new_session():
    """A requests.Session, which is what carries cookies across the walk."""
    return requests.Session()


def form_fields(html):
    """Every named `<input>`'s name -> value.

    This is what must be echoed back on a postback: `__VIEWSTATE`,
    `__EVENTVALIDATION`, `__VIEWSTATEGENERATOR`, the page-number field and any
    search inputs. Inputs with no `name` are skipped -- they are not submitted.
    """
    soup = BeautifulSoup(html, "html.parser")
    return {i.get("name"): i.get("value", "")
            for i in soup.find_all("input") if i.get("name")}


def total_records(html, pattern=r"([\d,]+)\s+Records"):
    """The result count the page prints, or 0 when it prints none.

    Tags are stripped first because the number and its label are usually in
    separate elements. 0 means "the page did not say", not "no results" -- the
    caller decides what to do with that, and `paginate_aspnet` treats it as a
    single page rather than guessing.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else 0


def page_count(records, page_size):
    """Pages needed for `records` at `page_size`, always at least 1."""
    if page_size <= 0:
        raise SessionError(f"page_size must be positive, got {page_size!r}")
    return max(1, -(-int(records) // int(page_size)))


def paginate_aspnet(url, *, page_size, session=None, page_field="hdnPageNo",
                    event_target="btnUpdate", total_override=None,
                    total_pattern=r"([\d,]+)\s+Records", max_pages=DEFAULT_MAX_PAGES,
                    throttle=0.25, ua="default", retries=2, _sleep=time.sleep):
    """Yield the HTML of every page of an ASP.NET postback-paginated result set.

    Yields page 1 from a GET, then each subsequent page from a POST that echoes
    the previous response's form fields with `page_field` bumped. The caller
    parses each page however it likes; this only guarantees it saw them all --
    or raises.

    `total_override` skips reading the count off the page, for callers that know
    it. `max_pages` is a hard bound regardless of what the page claims.
    """
    sess = session or new_session()
    first = http.get(url, session=sess, ua=ua, retries=retries)
    yield first

    records = total_records(first, total_pattern) if total_override is None else total_override
    pages = min(page_count(records, page_size), max_pages)

    fields = form_fields(first)
    previous = first
    for page in range(2, pages + 1):
        if throttle:
            _sleep(throttle)
        data = dict(fields)
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = ""
        data[page_field] = str(page)
        current = http.post(url, data=data, session=sess, ua=ua, retries=retries)

        if current == previous:
            raise SessionError(
                f"{url}: page {page} did not advance -- the response is byte-identical "
                f"to page {page - 1}. An ASP.NET postback that fails re-serves the "
                f"previous page instead of erroring, so continuing here would silently "
                f"read {page - 1} of {pages} pages and report success."
            )
        fields = form_fields(current)   # viewstate is regenerated per response
        previous = current
        yield current
