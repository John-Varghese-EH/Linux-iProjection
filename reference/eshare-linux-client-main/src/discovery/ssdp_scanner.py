"""
ssdp_scanner.py — SSDP / UPnP Discovery Backend
================================================

Sends an SSDP ``M-SEARCH`` multicast request and listens for responses that
identify Epson projectors or EShare displays.

Protocol overview
-----------------
- Multicast group : ``239.255.255.250``
- Port            : ``1900``  (UDP)
- Request         : HTTP-like ``M-SEARCH`` message over UDP multicast
- Response        : Unicast UDP response back to the sender

We look for ``SERVER:`` or ``ST:`` headers that contain known vendor strings.

Thread safety
-------------
``on_found`` and ``on_lost`` are called from the scanner's background thread.
Use ``GLib.idle_add()`` when updating GTK widgets.

Usage (standalone CLI test)
---------------------------
    python -m src.discovery.ssdp_scanner
"""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from typing import Callable, Optional

from src.models.device import Device

log = logging.getLogger(__name__)

# ── SSDP constants ────────────────────────────────────────────────────────────

SSDP_MULTICAST_IP   = "239.255.255.250"
SSDP_PORT           = 1900
SSDP_RECV_TIMEOUT   = 3.0    # seconds to wait for responses per sweep
SSDP_SWEEP_INTERVAL = 30.0   # seconds between active M-SEARCH sweeps

# The M-SEARCH request targets all UPnP root devices; we then filter responses.
SSDP_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_MULTICAST_IP}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
).encode()

# Vendor identification patterns (case-insensitive, matched against full response)
VENDOR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"epson",      re.I), "epson"),
    (re.compile(r"eshare",     re.I), "eshare"),
    (re.compile(r"projector",  re.I), "epson"),
    (re.compile(r"display.*receiver", re.I), "eshare"),
]

# Headers we care about extracting
_HEADER_RE = re.compile(r"^([A-Z\-]+):\s*(.+)$", re.I | re.M)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ssdp_response(raw: bytes) -> dict[str, str]:
    """Parse a raw SSDP UDP response into a header dict (lowercase keys)."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return {}
    return {m.group(1).lower(): m.group(2).strip() for m in _HEADER_RE.finditer(text)}


def _classify_ssdp(headers: dict[str, str]) -> Optional[str]:
    """
    Return 'epson', 'eshare', or None based on SSDP response headers.
    Checks SERVER, ST, USN, LOCATION fields against vendor patterns.
    """
    combined = " ".join(headers.values())
    for pattern, device_type in VENDOR_PATTERNS:
        if pattern.search(combined):
            return device_type
    return None


def _device_from_ssdp(headers: dict[str, str], peer_ip: str) -> Optional[Device]:
    """Build a Device from parsed SSDP response headers and sender IP."""
    device_type = _classify_ssdp(headers)
    if device_type is None:
        return None

    # Try to get a friendly name from the USN or SERVER header
    usn    = headers.get("usn",    "")
    server = headers.get("server", "")
    name   = server or usn.split("::")[-1] or peer_ip
    # Trim UUID prefix if present
    name = re.sub(r"^uuid:[0-9a-f\-]+:?:?", "", name, flags=re.I).strip()
    name = name or peer_ip

    # Capabilities
    capabilities: list[str] = []
    if device_type == "epson":
        capabilities = ["escvpnet", "rtp_recv"]
    elif device_type == "eshare":
        capabilities = ["eshare_app", "webcast"]

    return Device(
        name=name,
        ip=peer_ip,
        port=SSDP_PORT,          # placeholder; real control port discovered later
        device_type=device_type,
        capabilities=capabilities,
        metadata=headers,
        discovery_source="ssdp",
    )


# ── Scanner ───────────────────────────────────────────────────────────────────

class SsdpScanner:
    """
    Active SSDP scanner: sends M-SEARCH multicast and collects responses.

    Parameters
    ----------
    on_found:
        Called with a :class:`~src.models.device.Device` when a new device
        is identified.  May be called from a background thread.
    on_lost:
        Called with ``(ip: str, port: int)`` when a device hasn't been seen
        for ``stale_timeout`` seconds.
    sweep_interval:
        How often (seconds) to resend the M-SEARCH request.
    stale_timeout:
        How many seconds of silence before a device is considered gone.
    """

    def __init__(
        self,
        on_found: Callable[[Device], None],
        on_lost:  Callable[[str, int], None],
        sweep_interval: float = SSDP_SWEEP_INTERVAL,
        stale_timeout:  float = 90.0,
    ) -> None:
        self._on_found = on_found
        self._on_lost  = on_lost
        self._sweep_interval = sweep_interval
        self._stale_timeout  = stale_timeout

        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seen: dict[str, tuple[Device, float]] = {}   # ip → (device, last_seen)
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background sweep thread (non-blocking)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="ssdp-scanner", daemon=True
        )
        self._thread.start()
        log.info("SSDP scanner started (sweep every %.0fs)", self._sweep_interval)

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("SSDP scanner stopped.")

    def __enter__(self) -> "SsdpScanner":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ── Background thread ─────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._sweep()
            self._expire_stale()
            self._stop_event.wait(timeout=self._sweep_interval)

    def _sweep(self) -> None:
        """Send one M-SEARCH and collect responses for SSDP_RECV_TIMEOUT seconds."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET,   socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP,   socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(SSDP_RECV_TIMEOUT)
            sock.bind(("", 0))

            sock.sendto(SSDP_MSEARCH, (SSDP_MULTICAST_IP, SSDP_PORT))
            log.debug("SSDP: M-SEARCH sent to %s:%d", SSDP_MULTICAST_IP, SSDP_PORT)

            deadline = time.monotonic() + SSDP_RECV_TIMEOUT
            while time.monotonic() < deadline and not self._stop_event.is_set():
                try:
                    data, (peer_ip, _) = sock.recvfrom(4096)
                except socket.timeout:
                    break

                headers = _parse_ssdp_response(data)
                device  = _device_from_ssdp(headers, peer_ip)
                if device is None:
                    continue

                with self._lock:
                    is_new = device.ip not in self._seen
                    self._seen[device.ip] = (device, time.monotonic())

                if is_new:
                    log.info("SSDP: found  %r  (%s)  %s",
                             device.name, device.device_type, device.address)
                    self._on_found(device)

        except OSError as exc:
            log.error("SSDP sweep error: %s", exc)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _expire_stale(self) -> None:
        """Remove devices not seen within stale_timeout seconds."""
        now = time.monotonic()
        with self._lock:
            stale = [
                ip for ip, (_, ts) in self._seen.items()
                if now - ts > self._stale_timeout
            ]
            for ip in stale:
                device, _ = self._seen.pop(ip)
                log.info("SSDP: expired  %r  (%s)", device.name, device.address)
                self._on_lost(device.ip, device.port)


# ── Standalone CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s")
    print("SSDP scan …  (Ctrl+C to stop)\n")

    def on_found(d: Device) -> None:
        print(f"  [+] {d.name:<30}  {d.device_type:<8}  {d.address}")

    def on_lost(ip: str, port: int) -> None:
        print(f"  [-] Lost {ip}:{port}")

    scanner = SsdpScanner(on_found=on_found, on_lost=on_lost)
    scanner.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        scanner.stop()
        print("\nDone.")
