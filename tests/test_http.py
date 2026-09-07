"""Transport. The User-Agent tests encode a measured finding, not a preference."""
import pytest
import responses
from webgrab import http

URL = "https://example.test/data.csv"


class TestUserAgent:
    """These encode a MEASURED finding, repeated with controls on 2026-09-07
    against fred.stlouisfed.org, which sits behind Akamai Bot Manager (it sets
    _abck / bm_sz cookies):

        requests, no UA override        -> OK   0.3s, 208 KB
        requests, UA 'python-requests/x'-> OK   0.2s
        requests, UA 'curl/8.7.1'       -> OK   0.3s
        requests, UA 'webgrab/0.1'      -> FAIL 10s ReadTimeout  (twice)
        requests, UA 'webgrab/0.1 python-requests/2.34.2' -> FAIL (twice)
        any transport, UA Chrome        -> FAIL 15-20s

    So an UNRECOGNISED UA token is blocked, even appended to a recognised one,
    and a browser UA from a non-browser client is blocked too. The only safe
    default is to send no override and let the HTTP library name itself: honest,
    recognised, and nothing to maintain. A bespoke 'webgrab/0.1' UA -- which is
    what politeness would suggest -- silently breaks the single most-used
    endpoint in these projects.
    """

    @responses.activate
    def test_default_sends_no_override_so_the_library_names_itself(self):
        responses.add(responses.GET, URL, body="ok")
        http.get(URL)
        sent = responses.calls[0].request.headers["User-Agent"]
        assert sent.startswith("python-requests/")
        assert "webgrab" not in sent          # a custom token is what Akamai blocks
        assert "Mozilla" not in sent

    @responses.activate
    def test_browser_ua_is_available_but_must_be_asked_for(self):
        responses.add(responses.GET, URL, body="ok")
        http.get(URL, ua="browser")
        assert "Mozilla" in responses.calls[0].request.headers["User-Agent"]

    @responses.activate
    def test_ua_can_be_omitted_entirely(self):
        responses.add(responses.GET, URL, body="ok")
        http.get(URL, ua="none")
        assert "User-Agent" not in responses.calls[0].request.headers

    @responses.activate
    def test_an_explicit_literal_ua_is_passed_through(self):
        responses.add(responses.GET, URL, body="ok")
        http.get(URL, ua="curl/8.7.1")
        assert responses.calls[0].request.headers["User-Agent"] == "curl/8.7.1"


class TestRetry:
    @responses.activate
    def test_retries_a_transient_failure_then_succeeds(self):
        responses.add(responses.GET, URL, status=503)
        responses.add(responses.GET, URL, body="recovered")
        assert http.get(URL, retries=2, backoff=0) == "recovered"
        assert len(responses.calls) == 2

    @responses.activate
    def test_fails_loudly_once_retries_are_exhausted(self):
        for _ in range(3):
            responses.add(responses.GET, URL, status=503)
        with pytest.raises(http.FetchError) as e:
            http.get(URL, retries=2, backoff=0)
        assert "503" in str(e.value)

    @responses.activate
    def test_retries_zero_means_exactly_one_attempt(self):
        """Burst-sensitive hosts (niftyindices) must never be retried: bursts are
        what trip the block. The retry is the next scheduled run."""
        responses.add(responses.GET, URL, status=503)
        with pytest.raises(http.FetchError):
            http.get(URL, retries=0)
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_404_is_not_retried(self):
        """Retrying a definite answer wastes the host's time and ours."""
        responses.add(responses.GET, URL, status=404)
        with pytest.raises(http.FetchError):
            http.get(URL, retries=3, backoff=0)
        assert len(responses.calls) == 1


class TestFailureIsLoud:
    @responses.activate
    def test_an_empty_body_raises_rather_than_returning_nothing(self):
        """A 0-byte 200 is how archive.org downloads fail without -L, and an empty
        string parses as 'no rows' downstream instead of as an error."""
        responses.add(responses.GET, URL, body="")
        with pytest.raises(http.FetchError, match="empty"):
            http.get(URL)


class TestPost:
    """POST is needed for ASP.NET postback pagination, and must carry the same
    retry, UA and loud-failure semantics as GET rather than a parallel set."""

    @responses.activate
    def test_posts_form_data_and_returns_text(self):
        responses.add(responses.POST, URL, body="page2")
        assert http.post(URL, data={"hdnPageNo": "2"}) == "page2"
        assert "hdnPageNo=2" in responses.calls[0].request.body

    @responses.activate
    def test_shares_the_ua_policy_with_get(self):
        responses.add(responses.POST, URL, body="ok")
        http.post(URL, data={}, ua="browser")
        assert "Mozilla" in responses.calls[0].request.headers["User-Agent"]

    @responses.activate
    def test_retries_transient_failures_like_get(self):
        responses.add(responses.POST, URL, status=503)
        responses.add(responses.POST, URL, body="recovered")
        assert http.post(URL, data={}, retries=2, backoff=0) == "recovered"

    @responses.activate
    def test_fails_loudly(self):
        responses.add(responses.POST, URL, status=500)
        with pytest.raises(http.FetchError):
            http.post(URL, data={}, retries=0)


class TestSessionCompatibility:
    """A session need only quack like `requests`: `.get()` / `.post()`.

    Real code injects `requests.Session`, but test doubles across projects
    implement just the verb methods. Calling `session.request(method, ...)`
    would reject every such double, and the library would be the awkward one.
    """

    @responses.activate
    def test_a_duck_typed_session_with_only_get_is_accepted(self):
        calls = []

        class OnlyGet:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                class R:
                    status_code = 200
                    text = "canned"
                return R()

        assert http.get(URL, session=OnlyGet()) == "canned"
        assert calls[0][0] == URL
        assert "timeout" in calls[0][1] and "headers" in calls[0][1]

    @responses.activate
    def test_a_duck_typed_session_with_only_post_is_accepted(self):
        class OnlyPost:
            def post(self, url, **kwargs):
                class R:
                    status_code = 200
                    text = "posted"
                return R()

        assert http.post(URL, data={"a": "1"}, session=OnlyPost()) == "posted"

    @responses.activate
    def test_a_real_requests_session_still_works(self):
        import requests as _rq
        responses.add(responses.GET, URL, body="ok")
        with _rq.Session() as s:
            assert http.get(URL, session=s) == "ok"
