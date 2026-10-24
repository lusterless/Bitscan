"""The client address of a request: the TCP peer (#55 (d); proxy headers are
ignored), normalised once for every route group, so limiter keys, audit
details and stored addresses agree across agent and user routes (REQ-065 (3)).

An IPv6 zone (fe80::1%eth0, as CPython reports a link-local peer of a server
on ::) names the manager's interface, not the client, and PostgreSQL inet has
none: it is dropped. An IPv4-mapped IPv6 peer is reported as IPv4.
"""

import ipaddress

from fastapi import Request


def peer_ip(request: Request) -> str | None:
    """The normalised peer address, or None if the peer is not an IP."""
    host = request.client.host if request.client is not None else ""
    try:
        address = ipaddress.ip_address(host.partition("%")[0])
    except ValueError:
        return None
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return str(mapped or address)


def peer_key(request: Request) -> str:
    """For limiter keys and audit details: the normalised address, else the
    peer as given (a test client's name), else "unknown"."""
    host = request.client.host if request.client is not None else ""
    return peer_ip(request) or host or "unknown"
