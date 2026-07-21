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
from typing import Callable, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, Gst  # noqa: E402

log = logging.getLogger(__name__)

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


# Encoder detection


def _probe_encoder(preset: EncoderPreset = EncoderPreset.AUTO, quality: str = "balanced") -> str:
    """Detect best available H.264 encoder. Falls back to x264enc."""
    _ensure_gst()
    registry = Gst.Registry.get()

    if quality == "low_latency":
        x264_params = "bitrate=2000 speed-preset=ultrafast tune=zerolatency key-int-max=15"
        vaapi_params = "rate-control=cbr bitrate=2000 keyframe-period=15"
        nvenc_params = "bitrate=2000000 preset-level=UltraFastPreset"
    elif quality == "high_quality":
        x264_params = "bitrate=8000 speed-preset=fast tune=zerolatency key-int-max=60"
        vaapi_params = "rate-control=cbr bitrate=8000 keyframe-period=60"
        nvenc_params = "bitrate=8000000 preset-level=HighQualityPreset"
    else:  # balanced
        x264_params = "bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30"
        vaapi_params = "rate-control=cbr bitrate=4000 keyframe-period=30"
        nvenc_params = "bitrate=4000000 preset-level=FastPreset"

    candidates = [
        (EncoderPreset.VAAPI, "vaapih264enc", f"vaapih264enc {vaapi_params}"),
        (EncoderPreset.NVENC, "nvv4l2h264enc", f"nvv4l2h264enc {nvenc_params}"),
        (EncoderPreset.SOFTWARE, "x264enc", f"x264enc {x264_params}"),
    ]

    for enc_preset, element_name, element_str in candidates:
        if preset not in (EncoderPreset.AUTO, enc_preset):
            continue
        if registry.lookup_feature(element_name):
            log.info("Encoder selected: %s", element_name)
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


async def _request_portal_stream() -> Optional[int]:
    """Walk the xdg-desktop-portal ScreenCast flow and return a PipeWire node ID.

    Returns None if the user cancels the dialog or something goes wrong.
    Uses Gio.DBusProxy (no extra dependency beyond PyGObject).
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as e:
        log.error("Cannot connect to session D-Bus: %s", e)
        return None

    portal_proxy = Gio.DBusProxy.new_sync(
        bus,
        Gio.DBusProxyFlags.NONE,
        None,
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.ScreenCast",
        None,
    )

    token = f"linux-iprojection_{os.getpid()}"
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
                        Exception("User dismissed the screen sharing dialog"),
                    )
                else:
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        Exception(f"Portal error (code {response_code})"),
                    )

        handler_id = request_proxy.connect("g-signal", on_signal)

        try:
            portal_proxy.call_sync(method, args, Gio.DBusCallFlags.NONE, 30000, None)
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
                        "types": GLib.Variant("u", 3),  # 1=Monitor, 2=Window -> 3=Both
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
        return node_id

    except Exception as e:
        log.warning("Portal ScreenCast failed: %s", e)
        return None


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

    @property
    def is_casting(self) -> bool:
        return self._is_casting

    async def start(self, target: CastTarget) -> bool:
        """Request a portal stream and start the GStreamer pipeline.

        Returns True if casting started successfully.
        """
        if self._is_casting:
            log.warning("Already casting - call stop() first")
            return False

        _ensure_gst()

        # Determine if this is a dry-run (file target)
        is_file = target.host.startswith("/") or target.host.endswith(".mp4")

        # Get PipeWire node for real casting
        node_id = None
        if not is_file:
            node_id = await _request_portal_stream()
            if node_id is None:
                log.info("Portal cancelled or failed - not casting")
                return False

        # Build the pipeline
        pipeline_str = self._build_pipeline(target, node_id, is_file)
        log.info("GStreamer pipeline: %s", pipeline_str)

        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            log.error("Failed to parse pipeline: %s", e)
            if self.on_error:
                self.on_error(f"Pipeline parse error: {e}")
            return False

        # Bus monitoring
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        self._bus_watch_id = bus.connect("message", self._on_bus_message)

        # Start playing
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            log.error("Failed to enter PLAYING state")
            if self.on_error:
                self.on_error("GStreamer failed to start")
            return False

        self._target = target
        self._is_casting = True

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

        self._target = None
        log.info("Casting stopped")

    def _build_pipeline(
        self,
        target: CastTarget,
        node_id: int | None,
        is_file: bool,
    ) -> str:
        """Construct the full pipeline description string."""
        # Video source
        if node_id is not None:
            video_src = f"pipewiresrc path={node_id} do-timestamp=true"
        else:
            video_src = "videotestsrc pattern=smpte is-live=true"

        # Encoder
        encoder = _probe_encoder(self.encoder_preset, self.stream_quality)

        # Sink
        if is_file:
            sink = FileDumpSink()
        else:
            sink = self.sink
        video_sink = sink.build_sink_bin(target)

        video_branch = (
            f"{video_src} ! "
            "videoconvert ! videoscale ! videorate ! "
            "video/x-raw,format=I420 ! "
            f"{encoder} ! h264parse ! "
            f"{video_sink}"
        )

        # Audio branch
        if self.audio_enabled and not is_file:
            audio_enc, audio_pay = _probe_audio_encoder()
            if audio_enc and audio_pay:
                audio_branch = (
                    "pipewiresrc do-timestamp=true ! "
                    "audio/x-raw,format=F32LE,channels=2,rate=48000 ! "
                    "audioconvert ! audioresample ! "
                    f"{audio_enc} ! {audio_pay} ! "
                    f"udpsink host={target.host} port={target.audio_port} sync=false"
                )
                return f"{video_branch}   {audio_branch}"

        return video_branch

    def _on_bus_message(self, bus, message) -> bool:
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
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

        # Try to get position info for basic stats
        if self._pipeline:
            ok, pos = self._pipeline.query_position(Gst.Format.TIME)
            if ok:
                stats.latency_ms = pos / Gst.MSECOND

        if self.on_stats:
            self.on_stats(stats)
        return True
