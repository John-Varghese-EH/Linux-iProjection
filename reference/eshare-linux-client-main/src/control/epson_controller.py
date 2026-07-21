"""
epson_controller.py - Epson ESC/VP.net Control Layer
=====================================================

Manages the TCP session to an Epson projector's ESC/VP.net interface
(port 3629).  Provides async-friendly methods for power, input-select,
and status queries.

Protocol summary
----------------
1. Connect TCP to projector-ip:3629
2. Send handshake:  b'ESC/VP.net\\x10\\x03\\x00\\x00\\x00\\x00'
3. Receive echo of the same 16 bytes (projector acknowledges)
4. Send text commands terminated with '\\r'
5. Receive text responses terminated with '\\r\\n' or ':'
6. Repeat; keep-alive every 30 s with 'PWR?\\r'

Known source codes
------------------
  10 = VGA 1        20 = VGA 2
  30 = HDMI 1       A0 = HDMI 2
  41 = Video        42 = S-Video
  52 = LAN          53 = WirelessLAN

Reference
---------
Epson ESC/VP.net Command Reference (publicly available from Epson support pages)

Usage
-----
    import asyncio
    from src.control.epson_controller import EpsonController

    async def main():
        ctl = EpsonController("192.168.1.100")
        await ctl.connect()
        await ctl.power_on()
        await ctl.set_input("52")  # LAN input
        status = await ctl.query_status()
        print(status)
        await ctl.disconnect()

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ── Protocol constants ────────────────────────────────────────────────────────

ESCVPNET_PORT      = 3629
HANDSHAKE_BYTES    = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"
KEEPALIVE_INTERVAL = 30.0   # seconds
COMMAND_TIMEOUT    = 5.0    # seconds per command round-trip
CONNECT_TIMEOUT    = 10.0   # seconds for initial TCP connect

# Source code → friendly name mapping
SOURCE_NAMES: dict[str, str] = {
    "10": "VGA 1",
    "20": "VGA 2",
    "30": "HDMI 1",
    "A0": "HDMI 2",
    "41": "Video",
    "42": "S-Video",
    "52": "LAN",
    "53": "Wireless LAN",
}


@dataclass
class ProjectorStatus:
    power:      str = "unknown"   # '01'=on, '00'=off, '02'=warming, '03'=cooling
    source:     str = "unknown"
    lamp_hours: int = 0
    errors:     str = "00"
    model:      str = ""

    @property
    def power_label(self) -> str:
        return {"01": "On", "00": "Off", "02": "Warming", "03": "Cooling"}.get(
            self.power, self.power
        )

    @property
    def source_label(self) -> str:
        return SOURCE_NAMES.get(self.source, self.source)


# ──────────────────────────────────────────────────────────────────────────────
# Controller
# ──────────────────────────────────────────────────────────────────────────────

class EpsonController:
    """
    Asyncio-based ESC/VP.net client for Epson projectors.

    All public methods are coroutines and must be awaited.
    The class is safe to use as an async context manager::

        async with EpsonController("192.168.1.100") as ctl:
            await ctl.power_on()
    """

    def __init__(self, host: str, port: int = ESCVPNET_PORT) -> None:
        self._host   = host
        self._port   = port
        self._reader: Optional[asyncio.StreamReader]  = None
        self._writer: Optional[asyncio.StreamWriter]  = None
        self._lock   = asyncio.Lock()     # one command at a time
        self._keepalive_task: Optional[asyncio.Task] = None
        self.connected = False

    # ── Connection lifecycle ──────────────────────────────────────────────

    async def connect(self) -> None:
        """Open TCP connection and perform the ESC/VP.net handshake."""
        log.info("Connecting to Epson projector at %s:%d …", self._host, self._port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=CONNECT_TIMEOUT,
        )

        # Send handshake
        self._writer.write(HANDSHAKE_BYTES)
        await self._writer.drain()

        # Expect 16-byte acknowledgement
        ack = await asyncio.wait_for(self._reader.read(16), timeout=CONNECT_TIMEOUT)
        if not ack.startswith(b"ESC/VP.net"):
            raise ConnectionError(
                f"Unexpected handshake response from {self._host}: {ack!r}"
            )

        self.connected = True
        log.info("ESC/VP.net session established with %s", self._host)

        # Start keep-alive heartbeat
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(), name="escvpnet-keepalive"
        )

    async def disconnect(self) -> None:
        """Gracefully close the TCP connection."""
        self.connected = False
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None

        log.info("Disconnected from %s", self._host)

    # ── Power ─────────────────────────────────────────────────────────────

    async def power_on(self) -> str:
        """Send PWR ON command. Returns projector response."""
        return await self._command("PWR ON")

    async def power_off(self) -> str:
        """Send PWR OFF command (standby). Returns projector response."""
        return await self._command("PWR OFF")

    async def query_power(self) -> str:
        """Return the raw power state code ('01', '00', etc.)."""
        resp = await self._command("PWR?")
        # Response format: "PWR=01"
        return resp.split("=", 1)[-1].strip() if "=" in resp else resp

    # ── Input / Source ────────────────────────────────────────────────────

    async def set_input(self, source_code: str) -> str:
        """
        Switch the projector input.

        :param source_code: Hex string like '30' (HDMI1) or '52' (LAN).
        """
        return await self._command(f"SOURCE {source_code.upper()}")

    async def query_source(self) -> str:
        """Return the raw source code of the current input."""
        resp = await self._command("SOURCE?")
        return resp.split("=", 1)[-1].strip() if "=" in resp else resp

    # ── Status ────────────────────────────────────────────────────────────

    async def query_status(self) -> ProjectorStatus:
        """Query power, source, lamp, and error state. Returns ProjectorStatus."""
        status = ProjectorStatus()
        try:
            status.power  = await self.query_power()
            status.source = await self.query_source()
            lamp_resp     = await self._command("LAMP?")
            # Response format: "LAMP=1234 01" (hours + status)
            if "=" in lamp_resp:
                parts = lamp_resp.split("=", 1)[1].split()
                status.lamp_hours = int(parts[0]) if parts else 0
            err_resp      = await self._command("ERR?")
            status.errors = err_resp.split("=", 1)[-1].strip() if "=" in err_resp else "?"
            sno_resp      = await self._command("SNO?")
            status.model  = sno_resp.split("=", 1)[-1].strip() if "=" in sno_resp else ""
        except Exception as exc:
            log.warning("query_status partial failure: %s", exc)
        return status

    async def query_lamp_hours(self) -> int:
        """Return lamp hours as an integer."""
        resp = await self._command("LAMP?")
        try:
            return int(resp.split("=", 1)[1].split()[0])
        except (IndexError, ValueError):
            return 0

    # ── Raw command interface ─────────────────────────────────────────────

    async def send_raw(self, command: str) -> str:
        """
        Send an arbitrary ESC/VP.net command string and return the response.
        The \\r terminator is added automatically.
        """
        return await self._command(command)

    # ── Internals ─────────────────────────────────────────────────────────

    async def _command(self, cmd: str) -> str:
        """
        Send a single command and read the response.
        Serialised via asyncio.Lock so concurrent callers queue up safely.
        """
        if not self.connected or not self._writer:
            raise ConnectionError("Not connected to projector.")

        async with self._lock:
            payload = (cmd + "\r").encode("ascii")
            log.debug("→ %s: %r", self._host, payload)
            self._writer.write(payload)
            await self._writer.drain()

            # Read until '\r' or '\n'
            try:
                resp_bytes = await asyncio.wait_for(
                    self._reader.readline(), timeout=COMMAND_TIMEOUT
                )
                resp = resp_bytes.decode("ascii", errors="replace").strip()
                log.debug("← %s: %r", self._host, resp)
                return resp
            except asyncio.TimeoutError:
                log.warning("Command %r timed out", cmd)
                return ""

    async def _keepalive_loop(self) -> None:
        """Send a PWR? heartbeat every KEEPALIVE_INTERVAL seconds."""
        while self.connected:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self.connected:
                break
            try:
                await self._command("PWR?")
                log.debug("Keep-alive OK")
            except Exception as exc:
                log.warning("Keep-alive failed: %s - marking disconnected", exc)
                self.connected = False
                break

    # ── Async context manager ─────────────────────────────────────────────

    async def __aenter__(self) -> "EpsonController":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()


# ──────────────────────────────────────────────────────────────────────────────
# Standalone CLI tester
# ──────────────────────────────────────────────────────────────────────────────

async def _cli(host: str, port: int) -> None:
    import readline  # noqa: F401 - enables line editing in interactive mode

    print(f"Connecting to {host}:{port} …")
    ctl = EpsonController(host, port)

    try:
        await ctl.connect()
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return

    status = await ctl.query_status()
    print(f"\nProjector status:\n"
          f"  Power : {status.power_label}\n"
          f"  Input : {status.source_label}\n"
          f"  Lamp  : {status.lamp_hours} h\n"
          f"  Errors: {status.errors}\n"
          f"  Model : {status.model}\n")

    print("Interactive mode - type ESC/VP.net commands, 'quit' to exit.\n")
    loop = asyncio.get_event_loop()
    while True:
        try:
            cmd = await loop.run_in_executor(None, input, "epson> ")
        except (EOFError, KeyboardInterrupt):
            break
        cmd = cmd.strip()
        if not cmd:
            continue
        if cmd.lower() in ("quit", "exit", "q"):
            break
        resp = await ctl.send_raw(cmd)
        print(f"  ← {resp!r}")

    await ctl.disconnect()
    print("Disconnected.")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s")
    p = argparse.ArgumentParser(description="Interactive ESC/VP.net CLI")
    p.add_argument("host", nargs="?", default="127.0.0.1")
    p.add_argument("--port", type=int, default=ESCVPNET_PORT)
    args = p.parse_args()
    asyncio.run(_cli(args.host, args.port))
