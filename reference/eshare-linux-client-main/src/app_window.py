"""
app_window.py - Main Application Window
========================================

Layout (Adw.ApplicationWindow):

  ┌────────────────────────────────────────────────────────────────────┐
  │  Header bar: [☰ menu]   linux-iprojection    [↺ Scan]             │
  ├──────────────────────┬─────────────────────────────────────────────┤
  │  Left panel          │  Right panel (detail)                       │
  │                      │                                             │
  │  ┌────────────────┐  │  Device Name                                │
  │  │ DeviceRow      │  │  192.168.1.100:3629  · Epson               │
  │  ├────────────────┤  │                                             │
  │  │ DeviceRow      │  │  [  ▶ Start Stream  ]  [ ■ Stop ]          │
  │  ├────────────────┤  │                                             │
  │  │ DeviceRow      │  │  ─── Stream Settings ───                    │
  │  └────────────────┘  │  [SettingsPanel]                            │
  │                      │                                             │
  │  [+ Manual IP]       │                                             │
  ├──────────────────────┴─────────────────────────────────────────────┤
  │  StatusBar                                                         │
  └────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

import gi
gi.require_version("Gtk",  "4.0")
gi.require_version("Adw",  "1")
gi.require_version("Gst",  "1.0")

from gi.repository import Adw, GLib, GObject, Gtk  # type: ignore

from src.models.device import Device
from src.discovery.mdns_scanner import MdnsScanner
from src.discovery.ssdp_scanner import SsdpScanner
from src.streaming.gstreamer_pipeline import GStreamerPipeline, EncoderPreset, StreamStats
from src.ui.device_row import DeviceRow
from src.ui.settings_panel import SettingsPanel
from src.ui.status_bar import StatusBar

log = logging.getLogger(__name__)


class AppWindow(Adw.ApplicationWindow):
    """
    The main window of linux-iprojection.

    Manages:
    - Discovery lifecycle (mDNS + SSDP)
    - Device list (left panel ListBox)
    - Detail / controls pane (right panel)
    - GStreamer pipeline start / stop
    - Settings panel binding
    """

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application)
        self.set_title("linux-iprojection")
        self.set_default_size(960, 620)

        # ── State ──────────────────────────────────────────────────────
        self._devices: dict[str, Device] = {}   # ip:port → Device
        self._selected_device: Optional[Device] = None
        self._pipeline: Optional[GStreamerPipeline] = None

        # ── Discovery backends ─────────────────────────────────────────
        self._mdns    = MdnsScanner(on_found=self._on_device_found,
                                    on_lost=self._on_device_lost)
        self._ssdp    = SsdpScanner(on_found=self._on_device_found,
                                    on_lost=self._on_device_lost)

        # ── Build UI ───────────────────────────────────────────────────
        self._build_ui()

        # ── Connect shortcuts ──────────────────────────────────────────
        self.connect("close-request", self._on_close)

    # ══════════════════════════════════════════════════════════════════════
    # UI Construction
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        # Root box (vertical): toolbar + content + status bar
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        # ── Header bar ─────────────────────────────────────────────────
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        # Scan button
        self._scan_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self._scan_btn.set_tooltip_text("Scan for devices")
        self._scan_btn.connect("clicked", self._on_scan_clicked)
        header.pack_end(self._scan_btn)

        # Menu button
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_tooltip_text("Main menu")
        menu = Gtk.PopoverMenu.new_from_model(self._build_menu())
        menu_btn.set_popover(menu)
        header.pack_start(menu_btn)

        root.append(header)

        # ── Content: split pane ────────────────────────────────────────
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(280)
        root.append(paned)

        paned.set_start_child(self._build_left_panel())
        paned.set_end_child(self._build_right_panel())

        # ── Status bar ─────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.append(sep)

        self._status_bar = StatusBar()
        root.append(self._status_bar)

    # ── Left panel (device list) ──────────────────────────────────────

    def _build_left_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Panel title
        lbl = Gtk.Label(label="Devices")
        lbl.add_css_class("title-4")
        lbl.set_margin_start(12)
        lbl.set_margin_top(12)
        lbl.set_margin_bottom(8)
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        # Scrollable list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.append(scroll)

        self._device_list = Gtk.ListBox()
        self._device_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._device_list.add_css_class("boxed-list")
        self._device_list.set_margin_start(8)
        self._device_list.set_margin_end(8)
        self._device_list.set_margin_bottom(8)
        self._device_list.connect("row-selected", self._on_row_selected)
        scroll.set_child(self._device_list)

        # Empty state placeholder
        self._empty_label = Gtk.Label(label="No devices found.\nPress Scan to search.")
        self._empty_label.set_justify(Gtk.Justification.CENTER)
        self._empty_label.add_css_class("dim-label")
        self._empty_label.set_margin_top(32)
        self._device_list.set_placeholder(self._empty_label)

        # Scanning spinner
        self._spinner = Gtk.Spinner()
        self._spinner.set_margin_bottom(4)
        box.append(self._spinner)

        # Manual IP row
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        manual_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        manual_box.set_margin_start(8)
        manual_box.set_margin_end(8)
        manual_box.set_margin_top(6)
        manual_box.set_margin_bottom(8)

        self._manual_entry = Gtk.Entry()
        self._manual_entry.set_placeholder_text("192.168.x.x")
        self._manual_entry.set_hexpand(True)
        self._manual_entry.connect("activate", self._on_manual_add)
        manual_box.append(self._manual_entry)

        add_btn = Gtk.Button(label="Add")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_manual_add)
        manual_box.append(add_btn)

        box.append(manual_box)
        return box

    # ── Right panel (detail + settings) ──────────────────────────────

    def _build_right_panel(self) -> Gtk.Widget:
        self._right_stack = Gtk.Stack()
        self._right_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # ── Empty / no selection ──────────────────────────────────────
        no_sel = Adw.StatusPage(
            icon_name="video-display-symbolic",
            title="No device selected",
            description="Select a device from the list or scan for new ones.",
        )
        self._right_stack.add_named(no_sel, "empty")

        # ── Device detail ─────────────────────────────────────────────
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Device title area
        title_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_bar.set_margin_start(20)
        title_bar.set_margin_end(20)
        title_bar.set_margin_top(20)
        title_bar.set_margin_bottom(12)

        self._detail_name = Gtk.Label(label="")
        self._detail_name.add_css_class("title-2")
        self._detail_name.set_halign(Gtk.Align.START)
        title_bar.append(self._detail_name)

        self._detail_addr = Gtk.Label(label="")
        self._detail_addr.add_css_class("dim-label")
        self._detail_addr.set_halign(Gtk.Align.START)
        title_bar.append(self._detail_addr)

        detail_box.append(title_bar)
        detail_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Controls row
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ctrl_box.set_margin_start(20)
        ctrl_box.set_margin_end(20)
        ctrl_box.set_margin_top(12)
        ctrl_box.set_margin_bottom(12)

        self._start_btn = Gtk.Button(label="▶  Start Stream")
        self._start_btn.add_css_class("suggested-action")
        self._start_btn.add_css_class("pill")
        self._start_btn.connect("clicked", self._on_start_clicked)
        ctrl_box.append(self._start_btn)

        self._stop_btn = Gtk.Button(label="■  Stop")
        self._stop_btn.add_css_class("destructive-action")
        self._stop_btn.add_css_class("pill")
        self._stop_btn.set_sensitive(False)
        self._stop_btn.connect("clicked", self._on_stop_clicked)
        ctrl_box.append(self._stop_btn)

        detail_box.append(ctrl_box)
        detail_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Settings panel
        self._settings_panel = SettingsPanel()
        self._settings_panel.set_vexpand(True)
        detail_box.append(self._settings_panel)

        self._right_stack.add_named(detail_box, "detail")
        self._right_stack.set_visible_child_name("empty")

        return self._right_stack

    def _build_menu(self):
        from gi.repository import Gio  # type: ignore
        menu = Gio.Menu()
        menu.append("About linux-iprojection", "app.about")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        return menu

    # ══════════════════════════════════════════════════════════════════════
    # Discovery callbacks (called from background threads → marshal to GLib)
    # ══════════════════════════════════════════════════════════════════════

    def _on_device_found(self, device: Device) -> None:
        GLib.idle_add(self._add_device, device)

    def _on_device_lost(self, ip: str, port: int) -> None:
        GLib.idle_add(self._remove_device, f"{ip}:{port}")

    def _add_device(self, device: Device) -> bool:
        key = device.address
        if key in self._devices:
            # Update existing row
            self._devices[key] = device
            for row in self._iter_rows():
                if isinstance(row, DeviceRow) and row.device.address == key:
                    row.device = device
                    row.refresh()
            return False

        self._devices[key] = device
        row = DeviceRow(device)
        self._device_list.append(row)
        log.info("UI: added device %s", device.display_label)
        return False   # GLib.idle_add must return False

    def _remove_device(self, key: str) -> bool:
        self._devices.pop(key, None)
        for row in self._iter_rows():
            if isinstance(row, DeviceRow) and row.device.address == key:
                self._device_list.remove(row)
                break
        return False

    def _iter_rows(self):
        row = self._device_list.get_row_at_index(0)
        idx = 0
        while row is not None:
            yield row
            idx += 1
            row = self._device_list.get_row_at_index(idx)

    # ══════════════════════════════════════════════════════════════════════
    # UI signal handlers
    # ══════════════════════════════════════════════════════════════════════

    def _on_scan_clicked(self, _btn) -> None:
        log.info("Scan initiated by user")
        self._spinner.start()
        self._scan_btn.set_sensitive(False)

        self._mdns.start()
        self._ssdp.start()

        # Re-enable scan button after 10 s
        GLib.timeout_add_seconds(10, self._on_scan_timeout)

    def _on_scan_timeout(self) -> bool:
        self._spinner.stop()
        self._scan_btn.set_sensitive(True)
        return False   # one-shot

    def _on_row_selected(self, _list_box, row) -> None:
        if row is None or not isinstance(row, DeviceRow):
            self._selected_device = None
            self._right_stack.set_visible_child_name("empty")
            return

        self._selected_device = row.device
        self._detail_name.set_label(row.device.name)
        self._detail_addr.set_label(
            f"{row.device.address}  ·  {row.device.device_type.capitalize()}"
        )
        self._right_stack.set_visible_child_name("detail")

    def _on_manual_add(self, _widget) -> None:
        text = self._manual_entry.get_text().strip()
        if not text:
            return
        parts = text.split(":")
        ip   = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 3629
        device = Device(
            name=f"Manual ({ip})",
            ip=ip,
            port=port,
            device_type="epson",
            capabilities=["escvpnet", "rtp_recv"],
            discovery_source="manual",
        )
        self._add_device(device)
        self._manual_entry.set_text("")

    def _on_start_clicked(self, _btn) -> None:
        if not self._selected_device:
            return

        d = self._selected_device
        s = self._settings_panel.settings

        log.info("Starting stream to %s", d.address)

        self._pipeline = GStreamerPipeline(
            target_ip=d.ip,
            video_port=s.video_port,
            audio_port=s.audio_port,
            pipewire_node_id=-1,          # -1 = no specific node (auto / portal)
            audio_enabled=s.audio,
            encoder=EncoderPreset[s.encoder.upper()],
            width=s.width  or 1920,
            height=s.height or 1080,
            fps=s.fps,
            bitrate_kbps=s.bitrate,
            on_stats=self._on_stream_stats,
            on_error=self._on_stream_error,
        )

        try:
            self._pipeline.start()
        except Exception as exc:
            self._show_error_toast(str(exc))
            self._pipeline = None
            return

        d.is_streaming = True
        self._start_btn.set_sensitive(False)
        self._stop_btn.set_sensitive(True)
        self._status_bar.show_streaming(d.ip)

        # Refresh the row dot
        for row in self._iter_rows():
            if isinstance(row, DeviceRow) and row.device == d:
                row.refresh()

    def _on_stop_clicked(self, _btn) -> None:
        if self._pipeline:
            self._pipeline.stop()
            self._pipeline = None

        if self._selected_device:
            self._selected_device.is_streaming = False
            self._selected_device.is_connected = False
            for row in self._iter_rows():
                if isinstance(row, DeviceRow) and row.device == self._selected_device:
                    row.refresh()

        self._start_btn.set_sensitive(True)
        self._stop_btn.set_sensitive(False)
        self._status_bar.show_idle()

    def _on_stream_stats(self, stats: StreamStats) -> None:
        GLib.idle_add(self._status_bar.update_stats, stats)

    def _on_stream_error(self, message: str) -> None:
        GLib.idle_add(self._status_bar.show_error, message)
        GLib.idle_add(self._show_error_toast, message)
        GLib.idle_add(self._on_stop_clicked, None)

    def _show_error_toast(self, message: str) -> None:
        toast = Adw.Toast(title=f"Stream error: {message}", timeout=5)
        # ToastOverlay is wrapped by Adw.ApplicationWindow automatically
        # on newer libadwaita; fall back to a simple log if not available
        try:
            overlay = self.get_content()
            if isinstance(overlay, Adw.ToastOverlay):
                overlay.add_toast(toast)
        except Exception:
            log.error("Stream error: %s", message)

    # ══════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def start_discovery(self) -> None:
        """Called by main() after the window is shown."""
        self._on_scan_clicked(None)

    def _on_close(self, _window) -> bool:
        log.info("Window closing - cleaning up …")
        if self._pipeline:
            self._pipeline.stop()
        self._mdns.stop()
        self._ssdp.stop()
        return False   # allow close to proceed
