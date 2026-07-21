"""
Discovery of Epson projectors / EShare receivers on the local network.

Two strategies, used together:

1. mDNS/zeroconf browsing. NOTE: I have not been able to confirm the exact
   mDNS service type Epson's EShare receivers advertise (the referenced
   `eshare-linux-client` project presumably found this by packet capture).
   Once you have the repo cloned, grep its source for the `ServiceBrowser`
   / service-type string it uses and drop it into SERVICE_TYPES below -
   I don't want to guess a string here and have it silently discover
   nothing. `_projector._tcp.local.` and `_eshare._tcp.local.` below are
   placeholders to replace once confirmed.

2. A LAN sweep on TCP port 3629 (ESC/VP.net control), which IS documented
   and doesn't depend on mDNS working on your network/compositor. This
   alone is enough to find and control any Epson projector with LAN/ESC-VP
   support, independent of whether casting discovery works.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser

from .protocol import ESCVP_PORT

log = logging.getLogger(__name__)

# Placeholders - replace once confirmed from the reference client's source.
SERVICE_TYPES = [
    "_projector._tcp.local.",
    "_eshare._tcp.local.",
]

SCAN_TIMEOUT = 0.4
SCAN_CONCURRENCY = 64


@dataclass
class DiscoveredDevice:
    name: str
    address: str
    port: int
    source: str  # "mdns" or "scan"
    info: dict = field(default_factory=dict)


class _CollectingListener(ServiceListener):
    def __init__(self, results: list[DiscoveredDevice]):
        self.results = results

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if not info:
            return
        for addr in info.addresses_by_version(4):
            self.results.append(
                DiscoveredDevice(
                    name=name,
                    address=socket.inet_ntoa(addr),
                    port=info.port or ESCVP_PORT,
                    source="mdns",
                    info={"type": type_, "server": info.server},
                )
            )

    def update_service(self, zc, type_, name):
        pass

    def remove_service(self, zc, type_, name):
        pass


async def discover_mdns(timeout: float = 3.0) -> list[DiscoveredDevice]:
    results: list[DiscoveredDevice] = []
    async with AsyncZeroconf() as azc:
        listener = _CollectingListener(results)
        browsers = [
            AsyncServiceBrowser(azc.zeroconf, svc, listener) for svc in SERVICE_TYPES
        ]
        await asyncio.sleep(timeout)
        for b in browsers:
            await b.async_cancel()
    return results


def _local_ipv4_networks() -> list[ipaddress.IPv4Network]:
    """Best-effort: find this host's IPv4 /24s to sweep. Falls back to
    nothing if it can't determine an address (caller should let the user
    enter an IP manually in that case).
    """
    nets: list[ipaddress.IPv4Network] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        iface = ipaddress.ip_interface(f"{local_ip}/24")
        nets.append(iface.network)
    except OSError:
        pass
    return nets


async def _probe(ip: str, port: int, sem: asyncio.Semaphore) -> DiscoveredDevice | None:
    async with sem:
        try:
            fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(fut, timeout=SCAN_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return DiscoveredDevice(name=ip, address=ip, port=port, source="scan")
        except (OSError, asyncio.TimeoutError):
            return None


async def discover_by_scan(
    port: int = ESCVP_PORT, network: ipaddress.IPv4Network | None = None
) -> list[DiscoveredDevice]:
    networks = [network] if network else _local_ipv4_networks()
    if not networks:
        log.warning("Could not determine local subnet - enter the projector IP manually")
        return []

    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    tasks = []
    for net in networks:
        for host in net.hosts():
            tasks.append(_probe(str(host), port, sem))

    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def discover_all(mdns_timeout: float = 3.0) -> list[DiscoveredDevice]:
    """Run both strategies concurrently, dedupe by address."""
    mdns_task = asyncio.create_task(discover_mdns(mdns_timeout))
    scan_task = asyncio.create_task(discover_by_scan())
    mdns_results, scan_results = await asyncio.gather(mdns_task, scan_task)

    seen: dict[str, DiscoveredDevice] = {}
    for d in [*mdns_results, *scan_results]:
        # Prefer the mDNS entry (has a friendly name) over a bare scan hit.
        if d.address not in seen or seen[d.address].source == "scan":
            seen[d.address] = d
    return list(seen.values())
