"""
device_row.py — GTK4 List Row Widget for a Discovered Device
============================================================

Displays a single projection target inside the left-panel ListBox.

Visual layout (one row):
  ┌───────────────────────────────────────────────────────┐
  │  [icon]  Device Name          [type badge]  ● / ○    │
  │          192.168.1.100:3629                           │
  └───────────────────────────────────────────────────────┘

  ●  green  = connected & streaming
  ●  amber  = connected, idle
  ○  grey   = discovered, not connected
  ●  red    = error
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango  # type: ignore

from src.models.device import Device

# ── Colour constants for the status dot ──────────────────────────────────────
_STATUS_CSS = """
.status-dot {
    border-radius: 50%;
    min-width:  10px;
    min-height: 10px;
}
.dot-streaming { background-color: #2ec27e; }   /* green  */
.dot-connected { background-color: #e5a50a; }   /* amber  */
.dot-idle      { background-color: #9a9996; }   /* grey   */
.dot-error     { background-color: #e01b24; }   /* red    */

.device-type-badge {
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.75em;
    font-weight: bold;
}
.badge-epson   { background-color: #1c71d8; color: white; }
.badge-eshare  { background-color: #813d9c; color: white; }
.badge-generic { background-color: #5c5c5c; color: white; }
"""


def _load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(_STATUS_CSS.encode())
    Gtk.StyleContext.add_provider_for_display(
        Gtk.Widget.get_default().get_display()
        if hasattr(Gtk.Widget, "get_default") else
        Gtk.Widget().get_display(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class DeviceRow(Gtk.ListBoxRow):
    """
    A single row in the device list.

    Instantiate with a :class:`~src.models.device.Device` and attach to a
    ``Gtk.ListBox``.  Call :meth:`refresh` to update display state after the
    device's ``is_connected`` / ``is_streaming`` flags change.
    """

    def __init__(self, device: Device) -> None:
        super().__init__()
        self.device = device
        self._build_ui()
        self.refresh()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Outer horizontal box with padding
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        self.set_child(outer)

        # ── Device icon ────────────────────────────────────────────────
        icon_name = (
            "video-display-symbolic"
            if self.device.device_type == "eshare"
            else "preferences-desktop-remote-desktop-symbolic"
        )
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        icon.add_css_class("dim-label")
        outer.append(icon)

        # ── Text column (name + address) ───────────────────────────────
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        outer.append(text_box)

        self._name_label = Gtk.Label(label=self.device.name)
        self._name_label.set_halign(Gtk.Align.START)
        self._name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._name_label.add_css_class("heading")
        text_box.append(self._name_label)

        self._addr_label = Gtk.Label(label=self.device.address)
        self._addr_label.set_halign(Gtk.Align.START)
        self._addr_label.add_css_class("caption")
        self._addr_label.add_css_class("dim-label")
        text_box.append(self._addr_label)

        # ── Right side: badge + status dot ────────────────────────────
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right_box.set_valign(Gtk.Align.CENTER)
        outer.append(right_box)

        # Type badge
        self._badge = Gtk.Label(label=self.device.device_type.upper())
        self._badge.add_css_class("device-type-badge")
        self._badge.add_css_class(f"badge-{self.device.device_type}")
        right_box.append(self._badge)

        # Status dot (a tiny DrawingArea-free widget using CSS background)
        self._dot = Gtk.Label(label="")
        self._dot.add_css_class("status-dot")
        right_box.append(self._dot)

    # ── State refresh ─────────────────────────────────────────────────────

    def refresh(self) -> None:
        """
        Re-read ``self.device`` state and update all visual elements.
        Safe to call from any thread via ``GLib.idle_add(row.refresh)``.
        """
        # Update name/address in case discovery enriched the device
        self._name_label.set_label(self.device.name)
        self._addr_label.set_label(self.device.address)

        # ── Status dot ────────────────────────────────────────────────
        for cls in ("dot-streaming", "dot-connected", "dot-idle", "dot-error"):
            self._dot.remove_css_class(cls)

        if self.device.is_streaming:
            self._dot.add_css_class("dot-streaming")
            self._dot.set_tooltip_text("Streaming")
        elif self.device.is_connected:
            self._dot.add_css_class("dot-connected")
            self._dot.set_tooltip_text("Connected")
        else:
            self._dot.add_css_class("dot-idle")
            self._dot.set_tooltip_text("Discovered")

    def set_error(self) -> None:
        """Mark this row as errored (red dot)."""
        for cls in ("dot-streaming", "dot-connected", "dot-idle"):
            self._dot.remove_css_class(cls)
        self._dot.add_css_class("dot-error")
        self._dot.set_tooltip_text("Error")
