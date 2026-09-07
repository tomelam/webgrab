"""Cookie-carrying sessions and ASP.NET postback pagination.

Generalized from a solved implementation for RBI's SearchResults.aspx. Two
government sites in this collection paginate this way, and the pattern is
otherwise rediscovered from scratch every time.

Two guards here are NEW, and exist because the original could fail silently:

  A RUNAWAY CAP. Page count is derived from a number scraped off the page. If
  that regex ever matches something large, the loop hammers the host. max_pages
  bounds it.

  NON-ADVANCING DETECTION. When an ASP.NET postback fails -- a stale viewstate,
  a dropped cookie -- the server does not error. It re-serves page 1. Code that
  de-duplicates results by id then collects nothing new and reports success,
  having silently read 1 page of 17. Identical consecutive pages must raise.
"""
import pytest
import responses
from webgrab import session

URL = "https://gov.test/SearchResults.aspx"


def _page(n, viewstate, extra=""):
    """A minimal ASP.NET page carrying a per-page viewstate."""
    return (f'<html><form>'
            f'<input type="hidden" name="__VIEWSTATE" value="{viewstate}" />'
            f'<input type="hidden" name="__EVENTVALIDATION" value="ev{n}" />'
            f'<input type="hidden" name="hdnPageNo" value="{n}" />'
            f'<input type="text" name="ddlFunction" value="search" />'
            f'<input type="submit" value="unnamed input has no name attr" />'
            f'<span>231 Records</span>{extra}'
            f'<div>page-body-{n}</div></form></html>')


class TestFormFields:
    def test_extracts_the_named_inputs_from_a_real_rbi_page(self, fx):
        f = session.form_fields(fx("rbi_search_page1.html"))
        assert "__VIEWSTATE" in f and f["__VIEWSTATE"]
        assert "__EVENTVALIDATION" in f
        assert f["hdnPageNo"] == "1"
        assert len(f) > 10

    def test_skips_inputs_with_no_name(self):
        f = session.form_fields(_page(1, "vs1"))
        assert None not in f
        assert set(f) == {"__VIEWSTATE", "__EVENTVALIDATION", "hdnPageNo", "ddlFunction"}


class TestTotalRecords:
    def test_reads_the_count_off_a_real_rbi_page(self, fx):
        assert session.total_records(fx("rbi_search_page1.html")) == 231

    def test_strips_thousands_commas(self):
        assert session.total_records("<b>1,234</b> Records") == 1234

    def test_absent_count_is_zero_not_a_guess(self):
        assert session.total_records("<html>nothing here</html>") == 0

    def test_page_count_rounds_up(self):
        assert session.page_count(231, 14) == 17     # ceil(231/14)
        assert session.page_count(28, 14) == 2
        assert session.page_count(0, 14) == 1        # always at least page 1
        assert session.page_count(1, 14) == 1


