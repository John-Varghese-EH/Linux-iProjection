"""
mdns_scanner.py - mDNS / DNS-SD Discovery Backend
==================================================

Uses ``python-zeroconf`` to browse for projectors and displays that advertise
themselves on the local network via mDNS.

Service types watched
---------------------
- ``_epson._tcp.local.``    - Epson network projectors (iProjection / EasyMP)
- ``_eshare._tcp.local.``   - EShare wireless display receivers
- ``_http._tcp.local.``     - Generic HTTP devices (filtered by TXT records)
- ``_printer._tcp.local.``  - Some Epson models also announce here

Thread safety
-------------
All callbacks (``on_found``, ``on_lost``) are invoked from the zeroconf
internal thread.  If you are updating a GTK widget, wrap the call with
``GLib.idle_add()``.

Usage (standalone CLI test)
---------------------------
    python -m src.discovery.mdns_scanner
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Optional

try:
    from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

from src.models.device import Device

log = logging.getLogger(__name__)

# ── Service types we browse for ───────────────────────────────────────────────

SERVICE_TYPES: dict[str, str] = {
    "_epson._tcp.local.":   "epson",
    "_eshare._tcp.local.":  "eshare",
    "_http._tcp.local.":    "generic",  # further filtered by TXT records
    "_printer._tcp.local.": "epson",    # Epson sometimes uses this
}

# Keywords in mDNS names / TXT records that hint at EShare displays
ESHARE_KEYWORDS = {"eshare", "screen", "cast", "display", "receiver"}

# Keywords for Epson projectors
EPSON_KEYWORDS = {"epson", "projector", "pj", "eb-", "ex-", "powerlite"}


def _classify_generic(info: "ServiceInfo") -> str:
    """
    For ``_http._tcp.local.`` entries we don't know the type upfront.
    Try to determine it from the service name and TXT properties.
    """
    name_lower = info.name.lower()
    props = {k.decode(): v.decode() for k, v in (info.properties or {}).items()
             if isinstance(k, bytes) and isinstance(v, bytes)}
    combined = name_lower + " ".join(props.values()).lower()

    if any(kw in combined for kw in EPSON_KEYWORDS):
        return "epson"
    if any(kw in combined for kw in ESHARE_KEYWORDS):
        return "eshare"
    return "generic"


def _device_from_info(info: "ServiceInfo", default_type: str) -> Optional[Device]:
    """Convert a zeroconf ServiceInfo into a Device object, or None on error."""
    addresses = info.parsed_addresses()
    if not addresses:
        return None

    # Filter out loopback and IPv6
    ipv4 = [a for a in addresses if ":" not in a and not a.startswith("127.")]
    ip = ipv4[0] if ipv4 else addresses[0]

    # Decode TXT record
    props: dict = {}
    for k, v in (info.properties or {}).items():
        try:
            key = k.decode() if isinstance(k, bytes) else str(k)
            val = v.decode() if isinstance(v, bytes) else str(v)
            props[key] = val
        except Exception:
            pass

    device_type = (
        _classify_generic(info)
        if default_type == "generic"
        else default_type
    )

    # Determine capabilities from device type
    capabilities: list[str] = []
    if device_type == "epson":
        capabilities = ["escvpnet", "rtp_recv"]
    elif device_type == "eshare":
        cap_str = props.get("cap", "")
        if "webcast" in cap_str:
            capabilities.append("webcast")
        if "rtp" in cap_str:
            capabilities.append("rtp_recv")
        capabilities.append("eshare_app")

    # Friendly name: strip service type suffix from the full DNS name
    friendly = info.name
    for svc_type in SERVICE_TYPES:
        friendly = friendly.replace(f".{svc_type}", "").replace(svc_type, "")
    friendly = friendly.strip(".")

    return Device(
        name=friendly or info.server or ip,
        ip=ip,
        port=info.port,
        device_type=device_type,
        capabilities=capabilities,
        metadata=props,
        discovery_source="mdns",
    )


# ── ServiceListener implementation ────────────────────────────────────────────

class _ProjectionListener(ServiceListener):
    """
    Zeroconf ServiceListener that converts events to Device callbacks.
    One instance handles all watched service types.
    """

    def __init__(
        self,
        zc: "Zeroconf",
        on_found: Callable[[Device], None],
        on_lost:  Callable[[str, int], None],
        default_type: str,
    ) -> None:
        self._zc = zc
        self._on_found = on_found
        self._on_lost  = on_lost
        self._default_type = default_type
        self._known: dict[str, Device] = {}   # name → Device

    # zeroconf calls these methods from its own thread
    def add_service(self, zc: "Zeroconf", svc_type: str, name: str) -> None:
        info = zc.get_service_info(svc_type, name, timeout=3000)
        if info is None:
            log.debug("mDNS: add_service - could not resolve info for %s", name)
            return
        device = _device_from_info(info, self._default_type)
        if device is None:
            return
        self._known[name] = device
        log.info("mDNS: found  %r  (%s)  %s", device.name, device.device_type, device.address)
        self._on_found(device)

    def update_service(self, zc: "Zeroconf", svc_type: str, name: str) -> None:
        # Re-resolve and emit an update as a new found event
        self.add_service(zc, svc_type, name)

    def remove_service(self, zc: "Zeroconf", svc_type: str, name: str) -> None:
        device = self._known.pop(name, None)
        if device:
            log.info("mDNS: lost   %r  (%s)", device.name, device.address)
            self._on_lost(device.ip, device.port)


# ── Public scanner class ──────────────────────────────────────────────────────

class MdnsScanner:
    """
    Continuously browses mDNS for projection-capable devices.

    Parameters
    ----------
    on_found:
        Called with a :class:`~src.models.device.Device` whenever a new
        device is discovered or updated.  May be called from a background
        thread - use ``GLib.idle_add()`` if updating the GTK UI.
    on_lost:
        Called with ``(ip: str, port: int)`` when a device disappears.
    service_types:
        Override the default dict of ``{svc_type: device_type}`` pairs to
        browse.  Useful for unit testing with a custom service type.
    """

    def __init__(
        self,
        on_found: Callable[[Device], None],
        on_lost:  Callable[[str, int], None],
        service_types: Optional[dict[str, str]] = None,
    ) -> None:
        if not HAS_ZEROCONF:
            raise RuntimeError(
                "zeroconf is not installed.  Run: pip install zeroconf"
            )
        self._on_found = on_found
        self._on_lost  = on_lost
        self._service_types = service_types or SERVICE_TYPES
        self._zc: Optional[Zeroconf] = None
        self._browsers: list[ServiceBrowser] = []
        self._running = False

    def start(self) -> None:
        """Start browsing in the background (non-blocking)."""
        if self._running:
            return
        self._running = True
        self._zc = Zeroconf()
        log.info("mDNS scanner started - watching %d service type(s)",
                 len(self._service_types))

        for svc_type, default_type in self._service_types.items():
            listener = _ProjectionListener(
                zc=self._zc,
                on_found=self._on_found,
                on_lost=self._on_lost,
                default_type=default_type,
            )
            browser = ServiceBrowser(self._zc, svc_type, listener)
            self._browsers.append(browser)
            log.debug("mDNS: browsing %s (default_type=%s)", svc_type, default_type)

    def stop(self) -> None:
        """Unregister all browsers and shut down the Zeroconf instance."""
        if not self._running:
            return
        self._running = False
        for browser in self._browsers:
            browser.cancel()
        self._browsers.clear()
        if self._zc:
            self._zc.close()
            self._zc = None
        log.info("mDNS scanner stopped.")

    def __enter__(self) -> "MdnsScanner":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


# ── Standalone CLI ────────────────────────────────────────────────────────────

def _cli_on_found(device: Device) -> None:
    print(
        f"  [+] {device.name:<30}  {device.device_type:<8}  "
        f"{device.ip}:{device.port}  caps={device.capabilities}"
    )


def _cli_on_lost(ip: str, port: int) -> None:
    print(f"  [-] Lost device at {ip}:{port}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s")
    print("Scanning for projectors and displays via mDNS …  (Ctrl+C to stop)\n")

    scanner = MdnsScanner(on_found=_cli_on_found, on_lost=_cli_on_lost)
    scanner.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        scanner.stop()
        print("\nDone.")
