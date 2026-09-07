"""The registry, plus invariants that stop it rotting into stale prose."""
import os
import pathlib
import pytest
from webgrab import registry, freshness

REG = registry.load()


class TestLoading:
    def test_loads_every_source(self):
        assert len(REG) == 15

    def test_fred_carries_the_measured_ua_policy(self):
        """The finding must live in the registry, not only in a commit message.

        'default' here means SEND NO OVERRIDE. FRED is behind Akamai, which blocks
        an unrecognised UA token -- measured 2026-09-07, repeated with controls."""
        e = REG["fred"]
        assert e.user_agent == "default"
        notes = e.notes.upper()
        assert "AKAMAI" in notes, "the note must say WHY the UA policy is what it is"
        assert "2026-09-07" in e.notes, "a measurement needs its date"

    def test_dead_sources_record_when_they_died(self):
        assert REG["fred_swap_30y"].status == "dead"
        assert REG["fred_swap_30y"].newest_observation.isoformat() == "2016-10-28"

    def test_burst_sensitive_hosts_declare_no_retries(self):
        """niftyindices bans on bursts, so retrying is actively harmful."""
        assert REG["niftyindices"].retries == 0
        assert REG["niftyindices"].day_gated is True


class TestUrlResolution:
    def test_fills_the_template(self):
        assert REG["fred"].resolve(series="DGS10").endswith("id=DGS10")

    def test_missing_parameter_raises_rather_than_producing_a_broken_url(self):
        with pytest.raises(registry.RegistryError, match="series"):
            REG["fred"].resolve()

    def test_a_static_url_needs_no_parameters(self):
        assert REG["ibjarates"].resolve() == "https://ibjarates.com/"


class TestAsSource:
    def test_maps_onto_a_freshness_source(self):
        s = REG["fred"].as_source()
        assert isinstance(s, freshness.Source)
        assert s.max_age_days == 10 and s.cadence == "business_day"

    def test_a_source_without_a_cadence_cannot_be_freshness_checked(self):
        """archive.org items are static; claiming a max age would be a fiction."""
        with pytest.raises(registry.RegistryError, match="no cadence"):
            REG["archive_org"].as_source()


class TestInvariants:
    """These fail when the registry drifts, which is the point of having it."""

    def test_every_working_source_declares_a_ua_policy_and_retry_count(self):
        for e in REG.values():
            if e.status == "works":
                assert e.user_agent in ("default", "browser", "none"), e.id
                assert isinstance(e.retries, int), e.id

    def test_every_source_says_why_it_is_in_the_state_it_is_in(self):
        for e in REG.values():
            assert e.notes and e.notes.strip(), f"{e.id} has no notes"

    def test_probeable_excludes_the_unprobeable(self):
        ids = {e.id for e in registry.probeable(REG)}
        assert "fred" in ids and "ibjarates" in ids
        assert "fred_swap_30y" not in ids          # dead
        assert "stooq" not in ids                  # blocked
        assert "niftyindices" not in ids           # needs a browser
        assert "rbi_sgb" not in ids                # works, but declares no probe params


class TestPrivacyBoundary:
    """The registry records HOW to talk to a site, never WHAT the household owns.

    A grep in a runbook gets skipped. A test does not."""

    # Deliberately env-var only, with no default: hardcoding a path here would
    # publish the location of a private file in a public repository, which is the
    # very thing this test exists to prevent. Consumers point it at their own
    # private config, e.g.
    #     WEBGRAB_PRIVACY_CHECK_FILE=/path/to/positions.toml pytest
    _ENV = os.environ.get("WEBGRAB_PRIVACY_CHECK_FILE")
    POSITIONS = pathlib.Path(_ENV) if _ENV else None

    @pytest.mark.skipif(not (POSITIONS and POSITIONS.exists()),
                        reason="set WEBGRAB_PRIVACY_CHECK_FILE to run this")
    def test_no_household_scheme_code_appears_in_the_registry(self):
        import re
        held = set(re.findall(r'^\s*mfapi\s*=\s*"?(\d+)"?',
                              self.POSITIONS.read_text(), re.M))
        assert held, "expected to find scheme codes to exclude; parser may have drifted"
        raw = (pathlib.Path(registry.__file__).parent / "sources.toml").read_text()
        leaked = sorted(c for c in held if c in raw)
        assert not leaked, f"{len(leaked)} household scheme code(s) leaked into sources.toml"
