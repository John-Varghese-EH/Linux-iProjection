"""
Device dataclass — the central data model for any discovered receiver.

Every discovery backend (mDNS, SSDP, network scan) produces Device objects.
The GUI and control/streaming layers consume them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal


DeviceType = Literal["epson", "eshare", "miracast", "generic"]


@dataclass
class Device:
    """Represents a discovered projection target on the local network."""

    # ── Core identity ──────────────────────────────────────────────────────
    name: str
    """Human-readable display name (from mDNS, SSDP, or user-assigned)."""

    ip: str
    """IPv4 address of the device."""

    port: int
    """Primary control/stream port (e.g. 3629 for ESC/VP.net, 5004 for RTP)."""

    device_type: DeviceType = "generic"
    """Categorises the device so the right control/streaming driver is used."""

    # ── Capabilities ───────────────────────────────────────────────────────
    capabilities: list[str] = field(default_factory=list)
    """
    Feature flags detected from discovery records.
    Known values:
      "escvpnet"   — Epson ESC/VP.net control (TCP 3629)
      "pjlink"     — PJLink protocol (TCP 4352)
      "rtp_recv"   — Device can receive an RTP stream
      "rtsp_recv"  — Device can receive an RTSP stream
      "webcast"    — EShare WebCast HTTP push mode
      "eshare_app" — EShare official client integration
    """

    # ── Stream endpoint ────────────────────────────────────────────────────
    stream_port: int = 5004
    """UDP port on the receiver side for the RTP video stream."""

    audio_port: int = 5006
    """UDP port on the receiver side for the RTP audio stream."""

    # ── State ──────────────────────────────────────────────────────────────
    is_connected: bool = False
    """True while an active projection session is running."""

    is_streaming: bool = False
    """True while GStreamer pipeline is pushing data."""

    # ── Discovery metadata ─────────────────────────────────────────────────
    metadata: dict = field(default_factory=dict)
    """
    Raw key/value pairs from discovery:
    - mDNS: TXT record dictionary
    - SSDP: parsed response headers
    - Network scan: {'source': 'port_scan'}
    """

    discovery_source: str = "unknown"
    """Which backend found this device: 'mdns', 'ssdp', 'scan', 'manual'."""

    last_seen: float = field(default_factory=time.monotonic)
    """Monotonic timestamp of the most recent discovery advertisement."""

    # ── Helpers ────────────────────────────────────────────────────────────

    def has_capability(self, cap: str) -> bool:
        """Return True if the device reports the given capability string."""
        return cap in self.capabilities

    @property
    def display_label(self) -> str:
        """Short label shown in the device list: 'Name (type)'."""
        return f"{self.name} ({self.device_type})"

    @property
    def address(self) -> str:
        """'ip:port' string for logging and display."""
        return f"{self.ip}:{self.port}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Device):
            return NotImplemented
        # Two devices with the same IP+port are considered the same device.
        return self.ip == other.ip and self.port == other.port

    def __hash__(self) -> int:
        return hash((self.ip, self.port))

    def __repr__(self) -> str:
        return (
            f"Device(name={self.name!r}, ip={self.ip!r}, port={self.port}, "
            f"type={self.device_type!r}, connected={self.is_connected})"
        )