class TestPaginateAspnet:
    @responses.activate
    def test_yields_every_page_and_posts_the_postback_fields(self):
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        for n in (2, 3):
            responses.add(responses.POST, URL, body=_page(n, f"vs{n}"))

        pages = list(session.paginate_aspnet(URL, page_size=14, total_override=42, throttle=0))
        assert len(pages) == 3
        assert "page-body-3" in pages[2]

        first_post = responses.calls[1].request.body
        assert "__EVENTTARGET=btnUpdate" in first_post
        assert "hdnPageNo=2" in first_post

    @responses.activate
    def test_viewstate_is_refreshed_from_each_response(self):
        """ASP.NET regenerates __VIEWSTATE per response. Echoing a stale one
        silently re-serves page 1, so each hop must read the newest."""
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        responses.add(responses.POST, URL, body=_page(2, "vs2"))
        responses.add(responses.POST, URL, body=_page(3, "vs3"))

        list(session.paginate_aspnet(URL, page_size=14, total_override=42, throttle=0))
        assert "__VIEWSTATE=vs1" in responses.calls[1].request.body   # page 2 uses page 1's
        assert "__VIEWSTATE=vs2" in responses.calls[2].request.body   # page 3 uses page 2's

    @responses.activate
    def test_a_non_advancing_page_raises_instead_of_looping_quietly(self):
        """A failed postback re-serves the SAME page. Silently collecting it
        again is how a 17-page walk reports success having read one page."""
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        responses.add(responses.POST, URL, body=_page(1, "vs1"))      # identical: postback failed

        with pytest.raises(session.SessionError, match="did not advance"):
            list(session.paginate_aspnet(URL, page_size=14, total_override=42, throttle=0))

    @responses.activate
    def test_max_pages_bounds_a_runaway_record_count(self):
        """The page count comes from a number scraped off the page. If that is
        ever wrong, the cap is what stops us hammering the host."""
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        for n in range(2, 12):
            responses.add(responses.POST, URL, body=_page(n, f"vs{n}"))

        pages = list(session.paginate_aspnet(
            URL, page_size=14, total_override=10_000_000, max_pages=4, throttle=0))
        assert len(pages) == 4, "must stop at the cap, not at the claimed page count"

    @responses.activate
    def test_throttles_between_pages(self):
        """Politeness is not optional on a government site."""
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        responses.add(responses.POST, URL, body=_page(2, "vs2"))
        slept = []
        pages = list(session.paginate_aspnet(URL, page_size=14, total_override=28,
                                             throttle=0.25, _sleep=slept.append))
        assert len(pages) == 2
        assert slept == [0.25], "one pause per postback"

    @responses.activate
    def test_a_single_page_result_makes_no_post_at_all(self):
        responses.add(responses.GET, URL, body=_page(1, "vs1"))
        pages = list(session.paginate_aspnet(URL, page_size=14, total_override=5, throttle=0))
        assert len(pages) == 1
        assert len(responses.calls) == 1, "no postback when there is only one page"

    @responses.activate
    def test_cookies_persist_across_the_walk(self):
        """A persistent session is what carries the ASP.NET session cookie; a
        fresh connection per page loses it and every postback fails."""
        responses.add(responses.GET, URL, body=_page(1, "vs1"),
                      headers={"Set-Cookie": "ASP.NET_SessionId=abc123; Path=/"})
        responses.add(responses.POST, URL, body=_page(2, "vs2"))
        list(session.paginate_aspnet(URL, page_size=14, total_override=28, throttle=0))
        assert "ASP.NET_SessionId=abc123" in responses.calls[1].request.headers.get("Cookie", "")


class TestFirstPageSupplied:
    """A caller often already holds page 1 -- fetched through its own seam, or
    read from a recorded fixture. Forcing paginate_aspnet to re-fetch it would
    break that seam and make offline replay impossible."""

    @responses.activate
    def test_a_supplied_first_page_is_used_and_not_refetched(self):
        responses.add(responses.POST, URL, body=_page(2, "vs2"))
        pages = list(session.paginate_aspnet(
            URL, page_size=14, total_override=28, throttle=0,
            first_page=_page(1, "vs1")))
        assert len(pages) == 2
        assert "page-body-1" in pages[0]
        assert all(c.request.method == "POST" for c in responses.calls), \
            "no GET should be issued when page 1 is supplied"

    @responses.activate
    def test_the_supplied_page_still_provides_the_viewstate(self):
        responses.add(responses.POST, URL, body=_page(2, "vs2"))
        list(session.paginate_aspnet(URL, page_size=14, total_override=28,
                                     throttle=0, first_page=_page(1, "vs-from-caller")))
        assert "__VIEWSTATE=vs-from-caller" in responses.calls[0].request.body

    @responses.activate
    def test_the_record_count_is_read_from_the_supplied_page(self):
        """231 Records at 14 per page is 17 pages, capped here at 3."""
        for n in range(2, 5):
            responses.add(responses.POST, URL, body=_page(n, f"vs{n}"))
        pages = list(session.paginate_aspnet(
            URL, page_size=14, throttle=0, max_pages=3, first_page=_page(1, "vs1")))
        assert len(pages) == 3

    def test_a_single_page_supplied_needs_no_network_at_all(self):
        """No responses.activate and no mock: the autouse guard fails this test
        if it touches the network. This is what makes offline replay work."""
        pages = list(session.paginate_aspnet(
            URL, page_size=14, total_override=5, throttle=0,
            first_page=_page(1, "vs1")))
        assert len(pages) == 1
