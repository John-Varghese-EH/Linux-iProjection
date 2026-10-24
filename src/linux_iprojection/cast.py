"""
linux-iprojection - Screen casting via GStreamer and XDG Desktop Portal
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

Captures the screen via xdg-desktop-portal ScreenCast (PipeWire), encodes
to H.264, and delivers via RTP-over-UDP to the projector/receiver.

Protocol: pure RTP/UDP push - no RTSP session negotiation.
  Video: H.264 → rtph264pay pt=96 → udpsink port=5004
  Audio: Opus  → rtpopuspay pt=97 → udpsink port=5006
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, Gst  # noqa: E402

log = logging.getLogger(__name__)

_portal_token_counter = 0
_portal_session_handle: str | None = None

# Lazy init - don't call Gst.init at import time
_gst_initialized = False


def _ensure_gst():
    global _gst_initialized
    if not _gst_initialized:
        Gst.init(None)
        _gst_initialized = True


# Data types


class EncoderPreset(Enum):
    AUTO = auto()
    VAAPI = auto()
    NVENC = auto()
    SOFTWARE = auto()


@dataclass
class StreamStats:
    bitrate_kbps: float = 0.0
    fps: float = 0.0
    latency_ms: float = 0.0
    dropped: int = 0
    audio_active: bool = False


@dataclass
class CastTarget:
    """Where to send the stream."""

    host: str
    port: int = 5004  # video RTP port
    audio_port: int = 5006  # audio RTP port
    name: str = ""  # display name for UI


# Sink abstraction

TEST_PATTERNS = {
    "smpte": 0,        # SMPTE color bars
    "snow": 1,         # Random noise
    "black": 2,        # Solid black
    "white": 3,        # Solid white
    "red": 4,          # Solid red
    "green": 5,        # Solid green
    "blue": 6,         # Solid blue
    "checkers": 7,     # Checkerboard (1px)
    "circular": 17,    # Circular pattern
    "gamut": 19,       # Gamut check
    "grid": 23,        # Grid overlay
}


class CastSink(ABC):
    """Pluggable GStreamer sink chain for the encoded stream."""

    @abstractmethod
    def build_sink_bin(self, target: CastTarget) -> str:
        """Return a gst-launch-style element description for the sink."""


class RtpUdpSink(CastSink):
    """Production sink: RTP H.264 over UDP to the receiver."""

    def build_sink_bin(self, target: CastTarget) -> str:
        return (
            f"rtph264pay config-interval=1 pt=96 ! "
            f"udpsink host={target.host} port={target.port} sync=false"
        )


class FileDumpSink(CastSink):
    """Test sink: writes encoded stream to a local .mp4 file."""

    def build_sink_bin(self, target: CastTarget) -> str:
        return f'mp4mux ! filesink location="{target.host}"'


class JpegRtpSink(CastSink):
    """JPEG Rect-based sink for projectors not supporting H.264 RTP."""

    def build_sink_bin(self, target: CastTarget) -> str:
        return (
            f"jpegenc quality=85 ! rtpjpegpay pt=26 ! "
            f"udpsink host={target.host} port={target.port} sync=false"
        )


# Encoder detection


def _probe_encoder(preset: EncoderPreset = EncoderPreset.AUTO, quality: str = "balanced") -> str:
    """Detect best available H.264 encoder. Falls back to x264enc."""
    _ensure_gst()
    registry = Gst.Registry.get()

    if quality == "low_latency":
        x264_params = "bitrate=2000 speed-preset=ultrafast tune=zerolatency key-int-max=15"
        vaapi_params = "rate-control=cbr bitrate=2000"
        nvenc_params = "bitrate=2000 rc-mode=cbr zerolatency=true"
        openh264_params = "bitrate=2000000"
        base_bitrate = 2000
    elif quality == "high_quality":
        x264_params = "bitrate=8000 speed-preset=fast tune=zerolatency key-int-max=60"
        vaapi_params = "rate-control=cbr bitrate=8000"
        nvenc_params = "bitrate=8000 rc-mode=cbr"
        openh264_params = "bitrate=8000000"
        base_bitrate = 8000
    else:  # balanced
        x264_params = "bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30"
        vaapi_params = "rate-control=cbr bitrate=4000"
        nvenc_params = "bitrate=4000 rc-mode=cbr zerolatency=true"
        openh264_params = "bitrate=4000000"
        base_bitrate = 4000

    candidates = [
        # VA-API (Intel / AMD GPU)
        (EncoderPreset.VAAPI, "vah264enc", f"vah264enc {vaapi_params}"),
        (EncoderPreset.VAAPI, "vaapih264enc", f"vaapih264enc {vaapi_params}"),
        # NVIDIA NVENC
        (EncoderPreset.NVENC, "nvh264enc", f"nvh264enc {nvenc_params}"),
        (EncoderPreset.NVENC, "nvautogpuh264enc", f"nvautogpuh264enc {nvenc_params}"),
        (EncoderPreset.NVENC, "nvv4l2h264enc", f"nvv4l2h264enc bitrate={base_bitrate * 1000}"),
        # Software encoders
        (EncoderPreset.SOFTWARE, "x264enc", f"x264enc {x264_params}"),
        (EncoderPreset.SOFTWARE, "openh264enc", f"openh264enc {openh264_params}"),
    ]

    for enc_preset, element_name, element_str in candidates:
        if preset not in (EncoderPreset.AUTO, enc_preset):
            continue
        if registry.lookup_feature(element_name):
            log.info("Encoder selected: %s (%s)", element_name, enc_preset.name)
            return element_str

    log.warning("No HW encoder found - using x264enc (software)")
    return f"x264enc {x264_params}"


def _probe_audio_encoder() -> tuple[str, str]:
    """Return (encoder_element, payloader_element) for audio."""
    _ensure_gst()
    registry = Gst.Registry.get()
    if registry.lookup_feature("opusenc"):
        return "opusenc bitrate=128000", "rtpopuspay pt=97"
    if registry.lookup_feature("avenc_aac"):
        return "avenc_aac bitrate=128000", "rtpmp4apay pt=97"
    log.warning("No audio encoder found - audio will be disabled")
    return "", ""


# XDG Desktop Portal ScreenCast


class UserCancelledError(Exception):
    """Raised when the user explicitly cancels or dismisses the screen sharing dialog."""


class PortalError(Exception):
    """Raised when xdg-desktop-portal ScreenCast is unavailable or fails."""


async def _request_portal_stream(virtual: bool = False) -> Optional[int]:
    """Walk the xdg-desktop-portal ScreenCast flow and return a PipeWire node ID.

    Returns None if the user cancels the dialog or something goes wrong.
    Uses Gio.DBusProxy (no extra dependency beyond PyGObject).
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as e:
        log.error("Cannot connect to session D-Bus: %s", e)
        raise PortalError(f"Cannot connect to session D-Bus: {e}") from e

    portal_proxy = Gio.DBusProxy.new_sync(
        bus,
        Gio.DBusProxyFlags.NONE,
        None,
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.ScreenCast",
        None,
    )

    global _portal_token_counter
    _portal_token_counter += 1
    token = f"linux_iprojection_{os.getpid()}_{_portal_token_counter}"
    sender = bus.get_unique_name().replace(".", "_")[1:]

    async def call_and_wait(method: str, args, handle_token: str) -> dict:
        """Call a portal method and wait for the Response signal."""
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        request_proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            None,
            "org.freedesktop.portal.Desktop",
            request_path,
            "org.freedesktop.portal.Request",
            None,
        )

        def on_signal(_proxy, _sender, signal_name, parameters):
            if signal_name == "Response" and not future.done():
                response_code, results = parameters.unpack()
                if response_code == 0:
                    loop.call_soon_threadsafe(future.set_result, results)
                elif response_code == 1:
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        UserCancelledError("User dismissed the screen sharing dialog"),
                    )
                else:
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        PortalError(f"Portal error (code {response_code})"),
                    )

        handler_id = request_proxy.connect("g-signal", on_signal)

        try:
            await loop.run_in_executor(None, lambda: portal_proxy.call_sync(method, args, Gio.DBusCallFlags.NONE, 30000, None))
            return await asyncio.wait_for(future, timeout=120)
        finally:
            request_proxy.disconnect(handler_id)

    try:
        # Step 1: CreateSession
        session_token = f"session_{token}"
        req1 = f"req_{token}_1"
        result = await call_and_wait(
            "CreateSession",
            GLib.Variant(
                "(a{sv})",
                (
                    {
                        "session_handle_token": GLib.Variant("s", session_token),
                        "handle_token": GLib.Variant("s", req1),
                    },
                ),
            ),
            req1,
        )
        session_handle = result.get("session_handle", "")
        if not session_handle:
            raise RuntimeError("CreateSession returned no session_handle")
        log.info("Portal session created: %s", session_handle)

        # Step 2: SelectSources
        req2 = f"req_{token}_2"
        await call_and_wait(
            "SelectSources",
            GLib.Variant(
                "(oa{sv})",
                (
                    session_handle,
                    {
                        "types": GLib.Variant("u", 4 if virtual else 3),  # 4=Virtual, 3=Monitor+Window
                        "cursor_mode": GLib.Variant("u", 2),  # 2 = metadata
                        "handle_token": GLib.Variant("s", req2),
                    },
                ),
            ),
            req2,
        )
        log.info("Portal sources selected")

        # Step 3: Start (this shows the user permission dialog)
        req3 = f"req_{token}_3"
        start_result = await call_and_wait(
            "Start",
            GLib.Variant(
                "(osa{sv})",
                (
                    session_handle,
                    "",
                    {
                        "handle_token": GLib.Variant("s", req3),
                    },
                ),
            ),
            req3,
        )

        streams = start_result.get("streams", [])
        if not streams:
            log.warning("Portal returned no streams")
            return None

        node_id = int(streams[0][0])
        log.info("PipeWire node ID: %d", node_id)

        # Save session handle for cleanup
        global _portal_session_handle
        _portal_session_handle = session_handle

        return node_id

    except UserCancelledError:
        raise
    except Exception as e:
        log.warning("Portal ScreenCast failed: %s", e)
        raise PortalError(str(e)) from e


