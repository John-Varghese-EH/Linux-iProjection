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

from zeroconf import Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

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
    device_type: str = "projector"
    capabilities: list[str] = field(default_factory=list)
    stream_port: int = 5004
    audio_port: int = 5006
    info: dict = field(default_factory=dict)


class _AsyncCollectingListener:
    def __init__(self, azc: AsyncZeroconf, results: list[DiscoveredDevice]):
        self.azc = azc
        self.results = results
        self._tasks: set[asyncio.Task] = set()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        task = asyncio.create_task(self._process_service(type_, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    async def _process_service(self, type_: str, name: str) -> None:
        try:
            info = AsyncServiceInfo(type_, name)
            await info.async_request(self.azc.zeroconf, 3000)
            if not info or not info.addresses:
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
                    capabilities.append(
                        f"{k.decode('utf-8') if isinstance(k, bytes) else k}={v_str}"
                    )

            device_type = "projector"
            if "_eshare" in type_:
                device_type = "eshare_receiver"
            elif "_pjlink" in type_:
                device_type = "pjlink_projector"

            for addr in info.addresses_by_version(4):
                ip_str = socket.inet_ntoa(addr)
                self.results.append(
                    DiscoveredDevice(
                        name=name,
                        address=ip_str,
                        port=info.port or ESCVP_PORT,
                        source="mdns",
                        device_type=device_type,
                        capabilities=capabilities,
                        stream_port=5004,
                        audio_port=5006,
                        info={"type": type_, "server": info.server},
                    )
                )
        except Exception as e:
            log.debug("mDNS async process error: %s", e)


async def discover_mdns(timeout: float = 3.0) -> list[DiscoveredDevice]:
    results: list[DiscoveredDevice] = []
    try:
        async with AsyncZeroconf() as azc:
            listener = _AsyncCollectingListener(azc, results)
            browsers = [
                AsyncServiceBrowser(azc.zeroconf, svc, listener) for svc in SERVICE_TYPES
            ]
            await asyncio.sleep(timeout)
            for b in browsers:
                await b.async_cancel()
    except Exception as e:
        log.debug("mDNS discovery error: %s", e)
    return results


def _local_ipv4_networks() -> list[ipaddress.IPv4Network]:
    """Find this host's active IPv4 /24 subnets across all network interfaces."""
    nets: list[ipaddress.IPv4Network] = []
    try:
        import psutil

        for iface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    ip = addr.address
                    netmask = addr.netmask or "255.255.255.0"
                    try:
                        iface = ipaddress.IPv4Interface(f"{ip}/{netmask}")
                        # Constrain large networks (e.g. link-local /16) to /24 around host to keep scan fast
                        if iface.network.prefixlen < 24:
                            sub = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                            if sub not in nets:
                                nets.append(sub)
                        elif iface.network not in nets:
                            nets.append(iface.network)
                    except Exception:
                        pass
    except ImportError:
        pass

    if not nets:
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


def _get_arp_neighbor_ips() -> set[str]:
    """Retrieve active neighbor IPs from the ARP table for fast direct-link discovery."""
    ips = set()
    try:
        with open("/proc/net/arp", "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[3] not in ("00:00:00:00:00:00", "00:00:00:00:00:00:00:00"):
                    ip_cand = parts[0].strip()
                    try:
                        ipaddress.IPv4Address(ip_cand)
                        ips.add(ip_cand)
                    except ValueError:
                        pass
    except Exception:
        pass
    return ips


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
    ports: list[int] | None = None, network: ipaddress.IPv4Network | None = None
) -> list[DiscoveredDevice]:
    if ports is None:
        # 3629 = ESC/VP, 4352 = PJLink, 3620/3621 = iProjection data ports
        ports = [ESCVP_PORT, PJLINK_PORT, 3620, 3621]

    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    tasks = []
    seen_ips = set()

    # Strategy 1: Fast ARP neighbor sweep (critical for direct link-local / LAN cables)
    arp_ips = _get_arp_neighbor_ips()
    for ip in arp_ips:
        seen_ips.add(ip)
        for port in ports:
            tasks.append(_probe(ip, port, sem))

    # Strategy 2: Subnet sweep
    networks = [network] if network else _local_ipv4_networks()
    for net in networks:
        for host in net.hosts():
            host_str = str(host)
            if host_str not in seen_ips:
                for port in ports:
                    tasks.append(_probe(host_str, port, sem))

    if not tasks:
        log.warning("Could not determine local subnet - enter the projector IP manually")
        return []

    results = await asyncio.gather(*tasks)
    discovered: list[DiscoveredDevice] = []
    dedup_addresses = set()
    for r in results:
        if r is not None and r.address not in dedup_addresses:
            dedup_addresses.add(r.address)
            discovered.append(r)
    return discovered


# ── Epson Proprietary EEMP UDP Broadcast Discovery ──────────────────────────
#
# Reverse-engineered from EMP_PJCON.dll and EMP_NMANG.dll.
# The Windows iProjection app broadcasts UDP packets with magic bytes
# "EEMP" + "0100" on port 3620. Epson projectors on the LAN respond
# with their capabilities and identification data.

EEMP_MAGIC = b"EEMP"
EEMP_VERSION = b"0100"
EEMP_DISCOVERY_PORT = 3620
EEMP_RESPONSE_PORT = 3621


def _build_eemp_discovery_packet() -> bytes:
    """Build an EEMP discovery broadcast packet.

    Packet structure (derived from binary analysis):
    - Bytes 0-3:  Magic "EEMP"
    - Bytes 4-7:  Version "0100"
    - Bytes 8-15: Padding/reserved (zeroes)
    Total: 16 bytes minimum
    """
    packet = bytearray(64)
    packet[0:4] = EEMP_MAGIC
    packet[4:8] = EEMP_VERSION
    return bytes(packet)


def _parse_eemp_response(data: bytes, addr: tuple) -> DiscoveredDevice | None:
    """Parse an EEMP discovery response from a projector.

    The response begins with "EEMP" magic bytes followed by capability
    and identification data.
    """
    if len(data) < 8 or data[:4] != EEMP_MAGIC:
        return None

    ip = addr[0]

    # Extract projector name from response if present
    # The name is typically embedded as a null-terminated ASCII string
    name = f"EPSON Projector ({ip})"
    try:
        # Look for readable ASCII strings after the header
        text_region = data[16:]
        ascii_parts = []
        current = bytearray()
        for b in text_region:
            if 0x20 <= b <= 0x7E:
                current.append(b)
            else:
                if len(current) >= 3:
                    ascii_parts.append(current.decode("ascii"))
                current = bytearray()
        if len(current) >= 3:
            ascii_parts.append(current.decode("ascii"))
        if ascii_parts:
            name = ascii_parts[0]
    except Exception:
        pass

    # Parse capability flags from known positions
    capabilities = ["eemp_discovery"]
    try:
        if len(data) > 32:
            cap_byte = data[16] if len(data) > 16 else 0
            if cap_byte & 0x01:
                capabilities.append("jpeg_rect")
            if cap_byte & 0x02:
                capabilities.append("mpeg4_avc")
            if cap_byte & 0x04:
                capabilities.append("audio")
            if cap_byte & 0x08:
                capabilities.append("aes_encryption")
    except Exception:
        pass

    return DiscoveredDevice(
        name=name,
        address=ip,
        port=ESCVP_PORT,
        source="eemp",
        device_type="projector",
        capabilities=capabilities,
        stream_port=5004,
        audio_port=5006,
        info={"discovery": "eemp", "raw_len": len(data)},
    )


async def discover_eemp(timeout: float = 2.0) -> list[DiscoveredDevice]:
    """Discover Epson projectors via the proprietary EEMP UDP broadcast protocol.

    Sends a broadcast packet on port 3620 and listens for responses on port 3621,
    matching the behavior observed in the Windows iProjection software.
    """
    results: list[DiscoveredDevice] = []
    packet = _build_eemp_discovery_packet()

    loop = asyncio.get_running_loop()

    class EempProtocol(asyncio.DatagramProtocol):
        def __init__(self):
            self.transport = None

        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            device = _parse_eemp_response(data, addr)
            if device:
                log.info("EEMP discovery: found %s at %s", device.name, device.address)
                results.append(device)

    try:
        transport, protocol = await loop.create_datagram_endpoint(
            EempProtocol,
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )

        try:
            # Broadcast on all interfaces
            transport.sendto(packet, ("255.255.255.255", EEMP_DISCOVERY_PORT))
            # Also try common subnet broadcasts
            for net in _local_ipv4_networks():
                try:
                    broadcast = str(net.broadcast_address)
                    transport.sendto(packet, (broadcast, EEMP_DISCOVERY_PORT))
                except Exception:
                    pass

            await asyncio.sleep(timeout)
        finally:
            transport.close()
    except Exception as e:
        log.debug("EEMP discovery error: %s", e)

    return results


async def discover_all(mdns_timeout: float = 3.0) -> list[DiscoveredDevice]:
    """Run all discovery strategies concurrently, dedupe by address."""
    mdns_task = asyncio.create_task(discover_mdns(mdns_timeout))
    scan_task = asyncio.create_task(discover_by_scan())
    eemp_task = asyncio.create_task(discover_eemp(timeout=2.0))
    mdns_results, scan_results, eemp_results = await asyncio.gather(
        mdns_task, scan_task, eemp_task
    )

    seen: dict[str, DiscoveredDevice] = {}
    # Priority: mDNS > EEMP > scan (mDNS has friendly names, EEMP has capabilities)
    for d in [*mdns_results, *eemp_results, *scan_results]:
        if d.address not in seen or seen[d.address].source == "scan":
            seen[d.address] = d
    return list(seen.values())

