"""Record once, replay forever.

The convention comes from a `replay_from` / `save_replay` pair already proven in
a sibling project: the same code path that records a fixture is the one that
later replays it, so fixtures are regenerable rather than hand-curated and
refreshing one after a site change is a single command.

The load-bearing rule: IN REPLAY MODE, A MISSING FIXTURE RAISES. It must never
fall back to the network. A suite that quietly goes live when a fixture is
absent is non-deterministic, passes in CI while lying about what it exercised,
and hits the host from places that should never touch it.
"""
import pytest
import responses
from webgrab import replay

URL = "https://example.test/data.csv?id=DGS10"


class TestKeys:
    def test_a_key_is_filesystem_safe(self):
        k = replay.key_for("https://example.test/a/b?x=1&y=2")
        assert "/" not in k and "?" not in k and "&" not in k and "=" not in k

    def test_query_parameters_change_the_key(self):
        """Two FRED series differ only in the query string. Collapsing them
        would replay one series' data for another -- silently wrong numbers."""
        a = replay.key_for("https://fred.test/g.csv?id=DGS10")
        b = replay.key_for("https://fred.test/g.csv?id=DGS30")
        assert a != b

    def test_the_key_is_stable_across_calls(self):
        assert replay.key_for(URL) == replay.key_for(URL)

    def test_the_key_is_recognisable_not_just_a_hash(self):
        """A directory of bare hashes is unreadable when a fixture needs checking."""
        assert "data" in replay.key_for(URL)


class TestRecord:
    @responses.activate
    def test_records_to_disk_and_returns_the_body(self, tmp_path):
        responses.add(responses.GET, URL, body="col\n1\n")
        r = replay.Replay(tmp_path, mode="record")
        assert r.get(URL) == "col\n1\n"
        written = list(tmp_path.iterdir())
        assert len(written) == 1
        assert written[0].read_text() == "col\n1\n"

    @responses.activate
    def test_recording_twice_refreshes_rather_than_duplicating(self, tmp_path):
        responses.add(responses.GET, URL, body="v1")
        responses.add(responses.GET, URL, body="v2")
        r = replay.Replay(tmp_path, mode="record")
        r.get(URL)
        r.get(URL)
        files = list(tmp_path.iterdir())
        assert len(files) == 1 and files[0].read_text() == "v2"


class TestReplay:
    def test_replays_from_disk_without_touching_the_network(self, tmp_path):
        """No responses.activate and no mock: if this reached the network at all,
        the autouse guard in webgrab.testing would fail the test."""
        rec = replay.Replay(tmp_path, mode="record")
        (tmp_path / replay.key_for(URL)).write_text("recorded body")
        r = replay.Replay(tmp_path, mode="replay")
        assert r.get(URL) == "recorded body"

    def test_a_missing_fixture_raises_and_never_falls_back_to_the_network(self, tmp_path):
        """THE guard. A silent fallback here makes a suite that passes while
        secretly hitting live hosts, and that stops being reproducible."""
        r = replay.Replay(tmp_path, mode="replay")
        with pytest.raises(replay.ReplayError) as e:
            r.get(URL)
        msg = str(e.value)
        assert "no recorded fixture" in msg
        assert "record" in msg, "the error must say how to fix it"

    def test_replay_is_byte_exact(self, tmp_path):
        body = 'weird\r\nline\tendings and "quotes" & ₹ unicode\n'
        (tmp_path / replay.key_for(URL)).write_bytes(body.encode("utf-8"))
        r = replay.Replay(tmp_path, mode="replay")
        assert r.get(URL) == body


class TestModes:
    def test_an_unknown_mode_raises_rather_than_defaulting(self, tmp_path):
        with pytest.raises(replay.ReplayError, match="mode"):
            replay.Replay(tmp_path, mode="whatever")

    @responses.activate
    def test_live_mode_neither_reads_nor_writes_fixtures(self, tmp_path):
        responses.add(responses.GET, URL, body="fresh")
        r = replay.Replay(tmp_path, mode="live")
        assert r.get(URL) == "fresh"
        assert list(tmp_path.iterdir()) == []