def _close_portal_session() -> None:
    """Close the active XDG Desktop Portal ScreenCast session."""
    global _portal_session_handle
    if _portal_session_handle is None:
        return
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            "org.freedesktop.portal.Desktop",
            _portal_session_handle,
            "org.freedesktop.portal.Session",
            "Close",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        log.info("Portal session closed: %s", _portal_session_handle)
    except Exception as e:
        log.debug("Portal session close failed (may already be closed): %s", e)
    _portal_session_handle = None


# Pipeline manager


class ScreenCaster:
    """Manages the full capture → encode → RTP pipeline lifecycle.

    Usage:
        caster = ScreenCaster(sink=RtpUdpSink())
        await caster.start(CastTarget(host="192.168.1.100"))
        ...
        caster.stop()
    """

    def __init__(
        self,
        sink: CastSink | None = None,
        audio_enabled: bool = True,
        encoder_preset: EncoderPreset = EncoderPreset.AUTO,
        stream_quality: str = "balanced",
        on_stats: Callable[[StreamStats], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.sink = sink or RtpUdpSink()
        self.audio_enabled = audio_enabled
        self.encoder_preset = encoder_preset
        self.stream_quality = stream_quality
        self.on_stats = on_stats
        self.on_error = on_error

        self._pipeline: Gst.Pipeline | None = None
        self._target: CastTarget | None = None
        self._is_casting = False
        self._stats_timeout_id: int | None = None
        self._bus_watch_id = None
        self._active_pattern: str | None = None
        self._error_count: int = 0
        self._max_retries: int = 3
        self.last_error: str | None = None
        self.user_cancelled: bool = False

    @property
    def active_pattern(self) -> str | None:
        """Return the name of the active test pattern, or None if screen casting."""
        return self._active_pattern

    @property
    def is_casting(self) -> bool:
        return self._is_casting

    async def start(self, target: CastTarget, virtual: bool = False) -> bool:
        """Request a portal stream (or fall back to X11 capture) and start the GStreamer pipeline.

        Returns True if casting started successfully.
        """
        if self._is_casting:
            log.warning("Already casting - call stop() first")
            return False

        self.last_error = None
        self.user_cancelled = False

        _ensure_gst()

        # Determine if this is a dry-run (file target)
        is_file = target.host.startswith("/") or target.host.endswith(".mp4")

        # Determine display server environment
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        has_display = bool(os.environ.get("DISPLAY"))
        registry = Gst.Registry.get()
        has_ximagesrc = registry.lookup_feature("ximagesrc") is not None and has_display

        # Get PipeWire node for real casting
        node_id = None
        if not is_file:
            try:
                node_id = await _request_portal_stream(virtual=virtual)
            except UserCancelledError:
                log.info("User cancelled screen sharing portal dialog")
                self.user_cancelled = True
                self.last_error = "Screen sharing cancelled by user"
                return False
            except Exception as e:
                log.warning("Portal ScreenCast unavailable/failed: %s", e)
                # On X11 (e.g. Linux Mint / Cinnamon / XFCE / MATE), seamlessly fall back to native ximagesrc!
                if not is_wayland and has_ximagesrc:
                    log.info("Falling back to native X11 ximagesrc for screen capture")
                    node_id = None
                else:
                    err_msg = (
                        f"Screen sharing portal error: {e}. "
                        "On Wayland, ensure a compatible xdg-desktop-portal backend is active."
                    )
                    log.error(err_msg)
                    self.last_error = err_msg
                    if self.on_error:
                        self.on_error(err_msg)
                    return False

            if node_id is None and is_wayland:
                err_msg = "ScreenCast portal did not return a valid video stream. Ensure screen sharing permission was granted."
                log.error(err_msg)
                self.last_error = err_msg
                if self.on_error:
                    self.on_error(err_msg)
                return False

            # Switch projector to LAN input (source 53) and wake up if in standby
            await self._prepare_projector_for_stream(target)

        # Build the pipeline
        pipeline_str = self._build_pipeline(target, node_id, is_file)
        log.info("GStreamer pipeline: %s", pipeline_str)

        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            log.error("Failed to parse pipeline: %s", e)
            self.last_error = f"Pipeline parse error: {e}"
            if self.on_error:
                self.on_error(self.last_error)
            return False

        # Bus monitoring
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        self._bus_watch_id = bus.connect("message", self._on_bus_message)

        # Start playing with multi-stage fallback
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            log.warning("Pipeline failed to start. Attempting fallbacks...")
            self._pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()

            # Fallback 1: Try video-only (audio devices frequently fail on Linux)
            if self.audio_enabled and not is_file:
                log.info("Attempting video-only fallback...")
                pipeline_str = self._build_pipeline(target, node_id, is_file, enable_audio=False)
                try:
                    self._pipeline = Gst.parse_launch(pipeline_str)
                    bus = self._pipeline.get_bus()
                    bus.add_signal_watch()
                    self._bus_watch_id = bus.connect("message", self._on_bus_message)
                    ret = self._pipeline.set_state(Gst.State.PLAYING)
                except Exception as ex:
                    log.warning("Video-only parse error: %s", ex)
                    ret = Gst.StateChangeReturn.FAILURE

            # Fallback 2: Force software x264enc encoder
            if ret == Gst.StateChangeReturn.FAILURE:
                log.warning("Hardware encoder failed, falling back to software x264enc")
                if self._pipeline:
                    self._pipeline.set_state(Gst.State.NULL)
                    bus.remove_signal_watch()

                safe_encoder = "x264enc bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30"
                encoder = _probe_encoder(self.encoder_preset, self.stream_quality)
                pipeline_str = pipeline_str.replace(encoder, safe_encoder)

                try:
                    self._pipeline = Gst.parse_launch(pipeline_str)
                    bus = self._pipeline.get_bus()
                    bus.add_signal_watch()
                    self._bus_watch_id = bus.connect("message", self._on_bus_message)
                    ret = self._pipeline.set_state(Gst.State.PLAYING)
                except Exception as e:
                    log.error("Failed to parse software fallback pipeline: %s", e)
                    self.last_error = f"Fallback pipeline parse error: {e}"
                    if self.on_error:
                        self.on_error(self.last_error)
                    return False

            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("Failed to start pipeline even with software fallback")
                self.last_error = "Failed to start stream (check GStreamer hardware & software plugins)"
                if self.on_error:
                    self.on_error(self.last_error)
                return False

        self._error_count = 0
        self._target = target
        self._is_casting = True
        self._active_pattern = None

        # Stats timer (1s)
        self._stats_timeout_id = GLib.timeout_add_seconds(1, self._emit_stats)

        log.info(
            "Casting started → %s:%d (video) %s:%d (audio)",
            target.host,
            target.port,
            target.host,
            target.audio_port,
        )
        return True

    async def _prepare_projector_for_stream(self, target: CastTarget) -> None:
        """Switch the projector to LAN source before streaming.

        Sends SOURCE 53 (LAN input) via ESC/VP.net so the projector's
        internal decoder is ready to receive the incoming RTP stream.
        Powers on the projector if it is currently in standby mode.
        """
        try:
            from .protocol import EscVpNetClient, Source
            async with EscVpNetClient(target.host) as client:
                try:
                    pwr = await client.get_power()
                    if pwr == "00":
                        log.info("Projector %s is in standby, powering on before streaming...", target.host)
                        await client.power_on()
                        await asyncio.sleep(1.5)
                except Exception:
                    pass
                await client.set_source(Source.LAN)
                log.info("Switched %s to LAN source (53) for streaming", target.host)
        except Exception as e:
            log.warning(
                "Could not auto-switch %s to LAN source: %s (stream may still work if already on LAN)",
                target.host, e,
            )

    async def start_test_pattern(self, target: CastTarget, pattern: str = "smpte") -> bool:
        """Start casting a GStreamer test pattern instead of screen capture.

        Useful for focus calibration, geometry alignment, and color checking.
        No XDG portal dialog is shown.
        """
        if self._is_casting:
            log.warning("Already casting, stop first")
            return False

        _ensure_gst()

        pattern_id = TEST_PATTERNS.get(pattern, 0)
        encoder = _probe_encoder(self.encoder_preset, self.stream_quality)
        sink = self.sink
        video_sink = sink.build_sink_bin(target)

        pipeline_str = (
            f"videotestsrc pattern={pattern_id} is-live=true ! "
            "video/x-raw,width=1920,height=1080,framerate=30/1 ! "
            "videoconvert ! videoscale ! videoconvert ! "
            f"{encoder} ! h264parse ! "
            f"{video_sink}"
        )
        log.info("Test pattern pipeline: %s", pipeline_str)

        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            log.error("Failed to parse test pattern pipeline: %s", e)
            if self.on_error:
                self.on_error(f"Pipeline error: {e}")
            return False

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        self._bus_watch_id = bus.connect("message", self._on_bus_message)

        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            log.warning("Hardware encoder failed to start, falling back to software x264enc")
            self._pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()
            
            # Re-probe forcing AUTO software fallback (x264enc)
            safe_encoder = "x264enc bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30"
            pipeline_str = pipeline_str.replace(encoder, safe_encoder)
            
            try:
                self._pipeline = Gst.parse_launch(pipeline_str)
            except Exception as e:
                log.error("Failed to parse fallback pipeline: %s", e)
                if self.on_error:
                    self.on_error(f"Fallback pipeline error: {e}")
                return False

            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            self._bus_watch_id = bus.connect("message", self._on_bus_message)
            
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("Failed to start test pattern even with fallback")
                if self.on_error:
                    self.on_error("Failed to start pipeline (Hardware & Software encoding both failed)")
                return False

        self._error_count = 0
        self._target = target
        self._is_casting = True
        self._active_pattern = pattern
        self._stats_timeout_id = GLib.timeout_add_seconds(1, self._emit_stats)

        log.info("Test pattern '%s' casting to %s:%d", pattern, target.host, target.port)
        return True

    def stop(self) -> None:
        """Stop the pipeline and free resources."""
        if not self._is_casting:
            return
        self._is_casting = False

        if self._stats_timeout_id:
            GLib.source_remove(self._stats_timeout_id)
            self._stats_timeout_id = None

        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            if self._bus_watch_id:
                bus = self._pipeline.get_bus()
                if bus:
                    bus.remove_signal_watch()
            self._pipeline = None

        # Close the portal session to release the PipeWire capture
        _close_portal_session()

        self._target = None
        self._active_pattern = None
        log.info("Casting stopped")

    def _build_pipeline(
        self,
        target: CastTarget,
        node_id: int | None,
        is_file: bool,
        enable_audio: bool | None = None,
    ) -> str:
        """Construct the full pipeline description string."""
        # Video source
        if node_id is not None:
            video_src = f"pipewiresrc path={node_id} do-timestamp=true"
        else:
            _ensure_gst()
            registry = Gst.Registry.get()
            if registry.lookup_feature("ximagesrc") and os.environ.get("DISPLAY"):
                video_src = "ximagesrc use-damage=false show-pointer=true"
                log.info("Using X11 ximagesrc for screen capture")
            else:
                video_src = "videotestsrc pattern=smpte is-live=true"
                log.info("Using videotestsrc pattern fallback for stream")

        # Encoder
        encoder = _probe_encoder(self.encoder_preset, self.stream_quality)

        # Sink
        if is_file:
            sink = FileDumpSink()
        else:
            sink = self.sink
        video_sink = sink.build_sink_bin(target)

        # Video branch with proper caps negotiation
        # Limits resolution to 1080p and framerate to 30fps for projector compatibility.
        # Uses videoconvert before the encoder to allow HW encoders to negotiate their 
        # preferred native format (like NV12) instead of hardcoding I420.
        if isinstance(sink, JpegRtpSink):
            video_branch = (
                f"{video_src} ! "
                "videoconvert ! videoscale ! videorate ! "
                "video/x-raw,width=1920,height=1080,framerate=30/1 ! videoconvert ! "
                f"{video_sink}"
            )
        else:
            video_branch = (
                f"{video_src} ! "
                "videoconvert ! videoscale ! videorate ! "
                "video/x-raw,width=1920,height=1080,framerate=30/1 ! videoconvert ! "
                f"{encoder} ! h264parse ! "
                f"{video_sink}"
            )

        # Audio branch
        use_audio = self.audio_enabled if enable_audio is None else enable_audio
        if use_audio and not is_file:
            audio_enc, audio_pay = _probe_audio_encoder()
            if audio_enc and audio_pay:
                _ensure_gst()
                registry = Gst.Registry.get()
                audio_src = ""
                # In PipeWire sessions (Wayland), prefer pipewiresrc.
                # In X11 fallback sessions, prefer pulsesrc (PulseAudio or pipewire-pulse).
                if node_id is not None and registry.lookup_feature("pipewiresrc"):
                    audio_src = (
                        'pipewiresrc do-timestamp=true '
                        'stream-properties="props,media.class=Audio/Sink"'
                    )
                    log.info("Using pipewiresrc for audio capture (desktop audio)")
                elif registry.lookup_feature("pulsesrc"):
                    audio_src = 'pulsesrc device="@DEFAULT_SINK@.monitor" do-timestamp=true'
                    log.info("Using pulsesrc for audio capture (PulseAudio/pipewire-pulse)")
                elif registry.lookup_feature("pipewiresrc"):
                    audio_src = (
                        'pipewiresrc do-timestamp=true '
                        'stream-properties="props,media.class=Audio/Sink"'
                    )
                    log.info("Using pipewiresrc for audio capture")

                if audio_src:
                    audio_branch = (
                        f"{audio_src} ! "
                        "audioconvert ! audioresample ! "
                        "audio/x-raw,format=S16LE,channels=2,rate=48000 ! "
                        f"{audio_enc} ! {audio_pay} ! "
                        f"udpsink host={target.host} port={target.audio_port} sync=false"
                    )
                    return f"{video_branch}   {audio_branch}"

        return video_branch

    def _on_bus_message(self, bus, message) -> bool:
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            
            self._error_count += 1
            error_msg = err.message.lower()
            if self._error_count <= self._max_retries and any(kw in error_msg for kw in ("timeout", "resource", "temporarily")):
                log.warning("Transient GStreamer error (%d/%d): %s\n%s", self._error_count, self._max_retries, err.message, debug)
                log.info("Attempting to restart pipeline...")
                if self._pipeline:
                    self._pipeline.set_state(Gst.State.NULL)
                    ret = self._pipeline.set_state(Gst.State.PLAYING)
                    if ret != Gst.StateChangeReturn.FAILURE:
                        return True
            
            log.error("GStreamer error: %s\n%s", err.message, debug)
            self.stop()
            if self.on_error:
                self.on_error(err.message)
        elif t == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            log.warning("GStreamer warning: %s\n%s", warn.message, debug)
        elif t == Gst.MessageType.EOS:
            log.info("GStreamer: end-of-stream")
            self.stop()
        return True

    def _emit_stats(self) -> bool:
        """Called every 1s by GLib timeout. Returns True to keep timer alive."""
        if not self._is_casting or not self._pipeline:
            return False

        stats = StreamStats(audio_active=self.audio_enabled)

        # Try to get byte-level position for bitrate estimation
        if self._pipeline:
            # Query current position
            ok, pos = self._pipeline.query_position(Gst.Format.TIME)
            if ok and pos > 0:
                stats.latency_ms = pos / Gst.MSECOND

            # Try querying the pipeline for dropped buffers via QoS
            iterator = self._pipeline.iterate_sinks()
            while True:
                result, element = iterator.next()
                if result != Gst.IteratorResult.OK:
                    break
                if hasattr(element, "get_property"):
                    try:
                        # udpsink exposes bytes-served
                        if element.get_factory() and "udpsink" in element.get_factory().get_name():
                            bytes_served = element.get_property("bytes-served")
                            if bytes_served > 0:
                                stats.bitrate_kbps = (bytes_served * 8) / 1000.0
                    except Exception:
                        pass
                        
            # Adaptive bitrate logic
            if stats.latency_ms > 500 or self._error_count > 0:
                # Need to reduce bitrate
                self._adjust_bitrate(down=True)
            elif stats.latency_ms < 100 and self._error_count == 0:
                # Can carefully increase bitrate
                self._adjust_bitrate(down=False)

        if self.on_stats:
            self.on_stats(stats)

        # Periodic stream diagnostics log (every ~5 seconds based on 1s timer)
        if hasattr(self, '_stats_log_counter'):
            self._stats_log_counter += 1
        else:
            self._stats_log_counter = 1

        if self._stats_log_counter % 5 == 0 and self._target:
            log.debug(
                "Stream stats → %s:%d | bitrate=%.0f kbps latency=%.0f ms "
                "dropped=%d audio=%s errors=%d",
                self._target.host, self._target.port,
                stats.bitrate_kbps, stats.latency_ms,
                stats.dropped, stats.audio_active,
                self._error_count,
            )

        return True

    def _adjust_bitrate(self, down: bool):
        """Adjust encoder bitrate up or down."""
        if not self._pipeline:
            return
            
        enc_element = None
        it = self._pipeline.iterate_elements()
        while True:
            res, elem = it.next()
            if res != Gst.IteratorResult.OK:
                break
            if elem.get_factory():
                name = elem.get_factory().get_name()
                if "h264enc" in name or "jpegenc" in name:
                    enc_element = elem
                    break
                    
        if enc_element and hasattr(enc_element, "get_property") and hasattr(enc_element, "set_property"):
            try:
                # E.g. x264enc has 'bitrate' in kbps
                current = enc_element.get_property("bitrate")
                if current:
                    if down and current > 1000:
                        enc_element.set_property("bitrate", int(current * 0.8))
                    elif not down and current < 8000:
                        enc_element.set_property("bitrate", int(current * 1.05))
            except Exception:
                pass


def start_test_pattern(
    host: str,
    pattern_name: str = "smpte",
    port: int = 5004,
    on_stats: Any = None,
    on_error: Any = None,
) -> ScreenCaster:
    """Convenience helper to create and start a ScreenCaster with a test pattern.

    Works whether or not an asyncio event loop is already running.
    """
    target = CastTarget(host=host, port=port, name="Test Pattern")
    caster = ScreenCaster(sink=RtpUdpSink(), on_stats=on_stats, on_error=on_error)

    async def _start():
        await caster.start_test_pattern(target, pattern=pattern_name.lower())

    try:
        loop = asyncio.get_running_loop()
        # Already in an async context — schedule as a task
        loop.create_task(_start())
    except RuntimeError:
        # No running loop — create one
        asyncio.run(_start())

    return caster
