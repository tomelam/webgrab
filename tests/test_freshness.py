"""Freshness: the part no off-the-shelf library provides.

Every test here is a BREAK-TEST for a guard. Per the house rule, a guard is
verified by breaking the thing it protects and watching it fire -- a dead
assertion reads as protection and gives none.
"""
import datetime as dt
import json
import pytest
from webgrab import freshness, parse

TODAY = dt.date(2026, 9, 7)          # fixed, so these never drift
FRED_FX = freshness.Source("fred/DEXINUS", cadence="business_day", max_age_days=10)
SWAP = freshness.Source("fred/DSWP30", cadence="business_day", max_age_days=10)


class TestStaleness:
    def test_a_current_series_passes(self, fx):
        date, _ = parse.csv_last_observation(fx("fred_DEXINUS.csv"))
        freshness.assert_fresh(FRED_FX, date, today=TODAY)   # 2026-08-28, 10 days

    def test_the_dead_swap_series_is_rejected_and_the_age_is_named(self, fx):
        """THE break-test this library exists for. DSWP30 returns a clean 200 with
        valid parseable CSV. Only the observation date reveals it died in 2016."""
        date, _ = parse.csv_last_observation(fx("fred_DSWP30.csv"))
        with pytest.raises(freshness.StaleError) as e:
            freshness.assert_fresh(SWAP, date, today=TODAY)
        msg = str(e.value)
        assert "2016-10-28" in msg
        assert "3601" in msg            # the age in days, stated not implied
        assert "fred/DSWP30" in msg

    def test_one_day_past_the_limit_fires(self):
        """The boundary, so the comparison cannot be off by one unnoticed."""
        s = freshness.Source("x", cadence="business_day", max_age_days=5)
        freshness.assert_fresh(s, "2026-09-02", today=TODAY)          # 5 days: ok
        with pytest.raises(freshness.StaleError):
            freshness.assert_fresh(s, "2026-09-01", today=TODAY)      # 6 days: not


class TestDayGate:
    def test_a_second_contact_on_the_same_day_is_refused(self, tmp_path):
        st = freshness.Stamps(tmp_path / "stamps.json")
        s = freshness.Source("nifty", cadence="business_day", max_age_days=5, day_gated=True)
        assert st.may_contact(s, today=TODAY) is True
        st.note_attempt(s, today=TODAY)
        assert st.may_contact(s, today=TODAY) is False
        assert st.may_contact(s, today=TODAY + dt.timedelta(days=1)) is True

    def test_a_failed_fetch_still_burns_the_day(self, tmp_path):
        """The attempt is stamped BEFORE the fetch, so a host that bans on bursts
        is not hit again today just because the first try raised."""
        st = freshness.Stamps(tmp_path / "stamps.json")
        s = freshness.Source("nifty", cadence="business_day", max_age_days=5, day_gated=True)

        def exploding_fetch():
            raise RuntimeError("blocked")

        with pytest.raises(RuntimeError):
            st.guarded_fetch(s, exploding_fetch, today=TODAY)
        assert st.may_contact(s, today=TODAY) is False

    def test_an_ungated_source_is_not_limited(self, tmp_path):
        st = freshness.Stamps(tmp_path / "stamps.json")
        s = freshness.Source("gold", cadence="continuous", max_age_days=1)
        st.note_attempt(s, today=TODAY)
        assert st.may_contact(s, today=TODAY) is True


class TestStampFileDesync:
    def test_a_reverted_file_cannot_be_certified_fresh_by_its_stamp(self, tmp_path):
        """Subtle and real: the stamp says we fetched through 2026-09-03, but the
        file on disk was restored from an older backup. Trusting the stamp would
        report fresh data that is not there."""
        st = freshness.Stamps(tmp_path / "stamps.json")
        s = freshness.Source("fred/DGS10", cadence="business_day", max_age_days=10)
        data = tmp_path / "dgs10.csv"

        data.write_text("observation_date,DGS10\n2026-09-03,4.77\n")
        st.note_success(s, last_date="2026-09-03", path=data)
        assert st.honoured(s, data) is True

        data.write_text("observation_date,DGS10\n2026-07-01,4.20\n")   # reverted
        assert st.honoured(s, data) is False

    def test_a_missing_file_is_not_honoured(self, tmp_path):
        st = freshness.Stamps(tmp_path / "stamps.json")
        s = freshness.Source("fred/DGS10", cadence="business_day", max_age_days=10)
        data = tmp_path / "gone.csv"
        data.write_text("observation_date,DGS10\n2026-09-03,4.77\n")
        st.note_success(s, last_date="2026-09-03", path=data)
        data.unlink()
        assert st.honoured(s, data) is False


class TestToDate:
    """These sites emit four different date shapes. None is guessed at."""

    def test_iso_date(self):
        assert freshness.to_date("2026-08-28") == dt.date(2026, 8, 28)

    def test_iso_datetime_with_zulu(self):
        """gold-api returns '2026-09-07T10:37:17Z'."""
        assert freshness.to_date("2026-09-07T10:37:17Z") == dt.date(2026, 9, 7)

    def test_day_first_with_dashes(self):
        """mfapi returns '04-09-2026' -- day first, not month first."""
        assert freshness.to_date("04-09-2026") == dt.date(2026, 9, 4)

    def test_day_first_with_slashes(self):
        """IBJA returns '04/09/2026'."""
        assert freshness.to_date("04/09/2026") == dt.date(2026, 9, 4)

    def test_an_ambiguous_or_unknown_shape_raises(self):
        for bad in ("Sept 4 2026", "2026", "04-09-26", ""):
            with pytest.raises(ValueError):
                freshness.to_date(bad)
