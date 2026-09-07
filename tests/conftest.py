import pathlib
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def fx():
    """Read a recorded fixture. Fixtures are evidence: recorded from the live site
    on 2026-09-07 and never hand-edited. Regenerate with `make record`."""
    def _read(name):
        p = FIXTURES / name
        if not p.exists():
            raise AssertionError(f"missing fixture {name} -- run `make record`")
        return p.read_text(errors="replace")
    return _read
