"""
linux-iprojection: PJLink Protocol Controller
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

PJLink is an open, standardised projector control protocol (TCP port 4352).
Many Epson models that do NOT expose ESC/VP.net still support PJLink.

Usage:
    import asyncio
    from .pjlink import PJLinkController

    async def main():
        async with PJLinkController("192.168.1.100") as ctl:
            await ctl.power_on()
            status = await ctl.query_status()
            print(status)

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ── Protocol constants ────────────────────────────────────────────────────────

PJLINK_PORT = 4352
CONNECT_TIMEOUT = 10.0
COMMAND_TIMEOUT = 5.0
KEEPALIVE_INTERVAL = 45.0

# PJLink power state codes
POWER_STATES = {"0": "Standby", "1": "On", "2": "Cooling", "3": "Warming"}

# PJLink input codes → friendly names (Class 1)
INPUT_NAMES: dict[str, str] = {
    "11": "RGB 1",
    "12": "RGB 2",
    "21": "Video 1",
    "22": "Video 2",
    "31": "HDMI 1",
    "32": "HDMI 2",
    "41": "Storage",
    "51": "Network",
}

# ERST error positions
ERST_LABELS = ["Fan", "Lamp", "Temperature", "Cover", "Filter", "Other"]


@dataclass
class PJLinkStatus:
    power: str = "?"
    input_code: str = "?"
    lamp_hours: int = 0
    lamp_on: bool = False
    errors: list[str] = None  # type: ignore[assignment]
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    pjlink_class: int = 1
    serial: str | None = None
    input_resolution: str | None = None
    filter_hours: int | None = None
    frozen: bool | None = None
    available_inputs: list | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def power_label(self) -> str:
        return POWER_STATES.get(self.power, self.power)

    @property
    def input_label(self) -> str:
        return INPUT_NAMES.get(self.input_code, self.input_code)


# ──────────────────────────────────────────────────────────────────────────────
# Controller
# ──────────────────────────────────────────────────────────────────────────────


class PJLinkController:
    """
    Asyncio PJLink Class 1/2 client.

    Parameters:
    host:
        Projector IP address.
    port:
        PJLink port (default 4352).
    password:
        PJLink password if authentication is enabled on the projector.
        Leave empty (default) for unauthenticated connections.
    pjlink_class:
        1 (default) or 2.  Class 2 enables SRCH, SNUM, and extended inputs.
    """

    def __init__(
        self,
        host: str,
        port: int = PJLINK_PORT,
        password: str = "",
        pjlink_class: int = 1,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._class = pjlink_class
        self._prefix = f"%{pjlink_class}"

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._auth_hash: str = ""  # MD5(salt+password) or ""
        self._lock = asyncio.Lock()
        self._keepalive_task: Optional[asyncio.Task] = None
        self.connected = False

    # ── Connection lifecycle ──────────────────────────────────────────────

    async def connect(self) -> None:
        """Open TCP connection and handle PJLink authentication greeting."""
        log.info("Connecting to PJLink projector at %s:%d …", self._host, self._port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=CONNECT_TIMEOUT,
        )

        # Read greeting line: "%1PJLINK 0\r" or "%1PJLINK 1 <salt>\r"
        greeting = (
            (await asyncio.wait_for(self._reader.readline(), timeout=CONNECT_TIMEOUT))
            .decode("ascii", errors="replace")
            .strip()
        )

        log.debug("PJLink greeting: %r", greeting)

        if "PJLINK 1" in greeting:
            # Authentication required - derive MD5 hash
            parts = greeting.split()
            salt = parts[-1] if len(parts) >= 3 else ""
            if not self._password:
                raise ConnectionError(f"Projector at {self._host} requires a PJLink password.")
            self._auth_hash = hashlib.md5((salt + self._password).encode("utf-8")).hexdigest()
            log.debug("PJLink auth hash computed (salt=%r)", salt)
        elif "PJLINK 0" in greeting:
            self._auth_hash = ""
            log.debug("PJLink: no authentication required")
        elif "ERRA" in greeting:
            raise ConnectionError(f"PJLink authentication error from {self._host}: {greeting}")
        else:
            raise ConnectionError(f"Unexpected PJLink greeting from {self._host}: {greeting!r}")

        self.connected = True
        log.info("PJLink session established with %s (class %d)", self._host, self._class)

        self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="pjlink-keepalive")

    async def disconnect(self) -> None:
        """Close the PJLink TCP session."""
        self.connected = False
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None
        log.info("PJLink disconnected from %s", self._host)

    # ── Power ─────────────────────────────────────────────────────────────

    async def power_on(self) -> str:
        return await self._command("POWR", "1")

    async def power_off(self) -> str:
        return await self._command("POWR", "0")

    async def query_power(self) -> str:
        """Return raw power code: '0'=standby, '1'=on, '2'=cooling, '3'=warming."""
        resp = await self._command("POWR", "?")
        return self._extract_value(resp)

    # ── Input ─────────────────────────────────────────────────────────────

    async def set_input(self, input_code: str) -> str:
        """Set input source.  input_code e.g. '31' for HDMI 1."""
        return await self._command("INPT", input_code)

    async def query_input(self) -> str:
        resp = await self._command("INPT", "?")
        return self._extract_value(resp)

    # ── AV Mute ───────────────────────────────────────────────────────────

    async def set_av_mute(self, video: bool = False, audio: bool = False) -> str:
        """
        Control AV mute.
        PJLink mute codes: 11=video mute on, 10=off; 21=audio mute on, 20=off;
        31=both on, 30=both off.
        """
        if video and audio:
            code = "31"
        elif not video and not audio:
            code = "30"
        elif video:
            code = "11"
        else:
            code = "21"
        return await self._command("AVMT", code)

    # ── Status & Info ─────────────────────────────────────────────────────

    async def query_status(self) -> PJLinkStatus:
        """Query all available projector status fields."""
        status = PJLinkStatus()
        try:
            status.power = await self.query_power()
            status.input_code = await self.query_input()
            lamp_resp = self._extract_value(await self._command("LAMP", "?"))
            parts = lamp_resp.split()
            if parts:
                status.lamp_hours = int(parts[0]) if parts[0].isdigit() else 0
                status.lamp_on = parts[1] == "1" if len(parts) > 1 else False

            erst = self._extract_value(await self._command("ERST", "?"))
            status.errors = (
                [ERST_LABELS[i] for i, ch in enumerate(erst) if ch != "0"] if len(erst) == 6 else []
            )

            status.name = self._extract_value(await self._command("NAME", "?"))
            status.manufacturer = self._extract_value(await self._command("INF1", "?"))
            status.model = self._extract_value(await self._command("INF2", "?"))
        except Exception as exc:
            log.warning("PJLink query_status partial failure: %s", exc)
        
        try:
            status.serial = await self.get_serial()
            status.input_resolution = await self.get_input_resolution()
            status.filter_hours = await self.get_filter_hours()
            status.frozen = await self.get_freeze()
            status.available_inputs = await self.get_available_inputs()
        except Exception as exc:
            log.warning("PJLink Class 2 query_status partial failure: %s", exc)
            
        return status

    # ── Raw command ───────────────────────────────────────────────────────

    async def send_raw(self, cmd: str, value: str = "?") -> str:
        return await self._command(cmd.upper(), value)

    # ── Internals ─────────────────────────────────────────────────────────

    async def _command(self, cmd: str, value: str) -> str:
        """Send one PJLink command and return the raw response line."""
        if not self.connected or not self._writer:
            raise ConnectionError("Not connected to projector.")

        async with self._lock:
            payload = f"{self._auth_hash}{self._prefix}{cmd} {value}\r"
            log.debug("→ PJLink %s: %r", self._host, payload)
            self._writer.write(payload.encode("ascii"))
            await self._writer.drain()

            try:
                resp_bytes = await asyncio.wait_for(
                    self._reader.readline(), timeout=COMMAND_TIMEOUT
                )
                resp = resp_bytes.decode("ascii", errors="replace").strip()
                log.debug("← PJLink %s: %r", self._host, resp)
                return resp
            except asyncio.TimeoutError:
                log.warning("PJLink command %r timed out", cmd)
                return ""

    @staticmethod
    def _extract_value(resp: str) -> str:
        """
        Extract the value from a PJLink response.
        e.g. '%1POWR=1' → '1',  '%1LAMP=1500 1' → '1500 1'
        """
        if "=" in resp:
            return resp.split("=", 1)[1].strip()
        return resp

    async def _keepalive_loop(self) -> None:
        while self.connected:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self.connected:
                break
            try:
                await self._command("POWR", "?")
                log.debug("PJLink keep-alive OK")
            except Exception as exc:
                log.warning("PJLink keep-alive failed: %s", exc)
                self.connected = False
                break

    async def get_serial(self) -> str:
        """Query projector serial number (Class 2)."""
        return self._extract_value(await self._command("SNUM", "?"))

    async def get_input_resolution(self) -> str:
        """Query current input signal resolution (Class 2)."""
        return self._extract_value(await self._command("IRES", "?"))

    async def get_filter_hours(self) -> int:
        """Query filter usage hours (Class 2)."""
        resp = self._extract_value(await self._command("FILT", "?"))
        try:
            return int(resp.split()[0])
        except (ValueError, IndexError):
            return 0

    async def get_available_inputs(self) -> list[str]:
        """Query list of available input terminals (Class 2)."""
        resp = self._extract_value(await self._command("INST", "?"))
        if resp:
            return [x.strip() for x in resp.split() if x.strip()]
        return []

    async def set_freeze(self, on: bool) -> None:
        """Enable or disable freeze (Class 2)."""
        await self._command("FREZ", "1" if on else "0")

    async def get_freeze(self) -> bool:
        """Query freeze state (Class 2)."""
        resp = self._extract_value(await self._command("FREZ", "?"))
        return resp.strip() == "1"

    async def get_name(self) -> str:
        """Query projector name."""
        return self._extract_value(await self._command("NAME", "?"))

    # ── Async context manager ─────────────────────────────────────────────

    async def __aenter__(self) -> "PJLinkController":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()


# ──────────────────────────────────────────────────────────────────────────────
# Standalone CLI tester
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    )
    p = argparse.ArgumentParser(description="Interactive PJLink CLI")
    p.add_argument("host", nargs="?", default="127.0.0.1")
    p.add_argument("--port", type=int, default=PJLINK_PORT)
    p.add_argument("--password", default="")
    args = p.parse_args()

    async def _main() -> None:
        async with PJLinkController(args.host, args.port, args.password) as ctl:
            s = await ctl.query_status()
            print(f"\nProjector: {s.manufacturer} {s.model} ({s.name})")
            print(f"  Power : {s.power_label}")
            print(f"  Input : {s.input_label}")
            print(f"  Lamp  : {s.lamp_hours} h ({'on' if s.lamp_on else 'off'})")
            print(f"  Errors: {s.errors or 'none'}\n")

            loop = asyncio.get_event_loop()
            while True:
                try:
                    raw = await loop.run_in_executor(None, input, "pjlink cmd> ")
                except (EOFError, KeyboardInterrupt):
                    break
                raw = raw.strip()
                if not raw or raw.lower() in ("quit", "q"):
                    break
                parts = raw.split(None, 1)
                resp = await ctl.send_raw(parts[0], parts[1] if len(parts) > 1 else "?")
                print(f"  ← {resp!r}")

    asyncio.run(_main())
