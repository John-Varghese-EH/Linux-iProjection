# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""Unit tests for linux_iprojection.signaling (WebRTC signaling stub)."""

import pytest

from linux_iprojection.signaling import (
    SignalingConfig,
    SignalingError,
    SignalingState,
    WebRTCSession,
    WebRTCSignalingManager,
    has_webrtcbin,
    requires_webrtc,
)


def test_signaling_state_enum():
    """All expected states should be present."""
    states = [s.name for s in SignalingState]
    assert "IDLE" in states
    assert "CONNECTING" in states
    assert "OFFER_SENT" in states
    assert "CONNECTED" in states
    assert "FAILED" in states
    assert "CLOSED" in states


def test_signaling_config_defaults():
    """Config should have sensible defaults."""
    config = SignalingConfig(host="192.168.1.100")
    assert config.port == 3629
    assert config.video_codec == "H264"
    assert config.audio_codec == "opus"
    assert config.video_port == 5004
    assert config.audio_port == 5006
    assert config.enable_encryption is False


def test_session_defaults():
    """WebRTCSession should initialize with IDLE state."""
    config = SignalingConfig(host="192.168.1.100")
    session = WebRTCSession(config=config)
    assert session.state == SignalingState.IDLE
    assert session.local_sdp == ""
    assert session.remote_sdp == ""
    assert session.local_candidates == []


def test_manager_initial_state():
    """Manager should start in IDLE state."""
    manager = WebRTCSignalingManager()
    assert manager.state == SignalingState.IDLE
    assert manager.is_connected is False


def test_manager_state_callback():
    """State change callback should fire."""
    states_received = []
    manager = WebRTCSignalingManager(
        on_state_change=lambda s: states_received.append(s)
    )
    # Manually create a session and trigger state changes
    config = SignalingConfig(host="192.168.1.100")
    manager._session = WebRTCSession(config=config)
    manager._set_state(SignalingState.CONNECTING)
    assert states_received == [SignalingState.CONNECTING]


@pytest.mark.asyncio
async def test_send_offer_without_session():
    """Sending an offer without a session should raise SignalingError."""
    manager = WebRTCSignalingManager()
    with pytest.raises(SignalingError, match="No active session"):
        await manager.send_offer("v=0\r\n...")


@pytest.mark.asyncio
async def test_wait_answer_without_session():
    """Waiting for answer without a session should raise SignalingError."""
    manager = WebRTCSignalingManager()
    with pytest.raises(SignalingError, match="No active session"):
        await manager.wait_for_answer()


@pytest.mark.asyncio
async def test_add_ice_without_session():
    """Adding ICE candidate without a session should raise SignalingError."""
    manager = WebRTCSignalingManager()
    with pytest.raises(SignalingError, match="No active session"):
        await manager.add_ice_candidate("candidate:1 1 UDP 2122260223 ...")


@pytest.mark.asyncio
async def test_close_without_session():
    """Closing a non-existent session should not raise."""
    manager = WebRTCSignalingManager()
    await manager.close()  # Should not raise
    assert manager.state == SignalingState.IDLE


def test_requires_webrtc_rtp():
    """Devices with rtp streaming mode should not require WebRTC."""
    info = {"streaming_mode": "rtp"}
    assert requires_webrtc(info) is False


def test_requires_webrtc_webrtc():
    """Devices with webrtc streaming mode should require WebRTC."""
    info = {"streaming_mode": "webrtc"}
    assert requires_webrtc(info) is True


def test_requires_webrtc_empty():
    """Empty device info should default to not requiring WebRTC."""
    assert requires_webrtc({}) is False


def test_has_webrtcbin_returns_bool():
    """has_webrtcbin should return a boolean without crashing."""
    result = has_webrtcbin()
    assert isinstance(result, bool)
