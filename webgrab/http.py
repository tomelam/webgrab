"""One choke point for every HTTP GET, so behaviour is uniform and mockable.

THE USER-AGENT DEFAULT ENCODES A MEASUREMENT, NOT A TASTE. Verified 2026-09-07
against fred.stlouisfed.org, which sits behind Akamai Bot Manager, each result
repeated with controls:

    no UA override            OK   0.2-0.3s, 208 KB
    UA "python-requests/x"    OK
    UA "curl/8.7.1"           OK
    UA "webgrab/0.1"          FAIL 10s read timeout, twice
    UA "webgrab/0.1 python-requests/2.34.2"  FAIL, twice
    UA Chrome (any transport) FAIL 15-20s

An UNRECOGNISED UA token is blocked even when appended to a recognised one, and a
browser UA sent by a non-browser client is blocked as well. So the safe default is
to send no override at all and let the HTTP library name itself. Politeness would
suggest a bespoke "webgrab/0.1"; that silently breaks the most-used endpoint in
these projects, which is why this is measured rather than assumed. Hosts that
require the opposite (a browser UA) declare it per-source in sources.toml.

Failure is loud. Nothing here returns a default, a cached value, or an empty
string on error -- a plausible-looking wrong answer is the failure mode this
library exists to prevent.
"""
import requests
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential, RetryError)

__all__ = ["FetchError", "get", "post", "request", "USER_AGENTS"]

VERSION = "0.1"

# "default" is deliberately absent from this map: it means SEND NO OVERRIDE, so
# requests identifies itself as python-requests/x. See the module docstring --
# a bespoke "webgrab/0.1" token is blocked outright by Akamai-fronted hosts.
USER_AGENTS = {
    "browser": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "none": None,
}
TIMEOUT = 30

# Retrying these wastes the host's time and ours: the answer will not change.
NO_RETRY_STATUS = {400, 401, 403, 404, 405, 406, 410, 451}


class FetchError(RuntimeError):
    """The fetch did not produce a usable body. Always fatal."""


class _Transient(RuntimeError):
    """Internal: worth another attempt."""


def _headers(ua):
    """Header dict for a UA policy.

      "default"  -> {}                 let requests send python-requests/x
      "none"     -> {"UA": None}       suppress the header entirely; note that
                                       merely omitting the key does NOT do this,
                                       because requests injects its own
      "browser"  -> a Chrome string    opt-in spoofing, for hosts that demand it
      anything else -> used literally
    """
    if ua == "default":
        return {}
    value = USER_AGENTS[ua] if ua in USER_AGENTS else ua
    return {"User-Agent": value}


def request(method, url, *, ua="default", retries=2, backoff=1.0, timeout=TIMEOUT,
            session=None, allow_empty=False, **kwargs):
    """Fetch `url` and return its text, or raise FetchError.

    retries=0 means exactly one attempt. Use it for hosts that ban on bursts --
    niftyindices is the example; there the retry is the next scheduled run.
    """
    caller = session or requests
    headers = _headers(ua)
    headers.update(kwargs.pop("headers", None) or {})

    def _once():
        try:
            r = caller.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            raise _Transient(f"{url}: {type(e).__name__}: {e}") from e
        if r.status_code in NO_RETRY_STATUS:
            raise FetchError(f"{url} returned HTTP {r.status_code} (not retryable)")
        if r.status_code != 200:
            raise _Transient(f"{url} returned HTTP {r.status_code}")
        if not allow_empty and not r.text:
            raise FetchError(f"{url} returned HTTP 200 with an empty body")
        return r.text

    if retries <= 0:
        try:
            return _once()
        except _Transient as e:
            # Callers only ever see FetchError; _Transient is internal to the
            # retry decision and must not leak past this function.
            raise FetchError(f"{url} failed on its only attempt: {e}") from e

    runner = retry(
        stop=stop_after_attempt(retries + 1),
        wait=(wait_exponential(multiplier=backoff, min=backoff, max=30) if backoff
              else wait_exponential(multiplier=0, max=0)),
        retry=retry_if_exception_type(_Transient),
        reraise=False,
    )(_once)
    try:
        return runner()
    except RetryError as e:
        last = e.last_attempt.exception()
        raise FetchError(f"{url} failed after {retries + 1} attempts: {last}") from last


def get(url, **kwargs):
    """GET `url`, returning text. See request()."""
    return request("GET", url, **kwargs)


def post(url, data=None, **kwargs):
    """POST `data` to `url`, returning text.

    Needed for ASP.NET postback pagination, and deliberately routed through the
    same request() as GET so retry, User-Agent policy and loud failure cannot
    drift apart between the two verbs.
    """
    return request("POST", url, data=data, **kwargs)
