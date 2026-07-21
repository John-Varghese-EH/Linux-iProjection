"""
test_epson_control.py — Unit tests for ESC/VP.net and PJLink controllers
=========================================================================

Tests use a real asyncio TCP server (127.0.0.1 on a random port) to
simulate the projector.  This exercises the full protocol stack without
any mocking.

Run with:
    pytest tests/test_epson_control.py -v
"""

from __future__ import annotations

import asyncio
import threading
import unittest

from src.control.epson_controller import (
    EpsonController,
    HANDSHAKE_BYTES,
    ProjectorStatus,
)
from src.control.pjlink_controller import (
    PJLinkController,
    POWER_STATES,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fake ESC/VP.net server (asyncio)
# ──────────────────────────────────────────────────────────────────────────────

class FakeEpsonServer:
    """
    Minimal asyncio TCP server that speaks ESC/VP.net for unit testing.
    Tracks received commands so tests can assert on them.
    """

    def __init__(self) -> None:
        self.received: list[str] = []
        self._server = None
        self._host   = "127.0.0.1"
        self._port   = 0    # assigned by OS

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle, self._host, 0
        )
        self._port = self._server.sockets[0].getsockname()[1]
        asyncio.get_event_loop().create_task(self._server.serve_forever())
        return self._port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        # Send handshake
        writer.write(HANDSHAKE_BYTES)
        await writer.drain()

        # Eat client handshake
        await reader.read(16)

        buf = b""
        while True:
            chunk = await reader.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                self.received.append(cmd)
                resp = self._respond(cmd) + "\r\n"
                writer.write(resp.encode())
                await writer.drain()

    @staticmethod
    def _respond(cmd: str) -> str:
        if cmd == "PWR ON":  return "PWR=01"
        if cmd == "PWR OFF": return "PWR=00"
        if cmd in ("PWR?", "PWR ON?"): return "PWR=01"
        if cmd.startswith("SOURCE "):  return f"SOURCE={cmd.split()[1]}"
        if cmd == "SOURCE?": return "SOURCE=30"
        if cmd == "LAMP?":   return "LAMP=1234 01"
        if cmd == "ERR?":    return "ERR=00"
        if cmd == "SNO?":    return "SNO=TESTMODEL"
        return "ERR=01"


# ──────────────────────────────────────────────────────────────────────────────
# ESC/VP.net tests
# ──────────────────────────────────────────────────────────────────────────────

