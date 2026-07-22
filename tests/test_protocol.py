# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""Unit tests for linux_iprojection.protocol (EscVpNetClient).

Uses the fake TCP server from conftest.py - no real projector needed.
"""

import pytest

from linux_iprojection.protocol import (
    EscVpNetClient,
    ProjectorError,
    ProjectorUnreachableError,
    Source,
)


@pytest.mark.asyncio
async def test_handshake_success(fake_server):
    """A fresh connection should complete the handshake without error."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        reply = await client.send("PWR?")
        assert "PWR" in reply


@pytest.mark.asyncio
async def test_handshake_failure(bad_handshake_server):
    """A server returning wrong handshake bytes should raise ProjectorError."""
    with pytest.raises(ProjectorError, match="Unexpected handshake"):
        async with EscVpNetClient("127.0.0.1", bad_handshake_server.actual_port):
            pass


@pytest.mark.asyncio
async def test_connection_refused():
    """Connecting to a port with no server should raise after retries."""
    with pytest.raises((ProjectorError, ProjectorUnreachableError)):
        async with EscVpNetClient("127.0.0.1", 1):  # Port 1 - nothing there
            pass


@pytest.mark.asyncio
async def test_command_timeout(hanging_server):
    """A server that never responds to commands should cause a timeout."""
    with pytest.raises(ProjectorError, match="Timed out"):
        async with EscVpNetClient("127.0.0.1", hanging_server.actual_port) as client:
            await client.send("PWR?")


@pytest.mark.asyncio
async def test_err_response(fake_server):
    """Sending an unknown command should raise ProjectorError with ERR."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        with pytest.raises(ProjectorError, match="ERR"):
            await client.send("BADCMD")


@pytest.mark.asyncio
async def test_power_query(fake_server):
    """PWR? should return the power state value."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        result = await client.get_power()
        assert result == "01"


@pytest.mark.asyncio
async def test_power_on_off(fake_server):
    """Power on/off should work without errors."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        await client.power_on()
        result = await client.get_power()
        assert result == "01"

        await client.power_off()
        result = await client.get_power()
        assert result == "00"


@pytest.mark.asyncio
async def test_lamp_hours_with_status(fake_server):
    """LAMP? parsing should handle 'LAMP=1234 01' format (hours + status)."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        hours = await client.get_lamp_hours()
        assert hours == 1234


@pytest.mark.asyncio
async def test_lamp_hours_zero(fake_server):
    """Lamp hours should handle 0."""
    fake_server.lamp_hours = 0
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        hours = await client.get_lamp_hours()
        assert hours == 0


@pytest.mark.asyncio
async def test_lamp_hours_large(fake_server):
    """Lamp hours should handle large values."""
    fake_server.lamp_hours = 99999
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        hours = await client.get_lamp_hours()
        assert hours == 99999


@pytest.mark.asyncio
async def test_source_set_and_query(fake_server):
    """Setting and querying input source should round-trip."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        await client.set_source(Source.HDMI1)
        result = await client.get_source()
        assert result == "30"


@pytest.mark.asyncio
async def test_mute(fake_server):
    """Mute on/off should work."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        await client.set_mute(True)
        await client.set_mute(False)


@pytest.mark.asyncio
async def test_serial_number(fake_server):
    """SNO? should return the serial number."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        serial = await client.get_serial()
        assert serial == "TEST123456"


@pytest.mark.asyncio
async def test_get_status(fake_server):
    """get_status() should return a complete ProjectorStatus."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        status = await client.get_status()
        assert status.power == "01"
        assert status.lamp_hours == 1234
        assert status.error is None  # no error querying status


@pytest.mark.asyncio
async def test_not_connected_raises():
    """Sending a command without connecting should raise."""
    client = EscVpNetClient("127.0.0.1", 3629)
    with pytest.raises(ProjectorError, match="Not connected"):
        await client.send("PWR?")


@pytest.mark.asyncio
async def test_enterprise_features(fake_server):
    """Test the newly added enterprise features."""
    async with EscVpNetClient("127.0.0.1", fake_server.actual_port) as client:
        # Brightness
        await client.set_brightness(140)
        result = await client.get_brightness()
        assert result == 140
        
        # Contrast
        await client.set_contrast(150)
        result = await client.get_contrast()
        assert result == 150
        
        # Sharpness
        await client.set_sharpness(160)
        result = await client.get_sharpness()
        assert result == 160
        
        # Color Temp
        await client.set_color_temp(8)
        result = await client.get_color_temp()
        assert result == 8
        
        # Keystone
        from linux_iprojection.protocol import KeystoneAxis
        await client.set_keystone(KeystoneAxis.HORIZONTAL, 15)
        
        # Diagnostics
        filter_hours = await client.get_filter_hours()
        assert filter_hours == 500
        
        signal = await client.get_signal_status()
        assert signal == "00"
        
        resolution = await client.get_input_resolution()
        assert resolution == "1920x1080"
