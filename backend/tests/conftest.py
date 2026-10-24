import socket

import pytest


def make_resolver(*ips: str):
    """Fake getaddrinfo returning the given addresses for any host."""

    def resolver(host, port, **kwargs):
        family = lambda ip: socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family(ip), socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return resolver


@pytest.fixture
def public_dns():
    return make_resolver("93.184.216.34")
