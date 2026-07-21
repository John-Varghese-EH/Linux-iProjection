"""
Screen casting to an Epson/EShare receiver.

This module is split into two halves with very different confidence levels:

CAPTURE (solid, standards-based):
    Ask the user's compositor for a screen/window via the XDG Desktop
    Portal `org.freedesktop.portal.ScreenCast` interface. This is the
    correct, compositor-agnostic way to capture on Wayland and is what
    GNOME, KDE, niri (via xdg-desktop-portal-gnome/-wlr) and Hyprland
    (via xdg-desktop-portal-hyprland) all implement. The portal hands
    back a PipeWire node id; GStreamer's `pipewiresrc` reads frames from
    it directly — no compositor-specific code needed here.

DELIVERY (unconfirmed — needs the reference project's protocol):
    How `eshare-linux-client` gets encoded frames onto the wire to an
    Epson EShare receiver is not something I have verified documentation
    for. Rather than guess at a wire format, `CastSink` below is an
    abstract seam: implement `build_sink_bin()` once we've read that
    protocol out of the reference repo (likely RTSP/RTP to the port
    found via mDNS, given it's a GStreamer-based project — but confirm
    before relying on it). Until then, `FileDumpSink` lets you test the
    capture half end-to-end by writing to a local file.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

log = logging.getLogger(__name__)


@dataclass
class CastTarget:
    host: str
    port: int
    name: str = ""


class CastSink(ABC):
    """A pluggable GStreamer sink chain (as a bin description string)
    that consumes an H.264-encoded stream and delivers it to a projector.
    """

    @abstractmethod
    def build_sink_bin(self, target: CastTarget) -> str:
        """Return a `gst-launch`-style bin description string for
        everything downstream of the encoder, e.g. muxing + network sink.
        """


class FileDumpSink(CastSink):
    """Test sink: writes the encoded stream to a local .mp4 instead of
    the network, so you can verify capture + encode work before the
    delivery protocol is confirmed.
    """

    def build_sink_bin(self, target: CastTarget) -> str:
        return f'mp4mux ! filesink location="{target.host}"'


class RtspPushSink(CastSink):
    """PLACEHOLDER — do not treat as correct.

    If the reference project turns out to use RTSP push to the
    projector's EShare port, this is the shape it'd take. Left disabled
    (raises) until confirmed against the actual protocol, so it can't
    silently produce a pipeline that just fails against a real device.
    """

    def build_sink_bin(self, target: CastTarget) -> str:
        raise NotImplementedError(
            "EShare delivery protocol not yet confirmed — see module docstring. "
            "Inspect eshare-linux-client's GStreamer pipeline construction and "
            "fill this in."
        )


class ScreenCaster:
    """Owns the portal session + GStreamer pipeline lifecycle.

    Usage:
        caster = ScreenCaster(sink=FileDumpSink())
        await caster.start(CastTarget(host="/tmp/test.mp4", port=0))
        ...
        caster.stop()
    """

    def __init__(self, sink: CastSink):
        Gst.init(None)
        self.sink = sink
        self._pipeline: Gst.Pipeline | None = None
        self._portal_session = None  # set by _request_portal_stream()

    async def _request_portal_stream(self) -> int:
        """Negotiate a ScreenCast session over the XDG portal and return
        the PipeWire node id to read frames from.

        Implemented via the `pipewiresrc` GStreamer element combined with
        the portal request; on most desktop-portal-capable GStreamer
        builds, `pipewiresrc ! ... ` can be driven directly through
        `gtk4paintablesink`/`GstGtk4` widgets or the lower-level
        `Gio.DBusProxy` portal calls. For a first working version, the
        simplest reliable path is delegating capture selection to
        `pipewiresrc target-object=<node-id>` after an explicit portal
        request via `xdg-desktop-portal`'s D-Bus API (python-dbus or
        `Gio.DBusProxy`). That D-Bus negotiation is a few dozen lines on
        its own — flag if you want it filled in next; keeping this
        function isolated here is what makes that a self-contained
        follow-up rather than a rewrite.
        """
        raise NotImplementedError(
            "Portal ScreenCast D-Bus negotiation not yet implemented — "
            "isolated here so it's a clean follow-up task."
        )

    def build_pipeline(self, node_id: int, target: CastTarget) -> Gst.Pipeline:
        sink_desc = self.sink.build_sink_bin(target)
        desc = (
            f"pipewiresrc path={node_id} ! "
            "videoconvert ! "
            "x264enc tune=zerolatency bitrate=8000 speed-preset=veryfast key-int-max=30 ! "
            "h264parse ! "
            f"{sink_desc}"
        )
        log.info("Building pipeline: %s", desc)
        return Gst.parse_launch(desc)

    async def start(self, target: CastTarget) -> None:
        node_id = await self._request_portal_stream()
        self._pipeline = self.build_pipeline(node_id, target)
        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
