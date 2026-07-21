"""
epsonctl - Unified Client Wrapper
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH
"""

import logging
import re
import socket
import subprocess
from dataclasses import dataclass

from .pjlink import PJLinkController
from .protocol import EscVpNetClient

log = logging.getLogger(__name__)


@dataclass
class UnifiedStatus:
    power: bool = False
    source: str = ""
    lamp_hours: int = 0
    errors: str = ""
    mute: bool = False
    volume: int = 0
    serial: str = ""


def wake_on_lan(ip: str) -> bool:
    """Attempt to send a WoL magic packet to the given IP by resolving its MAC via ARP."""
    try:
        # Ping to ensure ARP table is populated
        subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL)
        arp_out = subprocess.run(["arp", "-n", ip], capture_output=True, text=True)
        match = re.search(r"([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})", arp_out.stdout)
        if not match:
            return False

        mac = match.group(0).replace("-", ":")
        mac_bytes = bytes.fromhex(mac.replace(":", ""))
        magic_packet = b"\xff" * 6 + mac_bytes * 16

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Broadcast to 255.255.255.255 on port 9
            s.sendto(magic_packet, ("255.255.255.255", 9))
        log.info(f"Sent WoL magic packet to {mac} for {ip}")
        return True
    except Exception as e:
        log.error(f"WoL failed for {ip}: {e}")
        return False


class ProjectorClient:
    """Unified facade for ESC/VP.net and PJLink clients."""

    def __init__(self, host: str, device_type: str = "projector"):
        self.host = host
        self.device_type = device_type
        if device_type == "pjlink_projector":
            self._client = PJLinkController(host)
        else:
            self._client = EscVpNetClient(host)

    async def __aenter__(self):
        await self._client.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.disconnect()

    async def power_on(self):
        await self._client.power_on()

    async def power_off(self):
        await self._client.power_off()

    async def set_source(self, source_code: str):
        if isinstance(self._client, PJLinkController):
            await self._client.set_input(source_code)
        else:
            await self._client.set_source(source_code)

    async def set_mute(self, on: bool):
        if isinstance(self._client, PJLinkController):
            await self._client.set_av_mute(video=on, audio=on)
        else:
            await self._client.set_mute(on)

    async def set_volume(self, level: int):
        if hasattr(self._client, "set_volume"):
            await self._client.set_volume(level)

    async def query_volume(self) -> int:
        if hasattr(self._client, "query_volume"):
            return await self._client.query_volume()
        return 0

    async def set_freeze(self, on: bool):
        if hasattr(self._client, "set_freeze"):
            await self._client.set_freeze(on)

    async def send_key(self, key_code: str):
        if hasattr(self._client, "send_key"):
            await self._client.send_key(key_code)

    async def send_raw(self, cmd: str) -> str:
        if hasattr(self._client, "run_command"):
            return await self._client.run_command(cmd)
        return ""

    async def set_color_mode(self, mode: str):
        if hasattr(self._client, "set_color_mode"):
            await self._client.set_color_mode(mode)

    async def set_aspect_ratio(self, aspect: str):
        if hasattr(self._client, "set_aspect_ratio"):
            await self._client.set_aspect_ratio(aspect)

    async def set_luminance(self, mode: str):
        if hasattr(self._client, "set_luminance"):
            await self._client.set_luminance(mode)

    async def get_status(self) -> UnifiedStatus:
        s = UnifiedStatus()
        try:
            if hasattr(self._client, "get_status"):
                raw = await self._client.get_status()
                s.power = raw.power
                s.source = raw.source
                s.lamp_hours = raw.lamp_hours
                s.errors = raw.errors
            else:
                if hasattr(self._client, "get_power"):
                    s.power = await self._client.get_power()
                if hasattr(self._client, "get_source"):
                    s.source = await self._client.get_source()
                if hasattr(self._client, "get_lamp_hours"):
                    s.lamp_hours = await self._client.get_lamp_hours()
                if hasattr(self._client, "get_error"):
                    s.errors = await self._client.get_error()

            if hasattr(self._client, "get_mute"):
                s.mute = await self._client.get_mute()
            if hasattr(self._client, "get_volume"):
                s.volume = await self._client.get_volume()
            if hasattr(self._client, "get_serial"):
                s.serial = await self._client.get_serial()

            return s
        except Exception as e:
            log.warning("get_status failed: %s", e)
            return s
