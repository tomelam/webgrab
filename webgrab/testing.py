"""A pytest plugin that makes an unmocked network call in a test an error.

Registered through the pytest11 entry point, so any project that installs
webgrab gets it without copying a conftest. That matters: the presence of this
guard in one project and its absence in another is most of the difference
between one's fetchers being testable and the other's not.

Tests that genuinely need the network mark themselves @pytest.mark.network and
are deselected by default.
"""
import socket

import pytest

__all__ = ["NetworkBlockedError"]

_real_create_connection = socket.create_connection
_real_socket_connect = socket.socket.connect


class NetworkBlockedError(RuntimeError):
    """A test tried to reach the network without asking."""


def _msg(address):
    where = ""
    try:
        where = f" to {address[0]}:{address[1]}" if address else ""
    except (TypeError, IndexError):
        where = f" to {address!r}"
    return (f"network access blocked in tests: attempted connection{where}. "
            f"Either mark the test with @pytest.mark.network, or mock the request "
            f"(responses / monkeypatch).")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: hits a live site; opt in with -m network")


@pytest.fixture(autouse=True)
def _block_unmocked_network(request):
    if "network" in request.keywords:
        yield
        return

    def blocked_create_connection(address, *a, **k):
        raise NetworkBlockedError(_msg(address))

    def blocked_connect(self, address, *a, **k):
        raise NetworkBlockedError(_msg(address))

    socket.create_connection = blocked_create_connection
    socket.socket.connect = blocked_connect
    try:
        yield
    finally:
        socket.create_connection = _real_create_connection
        socket.socket.connect = _real_socket_connect
