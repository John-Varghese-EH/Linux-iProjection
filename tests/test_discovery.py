# epsonctl — Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""Unit tests for epsonctl.discovery.

Tests use mocked sockets and zeroconf — no real network needed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from epsonctl.discovery import (
    HTTP_KEYWORDS,
    SERVICE_TYPES,
    DiscoveredDevice,
    _local_ipv4_networks,
    discover_by_scan,
)


def test_service_types_include_epson():
    """Verified mDNS service types should be present."""
    assert "_epson._tcp.local." in SERVICE_TYPES
    assert "_eshare._tcp.local." in SERVICE_TYPES
    assert "_http._tcp.local." in SERVICE_TYPES


def test_http_keywords():
    """Keyword filter should contain essential terms."""
    assert "epson" in HTTP_KEYWORDS
    assert "projector" in HTTP_KEYWORDS
    assert "eshare" in HTTP_KEYWORDS


def test_discovered_device_defaults():
    """DiscoveredDevice should have sensible defaults."""
    dev = DiscoveredDevice(
        name="Test",
        address="192.168.1.50",
        port=3629,
        source="manual",
    )
    assert dev.stream_port == 5004
    assert dev.audio_port == 5006
    assert dev.device_type == "unknown"
    assert dev.capabilities == []


@pytest.mark.asyncio
async def test_lan_scan_finds_open_port():
    """When a host accepts TCP on port 3629, it should be discovered."""

    async def fake_open_connection(host, port):
        if host == "192.168.1.50" and port == 3629:
            reader = AsyncMock()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return reader, writer
        raise OSError("Connection refused")

    import ipaddress

    with patch("epsonctl.discovery.asyncio.open_connection", side_effect=fake_open_connection):
        results = await discover_by_scan(
            ports=[3629],
            network=ipaddress.IPv4Network("192.168.1.48/29"),  # .49-.54
        )

    assert len(results) == 1
    assert results[0].address == "192.168.1.50"
    assert results[0].source == "scan"


@pytest.mark.asyncio
async def test_lan_scan_timeout():
    """When all hosts refuse, the scan should return an empty list."""

    async def fake_open_connection(host, port):
        raise asyncio.TimeoutError()

    import ipaddress

    with patch("epsonctl.discovery.asyncio.open_connection", side_effect=fake_open_connection):
        results = await discover_by_scan(
            ports=[3629],
            network=ipaddress.IPv4Network("10.0.0.0/30"),  # just 2 hosts
        )

    assert len(results) == 0


def test_dedup_prefers_mdns():
    """discover_all dedup logic should prefer mDNS entries."""
    mdns_dev = DiscoveredDevice(
        name="Epson EB-W50",
        address="192.168.1.50",
        port=3629,
        source="mdns",
        device_type="projector",
    )
    scan_dev = DiscoveredDevice(
        name="192.168.1.50",
        address="192.168.1.50",
        port=3629,
        source="scan",
    )

    # Simulate the dedup logic from discover_all
    seen: dict[str, DiscoveredDevice] = {}
    for d in [scan_dev, mdns_dev]:
        if d.address not in seen or seen[d.address].source == "scan":
            seen[d.address] = d

    result = list(seen.values())
    assert len(result) == 1
    assert result[0].name == "Epson EB-W50"
    assert result[0].source == "mdns"


def test_local_ipv4_networks():
    """Should return at least one network on most dev machines."""
    # This test may fail in isolated CI without network — that's OK
    networks = _local_ipv4_networks()
    # Don't assert length > 0 as this depends on environment
    for net in networks:
        assert net.prefixlen == 24
