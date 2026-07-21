"""
epsonctl - ESC/VP.net client.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

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
MAX_RETRIES = 3


class ProjectorError(Exception):
    """Raised for handshake failures, timeouts, or ERR responses."""


class ProjectorUnreachableError(ProjectorError):
    """Raised when connection retries are exhausted."""


class Power(str, Enum):
    ON = "01"
    OFF = "00"
    WARMUP = "02"
    COOLDOWN = "03"
    STANDBY = "04"
    ABNORMAL_STANDBY = "05"


# Common input source codes. Not every projector model supports every
# source - query `SOURCE?` / consult the model's ESC/VP21 guide to confirm.
class Source(str, Enum):
    VGA1 = "10"  # Computer 1/VGA (Analog)
    COMPUTER1 = "11"  # Computer 1 (Digital/RGB)
    VGA2 = "20"  # Computer 2/VGA (Analog)
    COMPUTER2 = "21"  # Computer 2 (Digital/RGB)
    HDMI1 = "30"  # HDMI 1
    VIDEO = "41"  # Video/Composite
    S_VIDEO = "42"  # S-Video
    USB = "52"  # USB Display
    LAN = "53"  # LAN/Network
    WIRELESS_HDMI = "56"  # Wireless HDMI (e.g. EB-1430Wi)
    HDMI2 = "A0"  # HDMI 2


class ColorMode(str, Enum):
    SRGB = "01"
    PRESENTATION = "04"
    THEATRE = "05"
    DYNAMIC = "06"
    BLACKBOARD = "0B"
    WHITEBOARD = "0C"


class AspectRatio(str, Enum):
    AUTO = "00"
    NORMAL = "20"
    WIDE = "30"
    FULL = "40"
    ZOOM = "50"


class LuminanceMode(str, Enum):
    NORMAL = "00"
    ECO = "01"


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
    open, run one or a few commands, and close - see `run_command` for a
    convenience one-shot helper.
    """

    def __init__(self, host: str, port: int = ESCVP_PORT):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._keepalive_task: asyncio.Task | None = None

    async def _attempt_connect(self) -> None:
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

    async def connect(self) -> None:
        retries = 0
        delay = 0.5
        while retries < MAX_RETRIES:
            try:
                await self._attempt_connect()
                return
            except ProjectorError as e:
                retries += 1
                if retries == MAX_RETRIES:
                    raise ProjectorUnreachableError(
                        f"Failed to connect after {MAX_RETRIES} attempts: {e}"
                    ) from e
                log.warning(f"Connection attempt {retries} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= 3.0  # 0.5, 1.5, 4.5

    async def _keepalive_loop(self):
        try:
            while True:
                await asyncio.sleep(10)
                if self._writer is not None:
                    # Send an empty CR to keep the connection alive
                    self._writer.write(CMD_TERMINATOR)
                    await self._writer.drain()
                    await self._read_until_prompt()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"Keepalive failed: {e}")

    def start_keepalive(self):
        if self._keepalive_task is None:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    def stop_keepalive(self):
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            self._keepalive_task = None

    async def close(self) -> None:
        self.stop_keepalive()
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
            data = await asyncio.wait_for(self._reader.readuntil(PROMPT), timeout=COMMAND_TIMEOUT)
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
            raise ProjectorError("Not connected - use `async with EscVpNetClient(...)`")
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
        reply = await self.send("PWR?")
        if reply.startswith("PWR="):
            return reply.split("=", 1)[1]
        return reply

    async def set_source(self, source: Source) -> None:
        await self.send(f"SOURCE {source.value}")

    async def get_source(self) -> str:
        reply = await self.send("SOURCE?")
        if reply.startswith("SOURCE="):
            return reply.split("=", 1)[1]
        return reply

    async def set_mute(self, on: bool) -> None:
        await self.send(f"MUTE {'ON' if on else 'OFF'}")

    async def query_lamp_hours(self) -> int:
        resp = await self.send("LAMP?")
        try:
            return int(resp.split("=", 1)[1].split()[0])
        except (IndexError, ValueError):
            return 0

    async def set_volume(self, level: int) -> None:
        """Set volume level (0-255)."""
        await self.send(f"VOL {level}")

    async def query_volume(self) -> int:
        """Query current volume."""
        resp = await self.send("VOL?")
        if "=" in resp:
            try:
                return int(resp.split("=", 1)[1].strip())
            except ValueError:
                pass
        return 0

    async def set_freeze(self, enable: bool) -> None:
        """Enable or disable image freeze."""
        cmd = "FREEZE ON" if enable else "FREEZE OFF"
        await self.send(cmd)

    async def send_key(self, hex_code: str) -> None:
        """
        Send a remote control key simulation command.
        Example hex_codes: '35' (Menu), '36' (Enter), '58' (Up), '59' (Down).
        """
        await self.send(f"KEY {hex_code}")

    async def set_color_mode(self, mode: ColorMode) -> None:
        await self.send(f"CMODE {mode.value}")

    async def get_color_mode(self) -> str:
        reply = await self.send("CMODE?")
        if reply.startswith("CMODE="):
            return reply.split("=", 1)[1]
        return reply

    async def set_aspect_ratio(self, aspect: AspectRatio) -> None:
        await self.send(f"ASPECT {aspect.value}")

    async def get_aspect_ratio(self) -> str:
        reply = await self.send("ASPECT?")
        if reply.startswith("ASPECT="):
            return reply.split("=", 1)[1]
        return reply

    async def set_luminance(self, mode: LuminanceMode) -> None:
        await self.send(f"LUMINANCE {mode.value}")

    async def get_luminance(self) -> str:
        reply = await self.send("LUMINANCE?")
        if reply.startswith("LUMINANCE="):
            return reply.split("=", 1)[1]
        return reply

    async def get_mute(self) -> bool:
        reply = await self.send("MUTE?")
        if reply.startswith("MUTE="):
            val = reply.split("=", 1)[1]
            return val == "ON"
        return False

    async def get_serial(self) -> str:
        reply = await self.send("SNO?")
        if reply.startswith("SNO="):
            return reply.split("=", 1)[1]
        return reply

    async def get_error(self) -> str:
        reply = await self.send("ERR?")
        if reply.startswith("ERR="):
            return reply.split("=", 1)[1]
        return reply

    async def get_lamp_hours(self) -> int | None:
        reply = await self.send("LAMP?")
        # Typical reply form: "LAMP=1234" or "LAMP=1234 01" (hours + status)
        if "=" in reply:
            val = reply.split("=", 1)[1]
            # split by space to handle "1234 01" format
            hours = val.split(" ")[0]
            try:
                return int(hours)
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
            status.muted = await self.get_mute()
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
