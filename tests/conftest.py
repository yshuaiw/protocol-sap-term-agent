"""All tests are offline. Windows asyncio loopback sockets remain available."""
import socket
import pytest


@pytest.fixture(autouse=True)
def prohibit_external_network(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('External network is forbidden in this test suite.')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
