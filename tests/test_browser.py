"""The stealth-browser tier, behind the [browser] extra.

Playwright is not installed in the default dev environment, so most of this file
tests the parts that are PURE -- the in-page fetch JS, the crash dump, the
availability guard -- and leaves only the thin Playwright wiring uncovered.
That split is deliberate: the bugs that actually bite here (a URL breaking out
of a JS string, a crash dump that writes nothing) are in the pure parts.
"""
import json
import pytest
from webgrab import browser


class TestAvailability:
    def test_available_reports_the_truth_about_this_environment(self):
        try:
            import playwright  # noqa: F401
            expected = True
        except ImportError:
            expected = False
        assert browser.available() is expected

    def test_require_raises_with_an_install_hint_when_absent(self, monkeypatch):
        monkeypatch.setattr(browser, "available", lambda: False)
        with pytest.raises(browser.BrowserUnavailable) as e:
            browser.require_available()
        msg = str(e.value)
        assert "webgrab[browser]" in msg, "must say how to install it"
        assert "playwright install" in msg, "the browser binary is a separate step"


class TestInPageFetchJs:
    """Fetching from INSIDE the page is what makes a cleared anti-bot challenge
    usable: the session cookies ride along without ever being handled directly."""

    def test_includes_the_url_and_keeps_credentials(self):
        js = browser.fetch_js("https://x.test/api/data")
        assert "https://x.test/api/data" in js
        assert "same-origin" in js

    def test_a_url_containing_a_quote_cannot_break_out_of_the_js(self):
        """Injection guard. A naive f-string here lets a crafted URL execute
        arbitrary script in the page's origin -- with the very session cookies
        this module exists to make use of.

        The attack URL must contain a DOUBLE quote, because that is the
        delimiter of the JS string literal. An earlier version of this test used
        single quotes, for which json.dumps() and naive interpolation produce
        byte-identical output -- so it passed while guarding nothing, and only
        deliberately breaking the guard revealed it."""
        nasty = 'https://x.test/a"); alert("pwned"); //'
        js = browser.fetch_js(nasty)
        assert json.dumps(nasty) in js, "the URL must be JSON-encoded, not interpolated"
        # the raw, unescaped payload must not appear anywhere in the emitted JS
        assert 'a"); alert("pwned")' not in js

    def test_headers_are_embedded_as_json(self):
        js = browser.fetch_js("https://x.test/a", headers={"X-Requested-With": "XMLHttpRequest"})
        assert json.dumps({"X-Requested-With": "XMLHttpRequest"}) in js

    def test_no_headers_still_produces_valid_js(self):
        js = browser.fetch_js("https://x.test/a")
        assert "{}" in js or "headers" in js


class _StubPage:
    """Duck-typed stand-in for a Playwright Page, so the dump is testable."""

    def __init__(self, content="<html>body</html>", text="visible text"):
        self._content, self._text = content, text
        self.screenshot_path = None

    def content(self):
        return self._content

    def inner_text(self, _selector):
        return self._text

    def screenshot(self, path=None, **_):
        self.screenshot_path = path
        import pathlib
        pathlib.Path(path).write_bytes(b"\x89PNG fake")


class TestCrashDump:
    def test_writes_html_text_and_a_screenshot(self, tmp_path):
        """A failure that leaves no evidence cannot be diagnosed later, and the
        distinction that matters -- 'the UI changed' vs 'we were blocked' --
        is only visible in the picture."""
        page = _StubPage()
        written = browser.crash_dump(page, tmp_path, label="harvest-fail")
        names = sorted(p.name for p in tmp_path.iterdir())
        assert len(names) == 3
        assert any(n.endswith(".html") for n in names)
        assert any(n.endswith(".txt") for n in names)
        assert any(n.endswith(".png") for n in names)
        assert len(written) == 3

    def test_the_label_appears_in_the_filenames(self, tmp_path):
        browser.crash_dump(_StubPage(), tmp_path, label="blocked-on-page-3")
        assert all("blocked-on-page-3" in p.name for p in tmp_path.iterdir())

    def test_a_dump_never_raises_and_masks_the_original_failure(self, tmp_path):
        """A crash dump runs while something has ALREADY gone wrong. If it
        raises, it replaces the real traceback with its own and the actual
        failure is lost."""
        class Broken(_StubPage):
            def content(self):
                raise RuntimeError("page is gone")

        written = browser.crash_dump(Broken(), tmp_path, label="x")
        assert isinstance(written, list)   # degraded, but no exception escaped


class TestPacing:
    def test_jitter_stays_within_its_bounds(self):
        for _ in range(200):
            assert 1.5 <= browser.jitter(1.5, 4.0) <= 4.0

    def test_jitter_rejects_an_inverted_range(self):
        with pytest.raises(ValueError):
            browser.jitter(5.0, 1.0)
