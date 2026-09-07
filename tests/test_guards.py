"""The network guard, verified by breaking it.

Installing webgrab gives every consuming project this guard through a pytest
entry point. A sibling project that lacks one has untestable scrapers as a result.
"""
import socket
import pytest
from webgrab import testing


def test_an_unmocked_connection_is_blocked_in_an_unmarked_test():
    """This test is NOT marked network, so the autouse guard is active and a real
    connection attempt must fail with an actionable message."""
    with pytest.raises(testing.NetworkBlockedError) as e:
        socket.create_connection(("example.com", 80), timeout=1)
    assert "network" in str(e.value).lower()
    assert "@pytest.mark.network" in str(e.value)


def test_the_guard_names_the_host_it_stopped():
    with pytest.raises(testing.NetworkBlockedError, match="example.com"):
        socket.create_connection(("example.com", 80), timeout=1)


@pytest.mark.network
def test_marked_tests_are_allowed_through():
    """Deselected by default (-m 'not network'), so this only runs on demand."""
    socket.create_connection(("fred.stlouisfed.org", 443), timeout=10).close()
