"""
linux-iprojection: WebRTC Signaling Manager (Stub)
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

This module provides the WebRTC signaling layer for modern Epson projectors
that require SDP offer/answer negotiation before accepting video streams.

Architecture:
    The Windows iProjection app uses WebRTCManager.dll (Google's libwebrtc)
    with signaling exchanged over a proprietary binary protocol on the
    ESC/VP.net TCP channel (port 3629) or a secondary channel.

    This stub defines the async interface and state machine. The actual
    signaling byte format will be implemented once a PCAP trace of the
    Windows app negotiation is captured and analyzed.

Integration with GStreamer:
    When the signaling is fully implemented, cast.py will use GStreamer's
    `webrtcbin` element instead of raw `udpsink`, connecting its
    `on-negotiation-needed` and `on-ice-candidate` signals to this module.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

log = logging.getLogger(__name__)


class SignalingState(Enum):
    """State machine for the WebRTC signaling session."""
    IDLE = auto()
    CONNECTING = auto()
    AUTHENTICATING = auto()
    SESSION_INIT = auto()         # Sending session initialization to projector
    OFFER_SENT = auto()           # SDP offer sent, waiting for answer
    ANSWER_RECEIVED = auto()      # SDP answer received, ICE candidates exchanging
    ICE_GATHERING = auto()        # Gathering/exchanging ICE candidates
    CONNECTED = auto()            # WebRTC media flowing
    FAILED = auto()
    CLOSED = auto()


@dataclass
class SignalingConfig:
    """Configuration for the WebRTC signaling session."""
    host: str
    port: int = 3629              # ESC/VP.net port (signaling channel)
    video_codec: str = "H264"     # H264 or VP8 (projector preference)
    audio_codec: str = "opus"     # opus or g711
    video_port: int = 5004        # RTP video port (for ICE candidate)
    audio_port: int = 5006        # RTP audio port (for ICE candidate)
    enable_encryption: bool = False
    encryption_mode: str = "AESEPCTR"  # AES, DES, or AESEPCTR


@dataclass
class WebRTCSession:
    """Represents an active WebRTC session with a projector."""
    config: SignalingConfig
    state: SignalingState = SignalingState.IDLE
    local_sdp: str = ""           # Our SDP offer
    remote_sdp: str = ""          # Projector's SDP answer
    local_candidates: list[str] = field(default_factory=list)
    remote_candidates: list[str] = field(default_factory=list)
    session_id: str = ""


class SignalingError(Exception):
    """Raised for signaling protocol errors."""


class WebRTCSignalingManager:
    """Manages WebRTC signaling with Epson projectors.

    This is a STUB implementation. The actual signaling byte format will be
    reverse-engineered from captured network traffic (PCAP) of the Windows
    iProjection application connecting to a projector.

    Usage (once fully implemented):
        manager = WebRTCSignalingManager()
        session = await manager.create_session(config)
        await manager.send_offer(session, local_sdp)
        remote_sdp = await manager.wait_for_answer(session)
        # ... exchange ICE candidates ...
        # GStreamer webrtcbin handles media from here
    """

    def __init__(
        self,
        on_state_change: Optional[Callable[[SignalingState], None]] = None,
        on_remote_sdp: Optional[Callable[[str], None]] = None,
        on_remote_ice: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_state_change = on_state_change
        self._on_remote_sdp = on_remote_sdp
        self._on_remote_ice = on_remote_ice
        self._session: Optional[WebRTCSession] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SignalingState:
        if self._session:
            return self._session.state
        return SignalingState.IDLE

    @property
    def is_connected(self) -> bool:
        return self.state == SignalingState.CONNECTED

    def _set_state(self, new_state: SignalingState) -> None:
        if self._session:
            old = self._session.state
            self._session.state = new_state
            log.info("Signaling state: %s → %s", old.name, new_state.name)
            if self._on_state_change:
                self._on_state_change(new_state)

    async def create_session(self, config: SignalingConfig) -> WebRTCSession:
        """Create a new WebRTC signaling session with the projector.

        This establishes the TCP control channel and prepares the projector
        for WebRTC streaming. The actual signaling bytes are TBD (requires
        PCAP analysis of EMP_PJCON.dll communication).

        Raises:
            SignalingError: If the session cannot be established.
            NotImplementedError: Until PCAP-based protocol is implemented.
        """
        self._session = WebRTCSession(config=config)
        self._set_state(SignalingState.CONNECTING)

        # Phase 1: Connect to projector via ESC/VP.net
        try:
            from .protocol import EscVpNetClient
            async with EscVpNetClient(config.host, config.port) as client:
                # Prepare projector for WebRTC
                if config.enable_encryption:
                    await client.set_encryption(config.encryption_mode)
                    log.info("Encryption mode set to %s", config.encryption_mode)

                # Switch to LAN source
                from .protocol import Source
                await client.set_source(Source.LAN)
                log.info("Projector switched to LAN source")

        except Exception as e:
            self._set_state(SignalingState.FAILED)
            raise SignalingError(f"Failed to prepare projector: {e}") from e

        # Phase 2: WebRTC signaling exchange
        # This is where the proprietary signaling protocol goes.
        # Without a PCAP trace, we cannot implement this phase.
        self._set_state(SignalingState.SESSION_INIT)

        raise NotImplementedError(
            "WebRTC signaling protocol not yet reverse-engineered. "
            "Please capture a PCAP trace of the Windows iProjection app "
            "connecting to the projector and place it in the workspace. "
            "Filter: tcp.port == 3629 || udp.port == 3620"
        )

    async def send_offer(self, sdp: str) -> None:
        """Send an SDP offer to the projector.

        Args:
            sdp: The local SDP offer string from GStreamer's webrtcbin.

        Raises:
            NotImplementedError: Until PCAP-based protocol is implemented.
        """
        if not self._session:
            raise SignalingError("No active session")

        self._session.local_sdp = sdp
        self._set_state(SignalingState.OFFER_SENT)

        # TODO: Encode SDP into the proprietary binary format
        # and send over the ESC/VP.net TCP channel.
        raise NotImplementedError(
            "SDP offer encoding requires PCAP analysis of EMP_PJCON.dll signaling"
        )

    async def wait_for_answer(self, timeout: float = 30.0) -> str:
        """Wait for the projector's SDP answer.

        Returns:
            The remote SDP answer string.

        Raises:
            NotImplementedError: Until PCAP-based protocol is implemented.
        """
        if not self._session:
            raise SignalingError("No active session")

        # TODO: Parse the proprietary binary response into an SDP answer.
        raise NotImplementedError(
            "SDP answer parsing requires PCAP analysis of EMP_PJCON.dll signaling"
        )

    async def add_ice_candidate(self, candidate: str) -> None:
        """Send a local ICE candidate to the projector.

        Args:
            candidate: ICE candidate string from GStreamer's webrtcbin.
        """
        if not self._session:
            raise SignalingError("No active session")

        self._session.local_candidates.append(candidate)
        log.debug("Local ICE candidate: %s", candidate)

        # TODO: Send ICE candidate over the proprietary channel.
        raise NotImplementedError(
            "ICE candidate exchange requires PCAP analysis"
        )

    async def close(self) -> None:
        """Close the signaling session and clean up resources."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None

        self._set_state(SignalingState.CLOSED)
        self._session = None
        log.info("WebRTC signaling session closed")


# ── Capability detection ─────────────────────────────────────────────────────


def requires_webrtc(device_info: dict) -> bool:
    """Check if a discovered device requires WebRTC signaling for streaming.

    Args:
        device_info: The `info` dict from a DiscoveredDevice.

    Returns:
        True if the projector requires WebRTC (modern firmware),
        False if raw RTP push should work (older firmware).
    """
    return device_info.get("streaming_mode") == "webrtc"


def has_webrtcbin() -> bool:
    """Check if GStreamer's webrtcbin element is available.

    Requires gst-plugins-bad with WebRTC support compiled in.
    """
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        registry = Gst.Registry.get()
        return registry.lookup_feature("webrtcbin") is not None
    except Exception:
        return False
"""
<parameter name="toolAction">Creating signaling stub
