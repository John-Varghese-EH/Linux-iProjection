"""
gstreamer_pipeline.py - GStreamer Pipeline Builder & Manager
============================================================

Constructs, manages, and monitors the GStreamer pipeline that captures
the desktop and streams it (with audio) to a remote receiver.

Pipeline topology
-----------------

  ┌──────────────────────────────────────────────────────────────────────┐
  │  VIDEO branch                                                        │
  │                                                                      │
  │  [pipewiresrc path=<NODE>]  ← Wayland/PipeWire screen capture       │
  │         │                                                            │
  │  [videoscale] [videorate]   ← resolution + fps normalisation        │
  │         │                                                            │
  │  [videoconvert]             ← colour space (I420/NV12)              │
  │         │                                                            │
  │  [vaapih264enc]  OR                                                  │
  │  [nvv4l2h264enc] OR                                                  │
  │  [x264enc]                  ← HW or SW H.264 encode                 │
  │         │                                                            │
  │  [rtph264pay]               ← packetise into RTP                     │
  │         │                                                            │
  │  [udpsink host=X port=5004] ← send to receiver                      │
  └──────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────┐
  │  AUDIO branch (optional)                                             │
  │                                                                      │
  │  [pipewiresrc]  ← system audio monitor (PipeWire default sink mon.) │
  │         │                                                            │
  │  [audioconvert] [audioresample]                                      │
  │         │                                                            │
  │  [opusenc]  OR  [avenc_aac]                                          │
  │         │                                                            │
  │  [rtpopuspay]  OR  [rtpmp4apay]                                      │
  │         │                                                            │
  │  [udpsink host=X port=5006]                                          │
  └──────────────────────────────────────────────────────────────────────┘

Usage
-----
    from src.streaming.gstreamer_pipeline import GStreamerPipeline, EncoderPreset

    pipe = GStreamerPipeline(
        target_ip="192.168.1.100",
        video_port=5004,
        audio_port=5006,
        pipewire_node_id=42,      # from WaylandCapture
        audio_enabled=True,
        encoder=EncoderPreset.AUTO,
    )
    pipe.start()
    ...
    pipe.stop()

GLib / GTK integration
-----------------------
The pipeline runs inside the GLib main loop via ``Gst.Bus`` watch.
``on_stats`` is called every second with a ``StreamStats`` namedtuple.
``on_error`` is called on any fatal error.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ── OS detection ────────────────────────────────────────────────────────────
# Force mock mode via env var for CI/testing:
#   set LINUX_IPROJECTION_MOCK_PIPELINE=1
IS_WINDOWS: bool = (
    platform.system() == "Windows"
    or os.environ.get("LINUX_IPROJECTION_MOCK_PIPELINE", "") == "1"
)

if IS_WINDOWS:
    log.warning(
        "[WINDOWS MODE] pipewiresrc unavailable - using videotestsrc/audiotestsrc. "
        "All streaming output is synthetic test content only."
    )

# Lazy GStreamer import so the module is importable on non-Linux systems too
_Gst  = None
_GLib = None


def _init_gst() -> None:
    global _Gst, _GLib
    if _Gst is not None:
        return
    try:
        import gi
        gi.require_version("Gst",  "1.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gst, GLib  # type: ignore
        Gst.init(None)
        _Gst  = Gst
        _GLib = GLib
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "GStreamer Python bindings not found.\n"
            "Install: sudo apt install python3-gi gir1.2-gst-plugins-base-1.0"
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Encoder detection
# ──────────────────────────────────────────────────────────────────────────────

class EncoderPreset(Enum):
    AUTO    = auto()   # probe available encoders, pick best
    VAAPI   = auto()   # Intel / AMD VA-API hardware
    NVENC   = auto()   # NVIDIA hardware (nvv4l2h264enc)
    SOFTWARE = auto()  # x264enc (always available)


def _probe_encoder(preferred: EncoderPreset) -> str:
    """
    Return the GStreamer element name for H.264 encoding.
    Falls back gracefully: VAAPI → NVENC → software.
    """
    _init_gst()
    registry = _Gst.Registry.get()

    candidates: list[tuple[str, EncoderPreset]] = [
        ("vaapih264enc",   EncoderPreset.VAAPI),
        ("nvv4l2h264enc",  EncoderPreset.NVENC),
        ("x264enc",        EncoderPreset.SOFTWARE),
    ]

    if preferred != EncoderPreset.AUTO:
        # Only try the chosen encoder, still fall back if unavailable
        candidates = [c for c in candidates if c[1] == preferred] + \
                     [("x264enc", EncoderPreset.SOFTWARE)]

    for elem_name, _ in candidates:
        if registry.find_plugin(elem_name.split("enc")[0]) or \
           registry.lookup_feature(elem_name):
            log.info("Encoder selected: %s", elem_name)
            return elem_name

    log.warning("No H.264 encoder found - defaulting to x264enc (may fail if not installed)")
    return "x264enc"


def _encoder_params(elem_name: str, bitrate_kbps: int) -> str:
    """Return the GStreamer element string (name + properties) for a given encoder."""
    if elem_name == "vaapih264enc":
        return (
            f"vaapih264enc rate-control=cbr bitrate={bitrate_kbps} "
            f"tune=low-power keyframe-period=60"
        )
    if elem_name == "nvv4l2h264enc":
        return (
            f"nvv4l2h264enc bitrate={bitrate_kbps * 1000} "
            f"preset-level=UltraFastPreset iframeinterval=60"
        )
    # x264enc (software fallback)
    return (
        f"x264enc tune=zerolatency bitrate={bitrate_kbps} "
        f"speed-preset=superfast key-int-max=60"
    )


def _probe_audio_encoder() -> tuple[str, str]:
    """
    Return (encoder_element, payloader_element) for audio.
    Prefers Opus; falls back to AAC.
    """
    _init_gst()
    registry = _Gst.Registry.get()
    if registry.lookup_feature("opusenc"):
        return "opusenc bitrate=128000", "rtpopuspay"
    if registry.lookup_feature("avenc_aac"):
        return "avenc_aac bitrate=128000", "rtpmp4apay"
    log.warning("No audio encoder found - audio will be disabled")
    return "", ""


# ──────────────────────────────────────────────────────────────────────────────
# Stream statistics
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StreamStats:
    bitrate_kbps: float = 0.0
    fps:          float = 0.0
    latency_ms:   float = 0.0
    dropped:      int   = 0
    audio_active: bool  = False


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_video_pipeline(
    *,
    pipewire_node_id: int,
    target_ip: str,
    video_port: int,
    width: int,
    height: int,
    fps: int,
    bitrate_kbps: int,
    encoder_elem: str,
) -> str:
    """Return the GStreamer pipeline description for the video branch (Linux / PipeWire)."""
    encoder_str = _encoder_params(encoder_elem, bitrate_kbps)
    return (
        f"pipewiresrc path={pipewire_node_id} do-timestamp=true ! "
        f"video/x-raw,width={width},height={height},framerate={fps}/1 ! "
        f"videoconvert ! "
        f"videoscale ! "
        f"videorate ! "
        f"video/x-raw,format=I420 ! "
        f"{encoder_str} ! "
        f"h264parse ! "
        f"rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={target_ip} port={video_port} sync=false"
    )


def _build_video_pipeline_windows(
    *,
    target_ip: str,
    video_port: int,
    width: int,
    height: int,
    fps: int,
    bitrate_kbps: int,
    encoder_elem: str,
) -> str:
    """
    Windows / CI mock video pipeline.

    Replaces ``pipewiresrc`` with ``videotestsrc`` (SMPTE colour bars) so the
    full encode → RTP → UDP path can be exercised without Wayland.
    """
    encoder_str = _encoder_params(encoder_elem, bitrate_kbps)
    return (
        f"videotestsrc pattern=smpte is-live=true ! "
        f"video/x-raw,width={width},height={height},framerate={fps}/1 ! "
        f"videoconvert ! "
        f"videoscale ! "
        f"videorate ! "
        f"video/x-raw,format=I420 ! "
        f"{encoder_str} ! "
        f"h264parse ! "
        f"rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={target_ip} port={video_port} sync=false"
    )


def _build_audio_pipeline(
    *,
    target_ip: str,
    audio_port: int,
    audio_encoder: str,
    audio_payloader: str,
) -> str:
    """Return the pipeline description string for the audio branch (Linux / PipeWire)."""
    return (
        f"pipewiresrc do-timestamp=true ! "
        f"audio/x-raw,format=F32LE,channels=2,rate=48000 ! "
        f"audioconvert ! "
        f"audioresample ! "
        f"{audio_encoder} ! "
        f"{audio_payloader} pt=97 ! "
        f"udpsink host={target_ip} port={audio_port} sync=false"
    )


def _build_audio_pipeline_windows(
    *,
    target_ip: str,
    audio_port: int,
    audio_encoder: str,
    audio_payloader: str,
) -> str:
    """
    Windows / CI mock audio pipeline.

    Replaces ``pipewiresrc`` with ``audiotestsrc`` (440 Hz sine) so the
    full audio encode → RTP → UDP path can be tested without PipeWire.
    """
    return (
        f"audiotestsrc wave=sine freq=440 is-live=true ! "
        f"audio/x-raw,format=F32LE,channels=2,rate=48000 ! "
        f"audioconvert ! "
        f"audioresample ! "
        f"{audio_encoder} ! "
        f"{audio_payloader} pt=97 ! "
        f"udpsink host={target_ip} port={audio_port} sync=false"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline manager
# ──────────────────────────────────────────────────────────────────────────────

class GStreamerPipeline:
    """
    Manages the full video + audio GStreamer projection pipeline.

    Parameters
    ----------
    target_ip:
        Receiver IP address.
    video_port:
        UDP port for the RTP H.264 video stream.
    audio_port:
        UDP port for the RTP audio stream (Opus or AAC).
    pipewire_node_id:
        PipeWire node ID from :class:`~src.streaming.capture_wayland.WaylandCapture`.
        If -1, a raw ``pipewiresrc`` without a specific path is used (picks default).
    audio_enabled:
        Whether to include the audio branch in the pipeline.
    encoder:
        Encoder preference (AUTO detects best available).
    width, height, fps, bitrate_kbps:
        Stream parameters.
    on_stats:
        Optional callback called every ~1 s with a :class:`StreamStats` snapshot.
    on_error:
        Optional callback called with an error message string on fatal errors.
    """

    def __init__(
        self,
        target_ip: str,
        video_port: int = 5004,
        audio_port: int = 5006,
        pipewire_node_id: int = -1,
        audio_enabled: bool = True,
        encoder: EncoderPreset = EncoderPreset.AUTO,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        bitrate_kbps: int = 4000,
        on_stats: Optional[Callable[[StreamStats], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._target_ip        = target_ip
        self._video_port       = video_port
        self._audio_port       = audio_port
        self._pipewire_node_id = pipewire_node_id
        self._audio_enabled    = audio_enabled
        self._encoder_pref     = encoder
        self._width            = width
        self._height           = height
        self._fps              = fps
        self._bitrate_kbps     = bitrate_kbps
        self._on_stats         = on_stats
        self._on_error         = on_error

        self._pipeline = None    # Gst.Pipeline
        self._bus_watch_id = None
        self._stats_timeout_id = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Build and start the GStreamer pipeline. Idempotent."""
        if self._running:
            log.warning("Pipeline already running - ignoring start()")
            return

        _init_gst()
        encoder_elem = _probe_encoder(self._encoder_pref)

        # ── Build pipeline description ─────────────────────────────────
        if IS_WINDOWS:
            log.warning(
                "[WINDOWS MODE] Building mock pipeline with videotestsrc/audiotestsrc. "
                "No real screen will be captured."
            )
            video_desc = _build_video_pipeline_windows(
                target_ip=self._target_ip,
                video_port=self._video_port,
                width=self._width,
                height=self._height,
                fps=self._fps,
                bitrate_kbps=self._bitrate_kbps,
                encoder_elem=encoder_elem,
            )
        else:
            node = self._pipewire_node_id if self._pipewire_node_id >= 0 else 0
            video_desc = _build_video_pipeline(
                pipewire_node_id=node,
                target_ip=self._target_ip,
                video_port=self._video_port,
                width=self._width,
                height=self._height,
                fps=self._fps,
                bitrate_kbps=self._bitrate_kbps,
                encoder_elem=encoder_elem,
            )

        if self._audio_enabled:
            audio_enc, audio_pay = _probe_audio_encoder()
            if audio_enc and audio_pay:
                if IS_WINDOWS:
                    audio_desc = _build_audio_pipeline_windows(
                        target_ip=self._target_ip,
                        audio_port=self._audio_port,
                        audio_encoder=audio_enc,
                        audio_payloader=audio_pay,
                    )
                else:
                    audio_desc = _build_audio_pipeline(
                        target_ip=self._target_ip,
                        audio_port=self._audio_port,
                        audio_encoder=audio_enc,
                        audio_payloader=audio_pay,
                    )
                full_desc = video_desc + "   " + audio_desc
            else:
                full_desc = video_desc
                self._audio_enabled = False
        else:
            full_desc = video_desc

        log.info("GStreamer pipeline [%s]:\n  %s",
                 "WINDOWS-MOCK" if IS_WINDOWS else "LINUX-LIVE", full_desc)

        err = _GLib.GError()
        self._pipeline = _Gst.parse_launch(full_desc)

        if not self._pipeline:
            raise RuntimeError("Failed to parse GStreamer pipeline.")

        # ── Bus message watch ──────────────────────────────────────────
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        self._bus_watch_id = bus.connect("message", self._on_bus_message)

        # ── Stats timer ────────────────────────────────────────────────
        self._stats_timeout_id = _GLib.timeout_add_seconds(1, self._emit_stats)

        # ── Play! ──────────────────────────────────────────────────────
        ret = self._pipeline.set_state(_Gst.State.PLAYING)
        if ret == _Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer failed to enter PLAYING state.")

        self._running = True
        log.info("Pipeline started → %s:%d (video) %s:%d (audio)",
                 self._target_ip, self._video_port,
                 self._target_ip, self._audio_port)

    def stop(self) -> None:
        """Stop the pipeline and free resources."""
        if not self._running:
            return
        self._running = False

        if self._stats_timeout_id:
            _GLib.source_remove(self._stats_timeout_id)
            self._stats_timeout_id = None

        if self._pipeline:
            self._pipeline.set_state(_Gst.State.NULL)
            if self._bus_watch_id:
                self._pipeline.get_bus().remove_signal_watch()
            self._pipeline = None

        log.info("Pipeline stopped.")

    def set_bitrate(self, bitrate_kbps: int) -> None:
        """
        Dynamically update the encoder bitrate without restarting.
        Only works for vaapih264enc and x264enc (they support dynamic props).
        """
        self._bitrate_kbps = bitrate_kbps
        if not self._pipeline:
            return
        enc = self._pipeline.get_by_name("enc0")
        if enc:
            try:
                enc.set_property("bitrate", bitrate_kbps)
            except Exception as exc:
                log.debug("set_bitrate dynamic update failed: %s", exc)

    # ── GStreamer bus callbacks ────────────────────────────────────────

    def _on_bus_message(self, bus, message) -> None:
        t = message.type
        if t == _Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            log.error("GStreamer error: %s\n%s", err.message, debug)
            self.stop()
            if self._on_error:
                self._on_error(err.message)
        elif t == _Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            log.warning("GStreamer warning: %s\n%s", warn.message, debug)
        elif t == _Gst.MessageType.EOS:
            log.info("GStreamer: end-of-stream")
            self.stop()
        elif t == _Gst.MessageType.STATE_CHANGED:
            if message.src == self._pipeline:
                _, new, _ = message.parse_state_changed()
                log.debug("Pipeline state → %s", new.value_nick)

    def _emit_stats(self) -> bool:
        """Called every 1 s by GLib.timeout_add_seconds. Returns True to repeat."""
        if not self._running or not self._pipeline or not self._on_stats:
            return False

        stats = StreamStats(audio_active=self._audio_enabled)

        # Query the video udpsink for bytes sent
        sink = self._pipeline.get_by_name("udpsink0")
        if sink:
            ok, pos = self._pipeline.query_position(_Gst.Format.TIME)
            if ok:
                stats.latency_ms = pos / _Gst.MSECOND

        self._on_stats(stats)
        return True   # keep the timer alive

    # ── Context manager support ───────────────────────────────────────

    def __enter__(self) -> "GStreamerPipeline":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