class TestEpsonController(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.server = FakeEpsonServer()
        self.port   = await self.server.start()
        self.ctl    = EpsonController("127.0.0.1", self.port)
        await self.ctl.connect()

    async def asyncTearDown(self) -> None:
        await self.ctl.disconnect()
        await self.server.stop()

    # ── Handshake ──────────────────────────────────────────────────────────

    async def test_connect_sets_connected(self) -> None:
        self.assertTrue(self.ctl.connected)

    # ── Power ──────────────────────────────────────────────────────────────

    async def test_power_on_sends_command(self) -> None:
        resp = await self.ctl.power_on()
        self.assertIn("PWR ON", self.server.received)
        self.assertEqual(resp, "PWR=01")

    async def test_power_off_sends_command(self) -> None:
        resp = await self.ctl.power_off()
        self.assertIn("PWR OFF", self.server.received)
        self.assertEqual(resp, "PWR=00")

    async def test_query_power(self) -> None:
        state = await self.ctl.query_power()
        self.assertEqual(state, "01")

    # ── Source ─────────────────────────────────────────────────────────────

    async def test_set_input(self) -> None:
        resp = await self.ctl.set_input("30")
        self.assertTrue(any("SOURCE 30" in c for c in self.server.received))
        self.assertIn("SOURCE=30", resp)

    async def test_query_source(self) -> None:
        source = await self.ctl.query_source()
        self.assertEqual(source, "30")

    # ── Status ─────────────────────────────────────────────────────────────

    async def test_query_status_returns_dataclass(self) -> None:
        status = await self.ctl.query_status()
        self.assertIsInstance(status, ProjectorStatus)
        self.assertEqual(status.power, "01")
        self.assertEqual(status.source, "30")
        self.assertEqual(status.lamp_hours, 1234)
        self.assertEqual(status.model, "TESTMODEL")

    async def test_query_lamp_hours(self) -> None:
        hours = await self.ctl.query_lamp_hours()
        self.assertEqual(hours, 1234)

    # ── Raw command ────────────────────────────────────────────────────────

    async def test_send_raw(self) -> None:
        resp = await self.ctl.send_raw("SNO?")
        self.assertEqual(resp, "SNO=TESTMODEL")

    # ── Context manager ────────────────────────────────────────────────────

    async def test_context_manager(self) -> None:
        await self.ctl.disconnect()   # disconnect the one from setUp first
        server2 = FakeEpsonServer()
        port2   = await server2.start()
        async with EpsonController("127.0.0.1", port2) as ctl:
            self.assertTrue(ctl.connected)
            resp = await ctl.power_on()
            self.assertIn("PWR=01", resp)
        self.assertFalse(ctl.connected)
        await server2.stop()
        # Re-connect for tearDown
        self.ctl = EpsonController("127.0.0.1", self.port)
        await self.ctl.connect()


# ──────────────────────────────────────────────────────────────────────────────
# Fake PJLink server (asyncio)
# ──────────────────────────────────────────────────────────────────────────────

class FakePJLinkServer:
    """Minimal PJLink Class 1 server for testing."""

    def __init__(self, require_auth: bool = False, password: str = "") -> None:
        self.received: list[str] = []
        self._require_auth = require_auth
        self._password     = password
        self._server       = None
        self._port         = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self._port   = self._server.sockets[0].getsockname()[1]
        asyncio.get_event_loop().create_task(self._server.serve_forever())
        return self._port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer) -> None:
        if self._require_auth:
            writer.write(b"%1PJLINK 1 TESTSALT\r")
        else:
            writer.write(b"%1PJLINK 0\r")
        await writer.drain()

        while True:
            line = await reader.readline()
            if not line:
                break
            cmd_str = line.decode("ascii", errors="replace").strip()
            # Strip auth hash if present (it's 32 hex chars before the %)
            if cmd_str and not cmd_str.startswith("%"):
                cmd_str = cmd_str[32:]
            self.received.append(cmd_str)
            resp = self._respond(cmd_str) + "\r"
            writer.write(resp.encode())
            await writer.drain()

    @staticmethod
    def _respond(cmd: str) -> str:
        if "POWR 1"  in cmd: return "%1POWR=OK"
        if "POWR 0"  in cmd: return "%1POWR=OK"
        if "POWR ?"  in cmd: return "%1POWR=1"
        if "INPT ?"  in cmd: return "%1INPT=31"
        if "INPT 31" in cmd: return "%1INPT=OK"
        if "LAMP ?"  in cmd: return "%1LAMP=2000 1"
        if "ERST ?"  in cmd: return "%1ERST=000000"
        if "NAME ?"  in cmd: return "%1NAME=TestProjector"
        if "INF1 ?"  in cmd: return "%1INF1=TestMaker"
        if "INF2 ?"  in cmd: return "%1INF2=EB-X39"
        if "AVMT"    in cmd: return "%1AVMT=OK"
        return "%1ERR3"


# ──────────────────────────────────────────────────────────────────────────────
# PJLink controller tests
# ──────────────────────────────────────────────────────────────────────────────

class TestPJLinkController(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.server = FakePJLinkServer()
        self.port   = await self.server.start()
        self.ctl    = PJLinkController("127.0.0.1", self.port)
        await self.ctl.connect()

    async def asyncTearDown(self) -> None:
        await self.ctl.disconnect()
        await self.server.stop()

    async def test_connect_sets_connected(self) -> None:
        self.assertTrue(self.ctl.connected)

    async def test_power_on(self) -> None:
        resp = await self.ctl.power_on()
        self.assertIn("OK", resp)

    async def test_query_power(self) -> None:
        state = await self.ctl.query_power()
        self.assertEqual(state, "1")

    async def test_query_input(self) -> None:
        src = await self.ctl.query_input()
        self.assertEqual(src, "31")

    async def test_set_input(self) -> None:
        resp = await self.ctl.set_input("31")
        self.assertIn("OK", resp)

    async def test_query_status_full(self) -> None:
        from src.control.pjlink_controller import PJLinkStatus
        status = await self.ctl.query_status()
        self.assertIsInstance(status, PJLinkStatus)
        self.assertEqual(status.power, "1")
        self.assertEqual(status.power_label, "On")
        self.assertEqual(status.lamp_hours, 2000)
        self.assertTrue(status.lamp_on)
        self.assertEqual(status.errors, [])
        self.assertEqual(status.name, "TestProjector")
        self.assertEqual(status.model, "EB-X39")

    async def test_av_mute(self) -> None:
        resp = await self.ctl.set_av_mute(video=True, audio=True)
        self.assertIn("OK", resp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
