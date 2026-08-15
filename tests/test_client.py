import asyncio
import pytest
from linux_iprojection.client import ProjectorClient, wake_on_lan

@pytest.mark.asyncio
async def test_projector_client_init():
    client = ProjectorClient("127.0.0.1")
    assert client.ip == "127.0.0.1"

@pytest.mark.asyncio
async def test_wake_on_lan():
    # Mostly ensuring it doesn't crash
    wake_on_lan("00:11:22:33:44:55")

@pytest.mark.asyncio
async def test_client_status_deduplication(mocker):
    # Mock EscVpNetClient to test if we don't double query
    mock_escvp = mocker.AsyncMock()
    # Let get_status return an object with populated fields
    class MockStatus:
        power = "01"
        source = "30"
        lamp_hours = 123
        errors = ""
        muted = True
        brightness = 100
        contrast = 50
        sharpness = 20
        color_temp = "00"
        filter_hours = 0
        projector_name = "TEST_PROJ"
        signal_present = True
        errors_decoded = []
    
    mock_escvp.get_status.return_value = MockStatus()
    # ensure it has the method get_status so our code uses it
    
    client = ProjectorClient("127.0.0.1")
    client._client = mock_escvp
    
    status = await client.get_status()
    assert status.power == "01"
    assert status.source == "30"
    assert status.mute == True
    assert status.projector_name == "TEST_PROJ"
    
    # ensure individual queries weren't called
    assert not mock_escvp.get_mute.called
    assert not mock_escvp.get_brightness.called
