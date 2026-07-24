"""
linux-iprojection: Discovery of Epson projectors / EShare receivers on the local network.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

Two strategies, used together:

1. mDNS/zeroconf browsing. We look for specific service types and also
   filter _http._tcp.local. for projector-related keywords.
2. A LAN sweep on TCP port 3629 (ESC/VP.net control).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field

from zeroconf import ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

from .pjlink import PJLINK_PORT
from .protocol import ESCVP_PORT

log = logging.getLogger(__name__)

SERVICE_TYPES = [
    "_epson._tcp.local.",
    "_eshare._tcp.local.",
    "_http._tcp.local.",
    "_pjlink._tcp.local.",
]

HTTP_KEYWORDS = [
    "eshare",
    "screen",
    "cast",
    "display",
    "receiver",
    "epson",
    "projector",
    "pj",
    "eb-",
    "ex-",
    "powerlite",
]

SCAN_TIMEOUT = 0.4
SCAN_CONCURRENCY = 64


@dataclass
class DiscoveredDevice:
    name: str
    address: str
    port: int
    source: str  # "mdns" or "scan"
    alias: str | None = None
    device_type: str = "unknown"
    capabilities: list[str] = field(default_factory=list)
    stream_port: int = 5004
    audio_port: int = 5006
    info: dict = field(default_factory=dict)


class _CollectingListener(ServiceListener):
    def __init__(self, results: list[DiscoveredDevice]):
        self.results = results

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if not info:
            return

        # Keyword filtering for generic HTTP services
        if type_ == "_http._tcp.local.":
            name_lower = name.lower()
            if not any(kw in name_lower for kw in HTTP_KEYWORDS):
                return

        capabilities = []
        if info.properties:
            for k, v in info.properties.items():
                if isinstance(v, bytes):
                    try:
                        v_str = v.decode("utf-8")
                    except UnicodeDecodeError:
                        v_str = repr(v)
                else:
                    v_str = str(v)
                capabilities.append(f"{k.decode('utf-8') if isinstance(k, bytes) else k}={v_str}")

        device_type = "projector"
        if "_eshare" in type_:
            device_type = "eshare_receiver"
        elif "_pjlink" in type_:
            device_type = "pjlink_projector"

        for addr in info.addresses_by_version(4):
            self.results.append(
                DiscoveredDevice(
                    name=name,
                    address=socket.inet_ntoa(addr),
                    port=info.port or ESCVP_PORT,
                    source="mdns",
                    device_type=device_type,
                    capabilities=capabilities,
                    stream_port=5004,
                    audio_port=5006,
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
        browsers = [AsyncServiceBrowser(azc.zeroconf, svc, listener) for svc in SERVICE_TYPES]
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
            return DiscoveredDevice(
                name=ip,
                address=ip,
                port=port,
                source="scan",
                device_type="projector",
                stream_port=5004,
                audio_port=5006,
            )
        except (OSError, asyncio.TimeoutError):
            return None


async def discover_by_scan(
    ports: list[int] = None, network: ipaddress.IPv4Network | None = None
) -> list[DiscoveredDevice]:
    if ports is None:
        # 3629 = ESC/VP, 4352 = PJLink, 3620/3621 = iProjection data ports
        ports = [ESCVP_PORT, PJLINK_PORT, 3620, 3621]

    networks = [network] if network else _local_ipv4_networks()
    if not networks:
        log.warning("Could not determine local subnet - enter the projector IP manually")
        return []

    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    tasks = []
    for net in networks:
        for host in net.hosts():
            for port in ports:
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
