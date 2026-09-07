"""Parsers, tested only against responses recorded from the live sites."""
import pytest
from webgrab import parse


class TestCsvLastObservation:
    def test_reads_newest_numeric_row(self, fx):
        date, value = parse.csv_last_observation(fx("fred_DEXINUS.csv"))
        assert date == "2026-08-28"
        assert value == pytest.approx(95.38)

    def test_skips_holiday_dot_rows(self, fx):
        """FRED writes '.' for holidays. The newest NUMERIC row is the answer,
        which is not always the last line of the file."""
        text = "observation_date,X\n2026-01-01,1.5\n2026-01-02,.\n2026-01-03,.\n"
        assert parse.csv_last_observation(text) == ("2026-01-01", 1.5)

    def test_dead_series_still_parses_and_reports_its_2016_date(self, fx):
        """DSWP30 returns a clean 200 with valid CSV. Parsing must SUCCEED and
        surface the stale date -- it is freshness, not parsing, that rejects it."""
        date, value = parse.csv_last_observation(fx("fred_DSWP30.csv"))
        assert date == "2016-10-28"
        assert value == pytest.approx(2.07)

    def test_raises_when_no_numeric_observation_exists(self):
        with pytest.raises(parse.ParseError):
            parse.csv_last_observation("observation_date,X\n2026-01-02,.\n")


class TestHiddenInputJson:
    def test_reads_ibja_gold_series(self, fx):
        d = parse.hidden_input_json(fx("ibjarates.html"), "HdnGold")
        assert len(d["labels"]) == 85
        assert d["labels"][-1] == "04/09/2026"

    def test_ibja_916_999_ratio_is_the_documented_value(self, fx):
        """0.91600 is the 22k ratio a downstream jewellery valuation depends on."""
        d = parse.hidden_input_json(fx("ibjarates.html"), "HdnGold")
        assert d["purity916"][-1] / d["purity999"][-1] == pytest.approx(0.916, abs=1e-5)

    def test_raises_when_the_page_shape_changes(self):
        with pytest.raises(parse.ParseError, match="not found"):
            parse.hidden_input_json("<html>redesigned</html>", "HdnGold")


class TestArchiveOrg:
    def test_real_item_exposes_filenames_that_differ_from_the_id(self, fx):
        """The documented trap: id 'ec-08-1904-b' -> file 'EC_08_1904_B.pdf'.
        Different case AND different separators, so never construct a filename."""
        d = parse.json_body(fx("archive_metadata_real.json"))
        names = [f["name"] for f in d["files"]]
        assert "EC_08_1904_B.pdf" in names
        assert "ec-08-1904-b.pdf" not in names

    def test_missing_item_returns_empty_object_not_404(self, fx):
        """archive.org answers 200 with {} for a non-existent id, so status codes
        cannot be trusted to detect a bad item."""
        with pytest.raises(parse.ParseError, match="empty"):
            parse.json_body(fx("archive_metadata_bogus_id.json"), require_nonempty=True)


class TestMfapi:
    def test_live_scheme_newest_nav(self, fx):
        d = parse.json_body(fx("mfapi_122639_live.json"))
        assert d["data"][0]["date"] == "04-09-2026"

    def test_dead_fund_parses_and_surfaces_its_2008_date(self, fx):
        """A dead fund is not a fetch failure. It parses; freshness rejects it."""
        d = parse.json_body(fx("mfapi_100027_dead.json"))
        assert d["data"][0]["date"] == "29-05-2008"


class TestDig:
    """Dotted-path access, so the registry can say WHERE a date lives as data."""

    def test_reads_a_nested_field(self):
        assert parse.dig({"a": {"b": "x"}}, "a.b") == "x"

    def test_reads_a_list_index(self, fx):
        d = parse.json_body(fx("mfapi_122639_live.json"))
        assert parse.dig(d, "data.0.date") == "04-09-2026"

    def test_reads_a_negative_index(self, fx):
        d = parse.hidden_input_json(fx("ibjarates.html"), "HdnGold")
        assert parse.dig(d, "labels.-1") == "04/09/2026"

    def test_a_wrong_path_raises_instead_of_returning_none(self):
        """Returning None would let a missing date read as 'no date', and a
        source with no date reads as one that never goes stale."""
        with pytest.raises(parse.ParseError, match="nope"):
            parse.dig({"a": 1}, "nope.deeper")

    def test_an_out_of_range_index_raises(self):
        with pytest.raises(parse.ParseError):
            parse.dig({"data": []}, "data.0.date")
