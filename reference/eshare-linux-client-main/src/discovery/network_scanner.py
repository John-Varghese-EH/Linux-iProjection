"""
network_scanner.py - Subnet Port-Scan Fallback Discovery Backend
================================================================

When mDNS and SSDP miss a device (e.g., it is behind a router that blocks
multicast), this module scans the local subnet for open ESC/VP.net ports
(TCP 3629) and PJLink ports (TCP 4352) to find projectors.

Implementation notes
--------------------
- Uses ``netifaces`` to detect the local subnet automatically.
- Falls back to ``/24`` guessing if ``netifaces`` is unavailable.
- Scanning is done with raw Python sockets (no nmap dependency) using a
  thread pool for speed.
- The scan is intentionally conservative - connect timeout is short and we
  only probe two ports per host.

Thread safety
-------------
``on_found`` is called from worker threads.  Use ``GLib.idle_add()`` when
updating GTK widgets.

Usage (standalone CLI test)
---------------------------
    python -m src.discovery.network_scanner
    python -m src.discovery.network_scanner --subnet 192.168.1.0/24 --workers 64
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from src.models.device import Device

log = logging.getLogger(__name__)

# ── Ports to probe ────────────────────────────────────────────────────────────

PROBE_PORTS: list[tuple[int, str]] = [
    (3629, "escvpnet"),   # Epson ESC/VP.net
    (4352, "pjlink"),     # PJLink
    (56789, "eshare"),    # EShare primary port
]

CONNECT_TIMEOUT = 0.5   # seconds - keep this short for a full /24 scan
DEFAULT_WORKERS = 50    # concurrent connection attempts


# ── Subnet detection ──────────────────────────────────────────────────────────

def _get_local_subnets() -> list[str]:
    """
    Return a list of local subnets as CIDR strings, e.g. ['192.168.1.0/24'].
    Tries netifaces2 (Windows-safe) then netifaces, then falls back.
    """
    try:
        # netifaces2 is a pure-Python drop-in that works on Windows + Linux
        try:
            import netifaces2 as netifaces  # type: ignore
        except ImportError:
            import netifaces  # type: ignore  # legacy C-extension fallback

        subnets: list[str] = []
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            ipv4_list = addrs.get(netifaces.AF_INET, [])
            for entry in ipv4_list:
                addr    = entry.get("addr", "")
                netmask = entry.get("netmask", "255.255.255.0")
                if not addr or addr.startswith("127."):
                    continue
                try:
                    network = ipaddress.IPv4Network(
                        f"{addr}/{netmask}", strict=False
                    )
                    subnets.append(str(network))
                except ValueError:
                    pass
        return subnets or _fallback_subnet()
    except ImportError:
        log.warning("netifaces / netifaces2 not installed - using fallback subnet detection")
        return _fallback_subnet()


def _fallback_subnet() -> list[str]:
    """Best-effort: derive /24 subnet from the outbound interface IP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        parts = local_ip.rsplit(".", 1)
        return [f"{parts[0]}.0/24"]
    except OSError:
        return ["192.168.1.0/24"]


# ── Port probe ────────────────────────────────────────────────────────────────

def _probe_host(ip: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    """Return True if TCP port is open on the given IP."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, socket.timeout):
        return False


def _check_and_build_device(ip: str) -> Optional[Device]:
    """
    Probe all PROBE_PORTS on a host.  If any port is open, return a Device.
    """
    for port, capability in PROBE_PORTS:
        if _probe_host(ip, port):
            log.info("Scan: open port %d on %s  (capability=%s)", port, ip, capability)
            caps = [capability]
            if capability == "escvpnet":
                caps.append("rtp_recv")
            return Device(
                name=f"Device@{ip}",
                ip=ip,
                port=port,
                device_type="epson" if capability in ("escvpnet", "pjlink") else "eshare",
                capabilities=caps,
                metadata={"source": "port_scan", "open_port": port},
                discovery_source="scan",
            )
    return None


# ── Scanner ───────────────────────────────────────────────────────────────────

class NetworkScanner:
    """
    One-shot subnet scanner that probes each host for known projector ports.

    Unlike mDNS/SSDP which run continuously, this scanner does a single sweep
    and then exits.  Call ``scan()`` again for a fresh sweep.

    Parameters
    ----------
    on_found:
        Called for each host where a projector port is open.
    subnet:
        Optional CIDR string (e.g. ``'192.168.1.0/24'``).
        Auto-detected if omitted.
    max_workers:
        Thread pool size for parallel connections.
    connect_timeout:
        Per-connection timeout in seconds.
    """

    def __init__(
        self,
        on_found: Callable[[Device], None],
        subnet: Optional[str] = None,
        max_workers: int = DEFAULT_WORKERS,
        connect_timeout: float = CONNECT_TIMEOUT,
    ) -> None:
        self._on_found  = on_found
        self._subnet    = subnet
        self._max_workers     = max_workers
        self._connect_timeout = connect_timeout
        self._stop_event      = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────

    def scan(self) -> None:
        """Start a background scan sweep (non-blocking)."""
        if self._thread and self._thread.is_alive():
            log.debug("Scan already in progress - ignoring duplicate call.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="net-scanner", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Abort an in-progress scan early."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── Internals ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        subnets = [self._subnet] if self._subnet else _get_local_subnets()
        log.info("Network scan starting - subnets: %s, workers: %d",
                 subnets, self._max_workers)

        for subnet_cidr in subnets:
            if self._stop_event.is_set():
                break
            self._scan_subnet(subnet_cidr)

        log.info("Network scan complete.")

    def _scan_subnet(self, subnet_cidr: str) -> None:
        try:
            network = ipaddress.IPv4Network(subnet_cidr, strict=False)
        except ValueError as exc:
            log.error("Invalid subnet %r: %s", subnet_cidr, exc)
            return

        hosts = list(network.hosts())
        log.info("Scanning %s - %d hosts …", subnet_cidr, len(hosts))

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(_check_and_build_device, str(ip)): str(ip)
                for ip in hosts
                if not self._stop_event.is_set()
            }
            found = 0
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    break
                try:
                    device = future.result()
                except Exception as exc:
                    ip = futures[future]
                    log.debug("Scan error for %s: %s", ip, exc)
                    continue
                if device:
                    found += 1
                    self._on_found(device)

        log.info("Subnet %s done - %d device(s) found.", subnet_cidr, found)


# ── Standalone CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import time

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s")

    parser = argparse.ArgumentParser(description="Subnet port scan for projectors.")
    parser.add_argument("--subnet",  default=None, help="CIDR e.g. 192.168.1.0/24")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()

    print(f"Scanning {args.subnet or 'auto-detected subnet'} …\n")

    def on_found(d: Device) -> None:
        print(f"  [+] {d.name}  caps={d.capabilities}  {d.address}")

    scanner = NetworkScanner(on_found=on_found, subnet=args.subnet,
                             max_workers=args.workers)
    scanner.scan()

    while scanner.is_running:
        time.sleep(0.5)

    print("\nDone.")
