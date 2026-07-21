"""
ESC/VP.net client.

Epson business/education projectors expose a TCP control service on port
3629 ("ESC/VP.net"). Before any command can be sent, the client must
complete a fixed 16-byte handshake; after that, ESC/VP21 text commands are
sent terminated by CR, and the projector replies terminated by CR + a ':'
prompt character.

Reference: Epson "ESC/VP.net Software Development Manual" section 5.4.1,
and the public ESC/VP21 command guides (PWR, SOURCE, MUTE, LAMP, etc).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

ESCVP_PORT = 3629
HANDSHAKE = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"
CMD_TERMINATOR = b"\r"
PROMPT = b":"
CONNECT_TIMEOUT = 5.0
COMMAND_TIMEOUT = 5.0


class ProjectorError(Exception):
    """Raised for handshake failures, timeouts, or ERR responses."""


class Power(str, Enum):
    ON = "01"
    OFF = "00"
    WARMUP = "02"
    COOLDOWN = "03"
    STANDBY = "04"
    ABNORMAL_STANDBY = "05"


# Common input source codes. Not every projector model supports every
# source — query `SOURCE?` / consult the model's ESC/VP21 guide to confirm.
class Source(str, Enum):
    COMPUTER1 = "11"
    COMPUTER2 = "21"
    VIDEO = "41"
    HDMI1 = "30"
    HDMI2 = "A0"
    USB = "52"
    LAN = "53"
    WIRELESS_HDMI = "56"


@dataclass
class ProjectorStatus:
    power: str | None = None
    source: str | None = None
    muted: bool | None = None
    lamp_hours: int | None = None
    error: str | None = None


class EscVpNetClient:
    """One connection per session. ESC/VP.net does not stay usefully
    open across long idle periods on all firmwares, so callers typically
    open, run one or a few commands, and close — see `run_command` for a
    convenience one-shot helper.
    """

    def __init__(self, host: str, port: int = ESCVP_PORT):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as e:
            raise ProjectorError(f"Could not reach {self.host}:{self.port}: {e}") from e

        self._writer.write(HANDSHAKE)
        await self._writer.drain()
        try:
            reply = await asyncio.wait_for(
                self._reader.readexactly(len(HANDSHAKE)), timeout=CONNECT_TIMEOUT
            )
        except (asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
            raise ProjectorError(f"Handshake with {self.host} failed: {e}") from e

        if reply != HANDSHAKE:
            raise ProjectorError(f"Unexpected handshake reply from {self.host}: {reply!r}")

        # After a successful handshake the projector sends a ':' prompt.
        await self._read_until_prompt()
        log.debug("Connected and handshook with %s:%s", self.host, self.port)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = None

    async def __aenter__(self) -> "EscVpNetClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _read_until_prompt(self) -> bytes:
        assert self._reader is not None
        try:
            data = await asyncio.wait_for(
                self._reader.readuntil(PROMPT), timeout=COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError as e:
            raise ProjectorError(f"Timed out waiting for reply from {self.host}") from e
        except asyncio.IncompleteReadError as e:
            raise ProjectorError(f"Connection closed by {self.host}") from e
        return data.rstrip(PROMPT).strip(b"\r\n")

    async def send(self, command: str) -> str:
        """Send a raw ESC/VP21 command (without the trailing CR) and
        return the projector's decoded text reply, e.g. send("PWR?") -> "PWR=01".
        """
        if self._writer is None:
            raise ProjectorError("Not connected — use `async with EscVpNetClient(...)`")
        self._writer.write(command.encode("ascii") + CMD_TERMINATOR)
        await self._writer.drain()
        reply = await self._read_until_prompt()
        text = reply.decode("ascii", errors="replace").strip()
        if text.startswith("ERR"):
            raise ProjectorError(f"Projector rejected '{command}': {text}")
        return text

    # --- convenience wrappers -------------------------------------------------

    async def power_on(self) -> None:
        await self.send("PWR ON")

    async def power_off(self) -> None:
        await self.send("PWR OFF")

    async def get_power(self) -> str:
        return await self.send("PWR?")

    async def set_source(self, source: Source) -> None:
        await self.send(f"SOURCE {source.value}")

    async def get_source(self) -> str:
        return await self.send("SOURCE?")

    async def set_mute(self, on: bool) -> None:
        await self.send(f"MUTE {'ON' if on else 'OFF'}")

    async def get_lamp_hours(self) -> int | None:
        reply = await self.send("LAMP?")
        # Typical reply form: "LAMP=1234"
        if "=" in reply:
            try:
                return int(reply.split("=", 1)[1])
            except ValueError:
                return None
        return None

    async def get_status(self) -> ProjectorStatus:
        status = ProjectorStatus()
        try:
            status.power = await self.get_power()
        except ProjectorError as e:
            status.error = str(e)
        try:
            status.source = await self.get_source()
        except ProjectorError:
            pass
        try:
            status.lamp_hours = await self.get_lamp_hours()
        except ProjectorError:
            pass
        return status


async def run_command(host: str, command: str) -> str:
    """One-shot helper: open, run one command, close."""
    async with EscVpNetClient(host) as client:
        return await client.send(command)
