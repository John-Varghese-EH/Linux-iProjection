"""
test_discovery.py — Unit tests for the discovery backends
=========================================================

Tests run without real network hardware using either:
  - A real local mock_receiver.py instance (integration test)
  - Mocked zeroconf / socket objects (pure unit test)

Run with:
    pytest tests/test_discovery.py -v
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from src.models.device import Device
from src.discovery.ssdp_scanner import (
    SsdpScanner,
    _parse_ssdp_response,
    _classify_ssdp,
    _device_from_ssdp,
)
from src.discovery.network_scanner import (
    NetworkScanner,
    _probe_host,
    _check_and_build_device,
    _get_local_subnets,
)


# ──────────────────────────────────────────────────────────────────────────────
# Device model tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDevice(unittest.TestCase):

    def test_basic_creation(self):
        d = Device(name="TestProj", ip="192.168.1.10", port=3629, device_type="epson")
        self.assertEqual(d.name, "TestProj")
        self.assertEqual(d.ip, "192.168.1.10")
        self.assertFalse(d.is_connected)

    def test_has_capability(self):
        d = Device(name="P", ip="1.2.3.4", port=3629,
                   capabilities=["escvpnet", "rtp_recv"])
        self.assertTrue(d.has_capability("escvpnet"))
        self.assertFalse(d.has_capability("pjlink"))

    def test_equality_by_ip_port(self):
        d1 = Device(name="A", ip="10.0.0.1", port=3629)
        d2 = Device(name="B", ip="10.0.0.1", port=3629)
        self.assertEqual(d1, d2)

    def test_display_label(self):
        d = Device(name="Epson EB-X39", ip="10.0.0.2", port=3629, device_type="epson")
        self.assertIn("epson", d.display_label)

    def test_address(self):
        d = Device(name="P", ip="192.168.1.5", port=5004)
        self.assertEqual(d.address, "192.168.1.5:5004")


# ──────────────────────────────────────────────────────────────────────────────
# SSDP scanner tests
# ──────────────────────────────────────────────────────────────────────────────

EPSON_SSDP_RESPONSE = b"""\
HTTP/1.1 200 OK\r\n\
CACHE-CONTROL: max-age=1800\r\n\
DATE: Mon, 20 Apr 2026 06:00:00 GMT\r\n\
EXT:\r\n\
LOCATION: http://192.168.1.100:80/description.xml\r\n\
SERVER: Linux/5.15 UPnP/1.1 Epson-Projector/2.0\r\n\
ST: urn:schemas-upnp-org:device:Basic:1\r\n\
USN: uuid:EPSON-EB-X39-001::urn:schemas-upnp-org:device:Basic:1\r\n\
\r\n"""

ESHARE_SSDP_RESPONSE = b"""\
HTTP/1.1 200 OK\r\n\
SERVER: Linux/4.9 UPnP/1.1 EShare-Receiver/4.2\r\n\
LOCATION: http://192.168.1.200:56789/\r\n\
USN: uuid:ESHARE-DISPLAY-002::urn:eshare:display\r\n\
\r\n"""

GENERIC_SSDP_RESPONSE = b"""\
HTTP/1.1 200 OK\r\n\
SERVER: Linux/5.10 UPnP/1.1 SomeOtherDevice/1.0\r\n\
USN: uuid:random-device-xyz\r\n\
\r\n"""


class TestSsdpParsing(unittest.TestCase):

    def test_parse_epson_response(self):
        headers = _parse_ssdp_response(EPSON_SSDP_RESPONSE)
        self.assertIn("server", headers)
        self.assertIn("epson", headers["server"].lower())

    def test_classify_epson(self):
        headers = _parse_ssdp_response(EPSON_SSDP_RESPONSE)
        self.assertEqual(_classify_ssdp(headers), "epson")

    def test_classify_eshare(self):
        headers = _parse_ssdp_response(ESHARE_SSDP_RESPONSE)
        self.assertEqual(_classify_ssdp(headers), "eshare")

    def test_classify_generic_returns_none(self):
        headers = _parse_ssdp_response(GENERIC_SSDP_RESPONSE)
        self.assertIsNone(_classify_ssdp(headers))

    def test_device_from_epson_ssdp(self):
        headers = _parse_ssdp_response(EPSON_SSDP_RESPONSE)
        device = _device_from_ssdp(headers, "192.168.1.100")
        self.assertIsNotNone(device)
        self.assertEqual(device.device_type, "epson")
        self.assertIn("escvpnet", device.capabilities)

    def test_device_from_generic_returns_none(self):
        headers = _parse_ssdp_response(GENERIC_SSDP_RESPONSE)
        device = _device_from_ssdp(headers, "192.168.1.50")
        self.assertIsNone(device)


class TestSsdpScannerMocked(unittest.TestCase):
    """Test SsdpScanner sweep logic with a mocked socket."""

    def test_sweep_calls_on_found(self):
        found: list[Device] = []

        with patch("src.discovery.ssdp_scanner.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value.__enter__ = lambda s: mock_sock
            mock_sock_cls.return_value.__exit__  = MagicMock(return_value=False)

            # Simulate: one Epson response, then timeout
            mock_sock.recvfrom.side_effect = [
                (EPSON_SSDP_RESPONSE, ("192.168.1.100", 1900)),
                socket.timeout(),
            ]

            scanner = SsdpScanner(on_found=found.append, on_lost=lambda *a: None)
            scanner._sweep()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].device_type, "epson")
        self.assertEqual(found[0].ip, "192.168.1.100")


# ──────────────────────────────────────────────────────────────────────────────
# Network scanner tests
# ──────────────────────────────────────────────────────────────────────────────

class TestNetworkScanner(unittest.TestCase):

    def test_probe_host_closed_port(self):
        # Port 1 is almost certainly closed
        result = _probe_host("127.0.0.1", 1, timeout=0.2)
        self.assertFalse(result)

    def test_probe_host_open_port(self):
        """Open a real listening socket, then probe it."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 0))
            port = srv.getsockname()[1]
            srv.listen(1)
            result = _probe_host("127.0.0.1", port, timeout=1.0)
        self.assertTrue(result)

    def test_check_and_build_device_closed(self):
        # Nothing listens on port 19999 (very likely)
        with patch("src.discovery.network_scanner._probe_host", return_value=False):
            device = _check_and_build_device("10.0.0.99")
        self.assertIsNone(device)

    def test_check_and_build_device_open_escvpnet(self):
        def fake_probe(ip, port, **kw):
            return port == 3629
        with patch("src.discovery.network_scanner._probe_host", side_effect=fake_probe):
            device = _check_and_build_device("10.0.0.50")
        self.assertIsNotNone(device)
        self.assertEqual(device.ip, "10.0.0.50")
        self.assertEqual(device.port, 3629)
        self.assertEqual(device.device_type, "epson")
        self.assertIn("escvpnet", device.capabilities)

    def test_subnet_detection_returns_list(self):
        subnets = _get_local_subnets()
        self.assertIsInstance(subnets, list)
        self.assertGreater(len(subnets), 0)
        # Each entry must be a valid CIDR
        for s in subnets:
            ipaddress.IPv4Network(s, strict=False)   # should not raise

    def test_scanner_finds_mock(self):
        """
        Integration-ish: spin up a local listening socket, run a mini scan
        against 127.0.0.1 only, and confirm the scanner calls on_found.
        """
        found: list[Device] = []
        lock  = threading.Event()

        def on_found(d: Device) -> None:
            found.append(d)
            lock.set()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 3629))
            srv.listen(1)

            scanner = NetworkScanner(
                on_found=on_found,
                subnet="127.0.0.1/32",   # only scan loopback
                connect_timeout=1.0,
            )
            scanner.scan()
            lock.wait(timeout=10)
            scanner.stop()

        self.assertTrue(len(found) >= 1)
        self.assertEqual(found[0].ip, "127.0.0.1")


# ──────────────────────────────────────────────────────────────────────────────
# mDNS scanner tests (mocked — no real Zeroconf)
# ──────────────────────────────────────────────────────────────────────────────

class TestMdnsScannerMocked(unittest.TestCase):

    def test_start_stop_no_error(self):
        """Start and stop the mDNS scanner without crashing."""
        from src.discovery.mdns_scanner import MdnsScanner
        scanner = MdnsScanner(
            on_found=lambda d: None,
            on_lost=lambda ip, p: None,
        )
        scanner.start()
        time.sleep(0.2)
        scanner.stop()   # should not raise

    def test_context_manager(self):
        from src.discovery.mdns_scanner import MdnsScanner
        with MdnsScanner(
            on_found=lambda d: None,
            on_lost=lambda ip, p: None,
        ) as scanner:
            self.assertTrue(scanner._running)
        self.assertFalse(scanner._running)


if __name__ == "__main__":
    unittest.main(verbosity=2)
