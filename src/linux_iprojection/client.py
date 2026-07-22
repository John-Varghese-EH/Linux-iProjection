"""
linux-iprojection unified client wrapper.
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
    brightness: int = 0
    contrast: int = 0
    sharpness: int = 0
    color_temp: str = ""
    filter_hours: int = 0
    projector_name: str = ""
    signal_present: bool = False
    input_resolution: str = ""
    errors_decoded: dict | None = None


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

    async def set_brightness(self, level: int):
        if hasattr(self._client, "set_brightness"):
            await self._client.set_brightness(level)

    async def get_brightness(self) -> int:
        if hasattr(self._client, "get_brightness"):
            return await self._client.get_brightness()
        return 0

    async def set_contrast(self, level: int):
        if hasattr(self._client, "set_contrast"):
            await self._client.set_contrast(level)

    async def get_contrast(self) -> int:
        if hasattr(self._client, "get_contrast"):
            return await self._client.get_contrast()
        return 0

    async def set_sharpness(self, level: int):
        if hasattr(self._client, "set_sharpness"):
            await self._client.set_sharpness(level)

    async def get_sharpness(self) -> int:
        if hasattr(self._client, "get_sharpness"):
            return await self._client.get_sharpness()
        return 0

    async def set_color_temp(self, temp):
        if hasattr(self._client, "set_color_temp"):
            await self._client.set_color_temp(temp)

    async def get_color_temp(self) -> str:
        if hasattr(self._client, "get_color_temp"):
            return await self._client.get_color_temp()
        return ""

    async def set_keystone(self, axis, value: int):
        if hasattr(self._client, "set_keystone"):
            await self._client.set_keystone(axis, value)

    async def get_keystone(self, axis) -> int:
        if hasattr(self._client, "get_keystone"):
            return await self._client.get_keystone(axis)
        return 0

    async def get_filter_hours(self) -> int:
        if hasattr(self._client, "get_filter_hours"):
            return await self._client.get_filter_hours()
        return 0

    async def get_projector_name(self) -> str:
        if hasattr(self._client, "get_projector_name"):
            return await self._client.get_projector_name()
        if hasattr(self._client, "get_name"):
            return await self._client.get_name()
        return ""

    async def get_signal_status(self) -> bool:
        if hasattr(self._client, "get_signal_status"):
            return await self._client.get_signal_status()
        return False

    async def get_detailed_errors(self) -> dict:
        if hasattr(self._client, "get_detailed_errors"):
            return await self._client.get_detailed_errors()
        return {}

    async def get_input_resolution(self) -> str:
        if hasattr(self._client, "get_input_resolution"):
            return await self._client.get_input_resolution()
        return ""

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

            # Extended enterprise fields
            try:
                s.brightness = await self.get_brightness()
            except Exception:
                pass
            try:
                s.contrast = await self.get_contrast()
            except Exception:
                pass
            try:
                s.sharpness = await self.get_sharpness()
            except Exception:
                pass
            try:
                s.color_temp = await self.get_color_temp()
            except Exception:
                pass
            try:
                s.filter_hours = await self.get_filter_hours()
            except Exception:
                pass
            try:
                s.projector_name = await self.get_projector_name()
            except Exception:
                pass
            try:
                s.signal_present = await self.get_signal_status()
            except Exception:
                pass
            try:
                s.input_resolution = await self.get_input_resolution()
            except Exception:
                pass
            try:
                s.errors_decoded = await self.get_detailed_errors()
            except Exception:
                pass

            return s
        except Exception as e:
            log.warning("get_status failed: %s", e)
            return s