# ──────────────────────────────────────────────────────────────────────────────
# CLI pipeline tester (no GTK needed)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    import argparse

    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s")

    p = argparse.ArgumentParser(description="Test GStreamer pipeline against mock receiver")
    p.add_argument("--target",    default="127.0.0.1")
    p.add_argument("--vport",     type=int, default=5004)
    p.add_argument("--aport",     type=int, default=5006)
    p.add_argument("--node",      type=int, default=-1, help="PipeWire node ID")
    p.add_argument("--bitrate",   type=int, default=2000)
    p.add_argument("--no-audio",  action="store_true")
    p.add_argument("--encoder",   choices=["auto","vaapi","nvenc","sw"], default="auto")
    args = p.parse_args()

    enc_map = {"auto": EncoderPreset.AUTO, "vaapi": EncoderPreset.VAAPI,
               "nvenc": EncoderPreset.NVENC, "sw": EncoderPreset.SOFTWARE}

    def on_stats(s: StreamStats) -> None:
        print(f"  stats: {s}")

    def on_error(msg: str) -> None:
        print(f"  ERROR: {msg}")

    pipe = GStreamerPipeline(
        target_ip=args.target,
        video_port=args.vport,
        audio_port=args.aport,
        pipewire_node_id=args.node,
        audio_enabled=not args.no_audio,
        encoder=enc_map[args.encoder],
        bitrate_kbps=args.bitrate,
        on_stats=on_stats,
        on_error=on_error,
    )

    print(f"Starting pipeline → {args.target}:{args.vport} (video) {args.aport} (audio)")
    print("Ctrl+C to stop\n")

    pipe.start()
    try:
        _init_gst()
        loop = _GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipe.stop()
        print("\nPipeline stopped.")
