"""Reading each source's newest observation date -- offline, from fixtures.

This is the pure half of `probe`. Keeping it separate from the fetching is what
lets the 'is this endpoint alive' logic be tested without a network at all.
"""
import datetime as dt
import pytest
from webgrab import probe, registry

REG = registry.load()


class TestNewestObservation:
    def test_fred_csv(self, fx):
        assert probe.newest_observation(REG["fred"], fx("fred_DEXINUS.csv")) == dt.date(2026, 8, 28)

    def test_the_dead_swap_series_reports_2016(self, fx):
        """Reading the date is what distinguishes this from a healthy series;
        every other signal -- status, content type, parseability -- says 'fine'."""
        e = REG["fred"]
        assert probe.newest_observation(e, fx("fred_DSWP30.csv")) == dt.date(2016, 10, 28)

    def test_gold_api_iso_datetime(self, fx):
        assert probe.newest_observation(REG["gold_api"], fx("gold_api_XAU.json")) == dt.date(2026, 9, 7)

    def test_mfapi_day_first_date(self, fx):
        assert probe.newest_observation(REG["mfapi"], fx("mfapi_122639_live.json")) == dt.date(2026, 9, 4)

    def test_mfapi_dead_fund_reports_2008(self, fx):
        assert probe.newest_observation(REG["mfapi"], fx("mfapi_100027_dead.json")) == dt.date(2008, 5, 29)

    def test_ibja_hidden_input(self, fx):
        assert probe.newest_observation(REG["ibjarates"], fx("ibjarates.html")) == dt.date(2026, 9, 4)

    def test_a_static_source_has_no_observation_date(self, fx):
        """archive.org items do not go stale. None here means 'not applicable',
        and the caller must not treat it as 'fresh'."""
        assert probe.newest_observation(REG["archive_org"], fx("archive_metadata_real.json")) is None

    def test_an_unknown_kind_raises_rather_than_being_skipped(self):
        e = registry.Entry(id="x", newest_date={"kind": "telepathy"})
        with pytest.raises(probe.ProbeError, match="telepathy"):
            probe.newest_observation(e, "whatever")

    def test_a_source_with_no_spec_raises(self):
        """Silently returning None would make an unspecified source look eternally
        fresh, which is the failure this whole module guards against."""
        e = registry.Entry(id="x")
        with pytest.raises(probe.ProbeError, match="no newest_date"):
            probe.newest_observation(e, "whatever")


class TestVerdict:
    def test_a_current_source_is_ok(self, fx):
        v = probe.verdict(REG["fred"], fx("fred_DEXINUS.csv"), today=dt.date(2026, 9, 7))
        assert v.ok and v.age_days == 10

    def test_a_dead_source_is_not_ok_and_says_why(self, fx):
        v = probe.verdict(REG["fred"], fx("fred_DSWP30.csv"), today=dt.date(2026, 9, 7))
        assert not v.ok
        assert "3601 days old" in v.detail

    def test_a_static_source_is_ok_without_a_date(self, fx):
        v = probe.verdict(REG["archive_org"], fx("archive_metadata_real.json"),
                          today=dt.date(2026, 9, 7))
        assert v.ok and v.age_days is None
