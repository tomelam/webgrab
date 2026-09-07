"""The stealth-browser tier, for sites a plain fetch cannot reach.

Needs the optional extra:  pip install 'webgrab[browser]' && playwright install chromium

Some hosts cannot be fetched with an HTTP client at any User-Agent: an ASP.NET
session plus a server-affinity cookie wall, or a Cloudflare challenge that must
actually execute. For those, drive a real browser, clear the challenge ONCE, and
then fetch every endpoint you need from INSIDE the page -- so the session
cookies ride along without ever being handled directly. Clearing a challenge is
slow; amortizing one clearance across several endpoints is the whole trick.

Two habits carried over from a long-running harvester, because both were learned
the hard way:

  PACE LIKE A PERSON, and treat a burst as the thing that gets you blocked. The
  retry for a blocked host is the next scheduled run, not another request now.

  DUMP EVIDENCE ON FAILURE -- HTML, visible text, and a screenshot. The question
  after a failure is always "did the UI change, or were we blocked?", and only
  the picture answers it.
"""
import contextlib
import datetime as dt
import json
import pathlib
import random

__all__ = ["BrowserUnavailable", "available", "require_available", "fetch_js",
           "crash_dump", "jitter", "session"]

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_LOCALE = "en-IN"
DEFAULT_TIMEZONE = "Asia/Kolkata"


class BrowserUnavailable(RuntimeError):
    """The browser extra is not installed."""


def available():
    """True when the optional browser dependencies are importable."""
    try:
        import playwright.sync_api  # noqa: F401
        import playwright_stealth  # noqa: F401
    except ImportError:
        return False
    return True


def require_available():
    """Raise a message that says how to fix it, rather than an ImportError."""
    if not available():
        raise BrowserUnavailable(
            "this needs the browser extra, which is not installed.\n"
            "  pip install 'webgrab[browser]'\n"
            "  playwright install chromium\n"
            "The browser binary is a separate download from the Python package."
        )


def jitter(low, high):
    """A random pause in [low, high]. Mechanical timing is itself a signal."""
    if high < low:
        raise ValueError(f"jitter range is inverted: {low} > {high}")
    return random.uniform(low, high)


def fetch_js(url, headers=None, timeout_ms=30000, method="GET", body=None):
    """JavaScript that fetches `url` from inside the page and returns its text.

    Supports an in-page POST with a body, which some endpoints require: a
    GET-only helper cannot reach, for instance, a TRI history endpoint that takes
    its query as a JSON body.

    URL, headers and body are all JSON-encoded, never interpolated. A naive
    f-string lets crafted content close the string literal and run arbitrary
    script in the page's own origin -- with the session cookies this function
    exists to make use of. The body matters most here: it carries user-shaped
    input far more often than the URL does. A dict body is serialised to JSON.
    """
    if body is not None and not isinstance(body, str):
        body = json.dumps(body)
    body_line = f"body: {json.dumps(body)}," if body is not None else ""
    return f"""
    async () => {{
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), {int(timeout_ms)});
        try {{
            const r = await fetch({json.dumps(url)}, {{
                method: {json.dumps(method)},
                credentials: 'same-origin',
                headers: {json.dumps(headers or {})},
                {body_line}
                signal: ctl.signal
            }});
            return await r.text();
        }} finally {{ clearTimeout(t); }}
    }}
    """


def crash_dump(page, directory, label="failure"):
    """Write HTML, visible text and a screenshot. Returns the paths written.

    NEVER raises. This runs when something has already gone wrong; an exception
    here would replace the real traceback with its own and lose the actual
    failure. Each artefact is attempted independently, so a page too broken to
    screenshot still yields its HTML.
    """
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = directory / f"{label}-{stamp}"
    written = []

    for suffix, getter in (
        (".html", lambda: page.content()),
        (".txt", lambda: page.inner_text("body")),
    ):
        with contextlib.suppress(Exception):
            path = stem.with_suffix(suffix)
            path.write_text(getter(), errors="replace")
            written.append(path)

    with contextlib.suppress(Exception):
        path = stem.with_suffix(".png")
        page.screenshot(path=str(path), full_page=True)
        written.append(path)

    return written


@contextlib.contextmanager
def session(url, *, headless=True, timeout=45000, settle=(3.0, 5.0),
            user_agent=DEFAULT_UA, viewport=None, locale=DEFAULT_LOCALE,
            timezone=DEFAULT_TIMEZONE):
    """Yield a page that has already loaded `url` and settled.

    Clearing an anti-bot challenge is the expensive part, so do it once here and
    reuse the yielded page for every endpoint you need -- calling `fetch_js`
    against each -- instead of paying for a fresh clearance per request.
    """
    require_available()
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    with Stealth().use_sync(sync_playwright()) as p:
        browser_ = p.chromium.launch(headless=headless)
        try:
            ctx = browser_.new_context(
                user_agent=user_agent,
                viewport=viewport or DEFAULT_VIEWPORT,
                locale=locale,
                timezone_id=timezone,
            )
            page = ctx.new_page()
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(int(jitter(*settle) * 1000))
            yield page
        finally:
            browser_.close()
