import ipaddress
import socket


def host_is_private(host: str, *, block_local_names: bool = False) -> bool:
    if not host:
        return True
    if block_local_names:
        lowered = host.casefold()
        if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
            return True

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue

    return any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        for address in addresses
    )
