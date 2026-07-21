"""
status_bar.py - Stream Status Footer Bar
=========================================

Displays live stream metrics at the bottom of the main window:

  ┌──────────────────────────────────────────────────────────┐
  │  ● Streaming to 192.168.1.100   4.0 Mbps · 30 fps · 42 ms  │
  └──────────────────────────────────────────────────────────┘

Call :meth:`update_stats` from the GLib main loop (e.g. via a
``GLib.timeout_add_seconds`` callback) to refresh the display.
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # type: ignore

from src.streaming.gstreamer_pipeline import StreamStats


class StatusBar(Gtk.Box):
    """
    Footer bar embedded at the bottom of :class:`~src.app_window.AppWindow`.

    Parameters
    ----------
    None - constructed with no arguments; populated via method calls.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self._build_ui()
        self.show_idle()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Status indicator dot (reuse CSS from DeviceRow via app stylesheet)
        self._dot = Gtk.Label(label="●")
        self._dot.add_css_class("dim-label")
        self.append(self._dot)

        # Primary status text
        self._status_label = Gtk.Label()
        self._status_label.set_hexpand(True)
        self._status_label.set_halign(Gtk.Align.START)
        self.append(self._status_label)

        # Metrics cluster (right-aligned)
        self._bitrate_label  = Gtk.Label()
        self._fps_label      = Gtk.Label()
        self._latency_label  = Gtk.Label()

        for lbl in (self._bitrate_label, self._fps_label, self._latency_label):
            lbl.add_css_class("caption")
            lbl.add_css_class("dim-label")
            self.append(lbl)

        # Separator between left status and right metrics
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        self.insert_child_after(sep, self._status_label)

    # ── State setters ─────────────────────────────────────────────────────

    def show_idle(self) -> None:
        """Display the default 'no device connected' state."""
        self._dot.set_label("○")
        self._dot.remove_css_class("success")
        self._dot.remove_css_class("error")
        self._status_label.set_label("No device connected")
        self._bitrate_label.set_label("")
        self._fps_label.set_label("")
        self._latency_label.set_label("")

    def show_connected(self, target_ip: str) -> None:
        """Show 'connected but not streaming' state."""
        self._dot.set_label("●")
        self._dot.add_css_class("success")
        self._dot.remove_css_class("error")
        self._status_label.set_label(f"Connected to {target_ip}")
        self._bitrate_label.set_label("-")
        self._fps_label.set_label("-")
        self._latency_label.set_label("-")

    def show_streaming(self, target_ip: str) -> None:
        """Switch to streaming state (call update_stats for live metrics)."""
        self._dot.set_label("●")
        self._dot.add_css_class("success")
        self._dot.remove_css_class("error")
        self._status_label.set_label(f"Streaming → {target_ip}")

    def show_error(self, message: str) -> None:
        """Display an error state."""
        self._dot.set_label("●")
        self._dot.add_css_class("error")
        self._dot.remove_css_class("success")
        self._status_label.set_label(f"Error: {message}")
        self._bitrate_label.set_label("")
        self._fps_label.set_label("")
        self._latency_label.set_label("")

    def update_stats(self, stats: StreamStats) -> None:
        """
        Refresh the metrics display from a :class:`~src.streaming.gstreamer_pipeline.StreamStats`
        snapshot.  Should be called from the GLib main loop.
        """
        self._bitrate_label.set_label(
            f"{stats.bitrate_kbps / 1000:.1f} Mbps" if stats.bitrate_kbps else "-"
        )
        self._fps_label.set_label(
            f"{stats.fps:.0f} fps" if stats.fps else "-"
        )
        self._latency_label.set_label(
            f"{stats.latency_ms:.0f} ms" if stats.latency_ms else "-"
        )
