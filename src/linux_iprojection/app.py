"""
linux-iprojection - main application
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

GTK4 + libadwaita UI for controlling and casting to Epson projectors.
Runs async control/discovery calls on background threads, marshalling
results back to the UI thread via GLib.idle_add.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .client import ProjectorClient  # noqa: E402
from .config import AppConfig, DeviceStore, load_config, save_config, setup_logging  # noqa: E402
from .discovery import DiscoveredDevice, discover_all  # noqa: E402
from .protocol import Source  # noqa: E402

log = logging.getLogger(__name__)
APP_ID = "dev.linux_iprojection.LinuxIProjection"


# Version


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("linux-iprojection")
    except Exception:
        try:
            from . import __version__

            return __version__
        except Exception:
            return "0.1.0"


# Async helper


def _run_async(coro):
    """Run an async coroutine on a background thread, marshal result back
    to the UI thread via GLib.idle_add."""

    def decorator(callback):
        def worker():
            try:
                result = asyncio.run(coro)
                error = None
            except Exception as e:
                result, error = None, e
            GLib.idle_add(callback, result, error)

        threading.Thread(target=worker, daemon=True).start()

    return decorator


# Device list row


class DeviceRow(Adw.ActionRow):
    """A row in the sidebar device list."""

    def __init__(self, device: DiscoveredDevice):
        title = device.alias if device.alias else (device.name or device.address)
        super().__init__(
            title=title,
            subtitle=device.address,
        )
        self.device = device

        # Icon based on discovery source
        icon_name = "video-display-symbolic"
        if hasattr(device, "device_type"):
            if device.device_type == "eshare":
                icon_name = "screen-shared-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        self.add_prefix(icon)

        # Source badge
        if device.source == "mdns":
            badge = Gtk.Label(
                label="mDNS",
                css_classes=["caption", "dim-label"],
                valign=Gtk.Align.CENTER,
            )
            self.add_suffix(badge)

        self.set_activatable(True)

    def update_from(self, device: DiscoveredDevice) -> None:
        self.device = device
        title = device.alias if device.alias else (device.name or device.address)
        self.set_title(title)
        self.set_subtitle(device.address)


# Main window


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(
            application=app,
            title="iProjection (Unofficial)",
            default_width=820,
            default_height=620,
        )

        self.current_device: DiscoveredDevice | None = None
        self._config: AppConfig = load_config()
        self._device_store = DeviceStore()
        self._polling_source_id: int | None = None
        self._is_casting = False
        self._caster = None

        # Build the whole UI
        self._build_ui()
        self._setup_actions()
        self._setup_shortcuts()

        # Load persisted devices, then scan
        self._load_persisted_devices()
        self.on_refresh(None)

        # Start polling if auto-connect
        self._start_polling()

    # UI Construction

    def _build_ui(self) -> None:
        # Main vertical box holds everything
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Top-level toolbar view with global header bar
        self.split = Adw.NavigationSplitView(vexpand=True)

        # Sidebar
        sidebar_page = Adw.NavigationPage(title="Projectors", tag="sidebar")
        sidebar_toolbar = Adw.ToolbarView()

        sidebar_header = Adw.HeaderBar()
        self.refresh_btn = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Scan for projectors",
        )
        self.refresh_btn.connect("clicked", self.on_refresh)
        sidebar_header.pack_start(self.refresh_btn)

        self.add_manual_btn = Gtk.Button(
            icon_name="list-add-symbolic",
            tooltip_text="Add projector by IP",
        )
        self.add_manual_btn.connect("clicked", self.on_add_manual)
        sidebar_header.pack_end(self.add_manual_btn)

        sidebar_toolbar.add_top_bar(sidebar_header)

        # Device list + status/loading stacks
        self.sidebar_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
        )

        # Empty state
        self.empty_status = Adw.StatusPage(
            title="No projectors found",
            description="Scan the network or add one by IP address",
            icon_name="network-wireless-symbolic",
        )

        empty_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER
        )
        refresh_btn_large = Gtk.Button(label="Refresh", css_classes=["pill", "suggested-action"])
        refresh_btn_large.connect("clicked", self.on_refresh)
        add_manual_btn_large = Gtk.Button(label="Add Manual IP", css_classes=["pill"])
        add_manual_btn_large.connect("clicked", self.on_add_manual)

        empty_actions.append(refresh_btn_large)
        empty_actions.append(add_manual_btn_large)
        self.empty_status.set_child(empty_actions)

        self.sidebar_stack.add_named(self.empty_status, "empty")

        # Loading state
        loading_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Scanning network…", css_classes=["dim-label"]))
        self.sidebar_stack.add_named(loading_box, "loading")

        # Device list
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.device_list = Gtk.ListBox(
            css_classes=["boxed-list"],
            margin_start=12,
            margin_end=12,
            margin_top=12,
            margin_bottom=12,
        )
        self.device_list.connect("row-activated", self.on_device_selected)
        list_scroller = Gtk.ScrolledWindow(child=self.device_list, vexpand=True)
        list_box.append(list_scroller)
        self.sidebar_stack.add_named(list_box, "list")

        sidebar_toolbar.set_content(self.sidebar_stack)
        sidebar_page.set_child(sidebar_toolbar)
        self.split.set_sidebar(sidebar_page)

        # Content pane
        content_page = Adw.NavigationPage(title="Control", tag="content")
        content_toolbar = Adw.ToolbarView()

        content_header = Adw.HeaderBar()

        # Hamburger menu
        menu_btn = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text="Main menu",
            primary=True,
        )
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About iProjection", "app.about")
        menu_btn.set_menu_model(menu)
        content_header.pack_end(menu_btn)

        content_toolbar.add_top_bar(content_header)

        # Content stack: empty state vs control panel vs casting state
        self.content_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
        )
        self.content_stack.add_named(self._build_empty_state(), "empty")
        self.content_stack.add_named(self._build_control_panel(), "control")
        self.content_stack.add_named(self._build_casting_panel(), "casting")
        content_toolbar.set_content(self.content_stack)
        content_page.set_child(content_toolbar)
        self.split.set_content(content_page)

        # Error banner
        self.error_banner = Adw.Banner(
            title="",
            revealed=False,
        )

        # Assemble
        main_box.append(self.error_banner)
        main_box.append(self.split)

        # Watermark footer - always visible, outside scrollable areas
        watermark_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            margin_top=4,
            margin_bottom=6,
        )
        watermark_btn = Gtk.LinkButton(
            uri="https://www.linkedin.com/in/John--Varghese",
            child=Gtk.Label(
                label="John Varghese (J0X) - Fueled by ☕️ and rainy days",
                css_classes=["dim-label", "caption"],
            ),
        )
        watermark_btn.set_has_frame(False)
        watermark_box.append(watermark_btn)
        main_box.append(watermark_box)

        # Wrap everything in ToastOverlay (exactly once)
        self.toast_overlay = Adw.ToastOverlay(child=main_box)
        self.set_content(self.toast_overlay)

        # Responsive breakpoint
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 500sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

    def _build_empty_state(self) -> Gtk.Widget:
        return Adw.StatusPage(
            title="Select a projector",
            description="Choose a device from the sidebar to view controls",
            icon_name="video-display-symbolic",
        )

    def _build_control_panel(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=24,
            margin_bottom=24,
        )

        self.device_title = Gtk.Label(css_classes=["title-1"], xalign=0)
        self.device_subtitle = Gtk.Label(
            css_classes=["dim-label"],
            xalign=0,
        )
        box.append(self.device_title)
        box.append(self.device_subtitle)

        # Action Grid (Dashboard)
        action_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=16, halign=Gtk.Align.CENTER
        )

        def _build_action_toggle(icon_name: str, label: str) -> Gtk.ToggleButton:
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(24)
            vbox.append(icon)
            lbl = Gtk.Label(label=label, css_classes=["caption"])
            vbox.append(lbl)
            btn = Gtk.ToggleButton(child=vbox)
            btn.set_size_request(80, 80)
            return btn

        self.power_btn = _build_action_toggle("system-shutdown-symbolic", "Power")
        self.power_btn.connect("toggled", self.on_power_toggled)
        action_box.append(self.power_btn)

        self.mute_btn = _build_action_toggle("video-display-symbolic", "A/V Mute")
        self.mute_btn.connect("toggled", self.on_mute_toggled)
        action_box.append(self.mute_btn)

        self.freeze_btn = _build_action_toggle("media-playback-pause-symbolic", "Freeze")
        self.freeze_btn.connect("toggled", self.on_freeze_toggled)
        action_box.append(self.freeze_btn)

        box.append(action_box)

        # Volume
        vol_group = Adw.PreferencesGroup(title="Audio")
        vol_row = Adw.ActionRow(title="Volume")

        vol_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER
        )
        vol_box.append(Gtk.Image.new_from_icon_name("audio-volume-low-symbolic"))

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.vol_scale.set_size_request(160, -1)
        self.vol_scale.set_draw_value(False)
        self.vol_scale.connect("change-value", self.on_volume_scroll)  # handle smooth scroll
        self.vol_scale.connect("value-changed", self.on_volume_changed)
        vol_box.append(self.vol_scale)
        vol_box.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))

        vol_row.add_suffix(vol_box)
        vol_group.add(vol_row)
        box.append(vol_group)

        # Input source
        source_group = Adw.PreferencesGroup(title="Input Source")
        source_row = Adw.ActionRow(title="Active source")
        source_names = [s.name.replace("_", " ").title() for s in Source]
        self.source_dropdown = Gtk.DropDown.new_from_strings(source_names)
        self.source_dropdown.connect("notify::selected", self.on_source_changed)
        source_row.add_suffix(self.source_dropdown)
        source_group.add(source_row)
        box.append(source_group)

        # Advanced Picture Settings
        picture_group = Adw.PreferencesGroup(
            title="Advanced Picture Settings",
            description="Fine-tune your projector's display capabilities",
        )

        self.color_mode_row = Adw.ComboRow(
            title="Color Mode", subtitle="Requires supported hardware"
        )
        from .protocol import AspectRatio, ColorMode, LuminanceMode

        self.color_model = Gtk.StringList.new([m.name.replace("_", " ").title() for m in ColorMode])
        self.color_mode_row.set_model(self.color_model)
        self.color_mode_row.connect("notify::selected", self.on_color_mode_changed)
        picture_group.add(self.color_mode_row)

        self.aspect_row = Adw.ComboRow(title="Aspect Ratio")
        self.aspect_model = Gtk.StringList.new(
            [m.name.replace("_", " ").title() for m in AspectRatio]
        )
        self.aspect_row.set_model(self.aspect_model)
        self.aspect_row.connect("notify::selected", self.on_aspect_changed)
        picture_group.add(self.aspect_row)

        self.luminance_row = Adw.ComboRow(title="Luminance (Eco Mode)")
        self.luminance_model = Gtk.StringList.new(
            [m.name.replace("_", " ").title() for m in LuminanceMode]
        )
        self.luminance_row.set_model(self.luminance_model)
        self.luminance_row.connect("notify::selected", self.on_luminance_changed)
        picture_group.add(self.luminance_row)

        box.append(picture_group)

        # Remote Control D-Pad
        remote_group = Adw.PreferencesGroup(title="Remote Control")
        dpad_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
            margin_top=12,
            margin_bottom=12,
        )
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)

        def _build_dpad_btn(icon_name: str, key_code: str, css_class="circular") -> Gtk.Button:
            if icon_name.startswith("label:"):
                btn = Gtk.Button(label=icon_name.split(":")[1], css_classes=[css_class])
            else:
                btn = Gtk.Button(icon_name=icon_name, css_classes=[css_class])
            btn.set_size_request(48, 48)
            btn.connect("clicked", lambda x: self.on_remote_key(key_code))
            return btn

        # Top Row (Menu, Esc)
        top_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=32,
            halign=Gtk.Align.CENTER,
            margin_bottom=16,
        )
        top_row.append(_build_dpad_btn("label:Menu", "43", "pill"))
        top_row.append(_build_dpad_btn("label:Esc", "05", "pill"))
        dpad_box.append(top_row)

        # D-Pad
        grid.attach(_build_dpad_btn("go-up-symbolic", "35"), 1, 0, 1, 1)
        grid.attach(_build_dpad_btn("go-previous-symbolic", "5B"), 0, 1, 1, 1)
        grid.attach(_build_dpad_btn("label:OK", "49", "suggested-action"), 1, 1, 1, 1)
        grid.attach(_build_dpad_btn("go-next-symbolic", "5C"), 2, 1, 1, 1)
        grid.attach(_build_dpad_btn("go-down-symbolic", "36"), 1, 2, 1, 1)
        dpad_box.append(grid)

        # Bottom Row (A/V Mute, Source Search)
        bottom_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=32,
            halign=Gtk.Align.CENTER,
            margin_top=16,
        )
        bottom_row.append(_build_dpad_btn("label:A/V Mute", "3E", "pill"))
        bottom_row.append(_build_dpad_btn("label:Search", "67", "pill"))
        dpad_box.append(bottom_row)

        # Extra Row (User, Default)
        extra_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=32,
            halign=Gtk.Align.CENTER,
            margin_top=16,
        )
        extra_row.append(_build_dpad_btn("label:User", "48", "pill"))
        extra_row.append(_build_dpad_btn("label:Default", "4A", "pill"))
        dpad_box.append(extra_row)

        # Volume Row (Vol-, Vol+)
        vol_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=32,
            halign=Gtk.Align.CENTER,
            margin_top=16,
        )
        vol_row.append(_build_dpad_btn("label:Vol -", "59", "pill"))
        vol_row.append(_build_dpad_btn("label:Vol +", "58", "pill"))
        dpad_box.append(vol_row)

        # We must place the dpad_box into a generic widget or a bin inside PreferencesGroup.
        # However, PreferencesGroup doesn't require rows, it can accept any widget directly in libadwaita >= 1.2
        # Let's wrap it in a listbox row to be safe and clean.
        dpad_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        dpad_row.set_child(dpad_box)
        dpad_listbox = Gtk.ListBox(css_classes=["boxed-list"])
        dpad_listbox.append(dpad_row)

        # Adw.PreferencesGroup add() takes widgets directly, but they usually look better if they are rows.
        # In Adw 1.4+, we can just append a row.
        remote_group.add(dpad_listbox)
        box.append(remote_group)

        # Status
        status_group = Adw.PreferencesGroup(
            title="Status", description="Real-time projector information"
        )
        self.lamp_row = Adw.ActionRow(title="Lamp hours", subtitle="-")
        self.power_row = Adw.ActionRow(title="Power state", subtitle="-")
        self.source_row = Adw.ActionRow(title="Current source", subtitle="-")
        status_group.add(self.lamp_row)
        status_group.add(self.power_row)
        status_group.add(self.source_row)

        self.device_info_row = Adw.ActionRow(
            title="Device Information", subtitle="View hardware details"
        )
        self.device_info_btn = Gtk.Button(label="View", valign=Gtk.Align.CENTER)
        self.device_info_btn.connect("clicked", self._show_device_info)
        self.device_info_row.add_suffix(self.device_info_btn)
        self.device_info_row.set_activatable_widget(self.device_info_btn)
        status_group.add(self.device_info_row)

        box.append(status_group)

        # Cast
        cast_group = Adw.PreferencesGroup(
            title="Screen Casting",
            description="Wirelessly mirror your screen directly to the projector",
        )
        cast_row = Adw.ActionRow(
            title="Cast Screen or Window",
            subtitle="Stream your desktop or a specific app via PipeWire",
        )
        self.cast_btn = Gtk.Button(
            label="Start Casting",
            css_classes=["suggested-action"],
            valign=Gtk.Align.CENTER,
        )
        self.cast_btn.connect("clicked", self.on_cast_clicked)
        cast_row.add_suffix(self.cast_btn)
        cast_group.add(cast_row)

        # Split position
        self.split_pos_row = Adw.ComboRow(
            title="Multi-PC Projection",
            subtitle="Choose your quadrant (Full screen by default)",
        )
        self.split_pos_model = Gtk.StringList.new(
            ["Full Screen", "Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"]
        )
        self.split_pos_row.set_model(self.split_pos_model)
        cast_group.add(self.split_pos_row)

        # Audio toggle
        audio_row = Adw.ActionRow(
            title="Include audio",
            subtitle="Stream system audio alongside video",
        )
        self.audio_switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=True)
        audio_row.add_suffix(self.audio_switch)
        audio_row.set_activatable_widget(self.audio_switch)
        cast_group.add(audio_row)
        box.append(cast_group)

        # Advanced Console
        console_group = Adw.PreferencesGroup(
            title="Advanced Console", description="Send raw ESC/VP or PJLink commands directly"
        )

        console_row = Adw.EntryRow(title="Raw Command")
        console_btn = Gtk.Button(label="Send", valign=Gtk.Align.CENTER)
        console_btn.connect("clicked", self._on_console_send_clicked, console_row)
        console_row.add_suffix(console_btn)

        self.console_output = Gtk.Label(
            label="Ready.",
            css_classes=["dim-label", "monospace"],
            halign=Gtk.Align.START,
            wrap=True,
            margin_top=8,
            margin_start=12,
            margin_bottom=8,
        )

        console_group.add(console_row)
        console_group.add(self.console_output)
        box.append(console_group)

        clamp = Adw.Clamp(child=box, maximum_size=600, margin_start=16, margin_end=16)
        scroller = Gtk.ScrolledWindow(child=clamp, vexpand=True)
        return scroller

    def _build_casting_panel(self) -> Gtk.Widget:
        """Panel shown while actively casting."""
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=48,
            margin_bottom=48,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )

        icon = Gtk.Image.new_from_icon_name("screen-shared-symbolic")
        icon.set_pixel_size(64)
        icon.set_css_classes(["accent"])
        box.append(icon)

        self.casting_title = Gtk.Label(
            label="Casting to projector",
            css_classes=["title-1"],
        )
        box.append(self.casting_title)

        self.casting_status = Gtk.Label(
            label="Streaming…",
            css_classes=["dim-label"],
        )
        box.append(self.casting_status)

        # Stats
        stats_group = Adw.PreferencesGroup(title="Stream")
        self.stats_bitrate_row = Adw.ActionRow(title="Bitrate", subtitle="-")
        self.stats_fps_row = Adw.ActionRow(title="Status", subtitle="Active")
        stats_group.add(self.stats_bitrate_row)
        stats_group.add(self.stats_fps_row)
        box.append(stats_group)

        # Stop button
        stop_btn = Gtk.Button(
            label="Stop Casting",
            css_classes=["destructive-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        stop_btn.connect("clicked", self.on_stop_cast_clicked)
        box.append(stop_btn)

        clamp = Adw.Clamp(child=box, maximum_size=600, margin_start=16, margin_end=16)
        return clamp

    # Actions & Shortcuts

    def _setup_actions(self) -> None:
        app = self.get_application()

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about)
        app.add_action(about_action)

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._show_preferences)
        app.add_action(prefs_action)

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self._show_shortcuts)
        app.add_action(shortcuts_action)

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda *_: self._refresh_status())
        app.add_action(refresh_action)

    def _setup_shortcuts(self) -> None:
        app = self.get_application()
        app.set_accels_for_action("app.preferences", ["<Control>comma"])
        app.set_accels_for_action("app.shortcuts", ["<Control>question"])

    # About dialog

    def _show_about(self, *_args) -> None:
        from .config import get_state_dir

        log_path = get_state_dir() / "linux-iprojection.log"

        about = Adw.AboutWindow(
            transient_for=self,
            application_name="iProjection",
            application_icon="dev.linux_iprojection.LinuxIProjection",
            version=_get_version(),
            developer_name="John Varghese (J0X)",
            website="https://github.com/John-Varghese-EH",
            issue_url="https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux/issues",
            license_type=Gtk.License.AGPL_3_0,
            comments="The ultimate, enterprise-grade controller for your Epson projector.\n"
            "Take complete command over network and mDNS projection. Features advanced diagnostic tools,\n"
            "custom alias management, direct ESC/VP console access, and native PipeWire screen casting-all\n"
            "packaged in a sleek, responsive GTK4 design.\n\n"
            "Note: This is an unofficial, community-driven application. Not affiliated with Seiko Epson Corporation.",
        )
        about.add_credit_section(
            "Architect &amp; Lead Developer",
            [
                "John Varghese (J0X) - Hey, I'm John. I built this app because I was frustrated\n"
                "by the lack of native Linux support for Epson's enterprise hardware. My goal was\n"
                "to bridge that gap and deliver a seamless, open-source experience."
            ],
        )
        about.add_link("View Application Logs", f"file://{log_path}")
        about.add_link("Connect on LinkedIn", "https://www.linkedin.com/in/John--Varghese")
        about.add_link("Follow on GitHub", "https://github.com/John-Varghese-EH")
        about.add_credit_section(
            "Protocol Research",
            ["eshare-linux-client (GPL-3.0-or-later)"],
        )
        about.present()

    # Preferences

    def _show_preferences(self, *_args) -> None:
        prefs_win = Adw.PreferencesWindow(
            transient_for=self,
            title="Preferences",
        )

        # General page
        general_page = Adw.PreferencesPage(
            title="General",
            icon_name="preferences-system-symbolic",
        )

        # Polling group
        poll_group = Adw.PreferencesGroup(
            title="Status Polling",
            description="How often to refresh projector status",
        )
        poll_row = Adw.SpinRow.new_with_range(5, 60, 5)
        poll_row.set_title("Polling interval (seconds)")
        poll_row.set_value(self._config.polling_interval)
        poll_row.connect("notify::value", self._on_poll_interval_changed)
        poll_group.add(poll_row)
        general_page.add(poll_group)

        # Auto-connect group
        connect_group = Adw.PreferencesGroup(title="Connection")
        auto_row = Adw.SwitchRow(
            title="Auto-connect on launch",
            subtitle="Connect to the last-used device automatically",
            active=self._config.auto_connect,
        )
        auto_row.connect("notify::active", self._on_auto_connect_changed)
        connect_group.add(auto_row)
        general_page.add(connect_group)

        # Streaming Quality
        stream_group = Adw.PreferencesGroup(title="Screen Casting")
        quality_row = Adw.ComboRow(
            title="Stream Quality", subtitle="Adjust based on network stability"
        )
        quality_model = Gtk.StringList.new(["Low Latency", "Balanced", "High Quality"])
        quality_row.set_model(quality_model)
        quality_map = {"low_latency": 0, "balanced": 1, "high_quality": 2}
        quality_row.set_selected(quality_map.get(self._config.stream_quality, 1))
        quality_row.connect("notify::selected", self._on_stream_quality_changed)
        stream_group.add(quality_row)
        general_page.add(stream_group)

        # Appearance group
        appearance_group = Adw.PreferencesGroup(title="Appearance")
        theme_row = Adw.ComboRow(title="Color scheme")
        theme_model = Gtk.StringList.new(["System", "Light", "Dark"])
        theme_row.set_model(theme_model)
        theme_map = {"system": 0, "light": 1, "dark": 2}
        theme_row.set_selected(theme_map.get(self._config.theme, 0))
        theme_row.connect("notify::selected", self._on_theme_changed)
        appearance_group.add(theme_row)
        general_page.add(appearance_group)

        prefs_win.add(general_page)

        # Advanced Page
        advanced_page = Adw.PreferencesPage(
            title="Advanced", icon_name="preferences-system-symbolic"
        )

        # Network Settings
        network_group = Adw.PreferencesGroup(title="Network Settings")

        timeout_row = Adw.SpinRow(
            title="Connection Timeout (seconds)",
            subtitle="Max time to wait when connecting to a projector",
            adjustment=Gtk.Adjustment(
                value=self._config.connection_timeout, lower=1, upper=60, step_increment=1
            ),
        )
        timeout_row.connect("notify::value", self._on_timeout_changed)
        network_group.add(timeout_row)

        port_row = Adw.SpinRow(
            title="Default Port",
            subtitle="Standard ESC/VP network port",
            adjustment=Gtk.Adjustment(
                value=self._config.default_port, lower=1, upper=65535, step_increment=1
            ),
        )
        port_row.connect("notify::value", self._on_port_changed)
        network_group.add(port_row)

        advanced_page.add(network_group)

        # Security Settings
        security_group = Adw.PreferencesGroup(title="Security")
        pwd_row = Adw.PasswordEntryRow(
            title="PJLink Password", text=self._config.pjlink_password or ""
        )
        pwd_row.connect("notify::text", self._on_pwd_changed)
        security_group.add(pwd_row)
        advanced_page.add(security_group)

        # Diagnostics
        diag_group = Adw.PreferencesGroup(title="Diagnostics")
        debug_row = Adw.SwitchRow(
            title="Enable Debug Logging",
            subtitle="Write verbose payload traces to linux-iprojection.log",
            active=self._config.debug_mode,
        )
        debug_row.connect("notify::active", self._on_debug_changed)
        diag_group.add(debug_row)
        advanced_page.add(diag_group)

        prefs_win.add(advanced_page)
        prefs_win.present()

    def _on_timeout_changed(self, row, _pspec) -> None:
        self._config.connection_timeout = int(row.get_value())
        save_config(self._config)

    def _on_port_changed(self, row, _pspec) -> None:
        self._config.default_port = int(row.get_value())
        save_config(self._config)

    def _on_pwd_changed(self, row, _pspec) -> None:
        self._config.pjlink_password = row.get_text()
        save_config(self._config)

    def _on_debug_changed(self, row, _pspec) -> None:
        self._config.debug_mode = row.get_active()
        save_config(self._config)
        # Apply logging dynamically
        from .config import setup_logging

        setup_logging(verbose=self._config.debug_mode)

    def _on_poll_interval_changed(self, row, _pspec) -> None:
        self._config.polling_interval = int(row.get_value())
        save_config(self._config)
        self._restart_polling()

    def _on_auto_connect_changed(self, row, _pspec) -> None:
        self._config.auto_connect = row.get_active()
        save_config(self._config)

    def _on_theme_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        themes = {0: "system", 1: "light", 2: "dark"}
        self._config.theme = themes.get(idx, "system")
        save_config(self._config)
        self._apply_theme()

    def _on_stream_quality_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        qualities = {0: "low_latency", 1: "balanced", 2: "high_quality"}
        self._config.stream_quality = qualities.get(idx, "balanced")
        save_config(self._config)

    def _apply_theme(self) -> None:
        sm = Adw.StyleManager.get_default()
        scheme_map = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        sm.set_color_scheme(scheme_map.get(self._config.theme, Adw.ColorScheme.DEFAULT))

    # Shortcuts window

    def _show_shortcuts(self, *_args) -> None:
        shortcuts = Gtk.ShortcutsWindow(transient_for=self)
        section = Gtk.ShortcutsSection(visible=True)
        group = Gtk.ShortcutsGroup(title="General", visible=True)
        group.append(
            Gtk.ShortcutsShortcut(
                title="Preferences",
                accelerator="<Control>comma",
                visible=True,
            )
        )
        group.append(
            Gtk.ShortcutsShortcut(
                title="Keyboard Shortcuts",
                accelerator="<Control>question",
                visible=True,
            )
        )
        group.append(
            Gtk.ShortcutsShortcut(
                title="Quit",
                accelerator="<Control>q",
                visible=True,
            )
        )
        section.append(group)
        shortcuts.set_child(section)
        shortcuts.present()

    # Polling

    def _start_polling(self) -> None:
        if self._polling_source_id is not None:
            return
        interval = max(5, self._config.polling_interval)
        self._polling_source_id = GLib.timeout_add_seconds(
            interval,
            self._poll_tick,
        )

    def _stop_polling(self) -> None:
        if self._polling_source_id is not None:
            GLib.source_remove(self._polling_source_id)
            self._polling_source_id = None

    def _restart_polling(self) -> None:
        self._stop_polling()
        self._start_polling()

    def _poll_tick(self) -> bool:
        """Called every polling_interval seconds."""
        if not self.is_active():
            # Window not focused - skip to reduce LAN chatter
            return True
        if self.current_device is not None:
            self._refresh_status()
        return True  # keep timer alive

    # Event handlers

    def on_refresh(self, _button) -> None:
        self.refresh_btn.set_sensitive(False)
        self.sidebar_stack.set_visible_child_name("loading")

        @_run_async(discover_all())
        def done(devices, error):
            self.refresh_btn.set_sensitive(True)
            if error:
                log.error("Scan failed: %s", error)
                self.sidebar_stack.set_visible_child_name("empty")
                self.error_banner.set_title(f"Scan failed: {error}")
                self.error_banner.set_revealed(True)
                return
            self.error_banner.set_revealed(False)
            self._populate_devices(devices or [])

    def _populate_devices(self, devices: list) -> None:
        # Clear existing
        child = self.device_list.get_row_at_index(0)
        while child is not None:
            self.device_list.remove(child)
            child = self.device_list.get_row_at_index(0)

        # Also merge with persisted devices and map aliases
        persisted = self._device_store.load_devices()
        persisted_dict = {pd.get("address"): pd for pd in persisted}

        seen_addrs = {d.address for d in devices}

        # Apply aliases to discovered devices
        for d in devices:
            if d.address in persisted_dict:
                d.alias = persisted_dict[d.address].get("alias")

        # Add persisted ones that aren't discovered
        for pd in persisted:
            if pd.get("address") not in seen_addrs:
                devices.append(
                    DiscoveredDevice(
                        name=pd.get("name", pd.get("address", "?")),
                        address=pd.get("address", "?"),
                        port=pd.get("port", 3629),
                        source="persisted",
                        alias=pd.get("alias"),
                    )
                )

        for d in devices:
            self.device_list.append(DeviceRow(d))

        # Save discovered devices
        self._device_store.save_devices(
            [
                {"name": d.name, "address": d.address, "port": d.port, "alias": d.alias}
                for d in devices
            ]
        )

        if devices:
            self.sidebar_stack.set_visible_child_name("list")
        else:
            self.sidebar_stack.set_visible_child_name("empty")

    def _load_persisted_devices(self) -> None:
        """Load devices from disk on startup."""
        persisted = self._device_store.load_devices()
        for pd in persisted:
            dev = DiscoveredDevice(
                name=pd.get("name", pd.get("address", "?")),
                address=pd.get("address", "?"),
                port=pd.get("port", 3629),
                source="persisted",
                alias=pd.get("alias"),
            )
            self.device_list.append(DeviceRow(dev))
        if persisted:
            self.sidebar_stack.set_visible_child_name("list")

    def on_add_manual(self, _button) -> None:
        dialog = Adw.AlertDialog(
            heading="Add projector",
            body="Enter the projector's IP address",
        )
        entry = Gtk.Entry(placeholder_text="192.168.1.50")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response == "add" and entry.get_text().strip():
                ip = entry.get_text().strip()
                device = DiscoveredDevice(
                    name=ip,
                    address=ip,
                    port=3629,
                    source="manual",
                )
                self.device_list.append(DeviceRow(device))
                self.sidebar_stack.set_visible_child_name("list")

                # Persist
                existing = self._device_store.load_devices()
                existing.append({"name": ip, "address": ip, "port": 3629})
                self._device_store.save_devices(existing)

        dialog.connect("response", on_response)
        dialog.present(self)

    def on_device_selected(self, _listbox, row: DeviceRow) -> None:
        self.current_device = row.device
        self.device_title.set_label(row.device.name or row.device.address)
        self.device_subtitle.set_label(row.device.address)
        self.content_stack.set_visible_child_name("control")
        self.split.set_show_content(True)
        self._refresh_status()

    def _refresh_status(self) -> None:
        if not self.current_device:
            return
        host = self.current_device.address

        async def query():
            async with ProjectorClient(host, self.current_device.device_type) as client:
                return await client.get_status()

        @_run_async(query())
        def done(status, error):
            self._latest_status = status
            if error:
                log.warning("Status query failed: %s", error)
                self.power_row.set_subtitle("Unreachable")
                self._toast(
                    f"Connection failed: {error}", action_name="Retry", action_target="app.refresh"
                )
                return
            if status.power:
                pwr_val = status.power
                if isinstance(pwr_val, bool):
                    pwr_active = pwr_val
                elif "=" in pwr_val:
                    pwr_val = pwr_val.split("=", 1)[1]
                    pwr_active = pwr_val in ("01", "02")
                else:
                    pwr_active = False

                # Disconnect briefly to avoid self-triggering
                self.power_btn.handler_block_by_func(self.on_power_toggled)
                self.power_btn.set_active(pwr_active)
                self.power_btn.handler_unblock_by_func(self.on_power_toggled)

                power_names = {
                    "00": "Off",
                    "01": "On",
                    "02": "Warming up",
                    "03": "Cooling down",
                    "04": "Standby",
                    "05": "Abnormal standby",
                }
                subtitle = (
                    power_names.get(str(pwr_val), str(pwr_val))
                    if not isinstance(pwr_val, bool)
                    else ("On" if pwr_val else "Off")
                )
                self.power_row.set_subtitle(subtitle)

            if status.mute is not None:
                self.mute_btn.handler_block_by_func(self.on_mute_toggled)
                self.mute_btn.set_active(status.mute)
                self.mute_btn.handler_unblock_by_func(self.on_mute_toggled)

            if status.volume is not None:
                self.vol_scale.handler_block_by_func(self.on_volume_changed)
                self.vol_scale.set_value(status.volume)
                self.vol_scale.handler_unblock_by_func(self.on_volume_changed)
            if status.source:
                src_val = status.source
                if "=" in src_val:
                    src_val = src_val.split("=", 1)[1]
                self.source_row.set_subtitle(src_val)
                # Try to select the matching dropdown item
                for i, s in enumerate(Source):
                    if s.value == src_val:
                        self.source_dropdown.set_selected(i)
                        break
            if status.lamp_hours is not None:
                self.lamp_row.set_subtitle(f"{status.lamp_hours} h")

    def _show_device_info(self, _button) -> None:
        if not self.current_device:
            return

        dialog = Adw.AlertDialog(
            heading="Device Information",
            body="Hardware and network details",
        )
        dialog.add_response("close", "Close")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup()
        box.append(group)

        # Basic Info
        group.add(Adw.ActionRow(title="IP Address", subtitle=self.current_device.address))
        group.add(
            Adw.ActionRow(title="Original Name", subtitle=self.current_device.name or "Unknown")
        )

        alias_row = Adw.EntryRow(title="Friendly Alias", text=self.current_device.alias or "")
        alias_row.connect("notify::text", self._on_alias_changed)
        group.add(alias_row)

        group.add(
            Adw.ActionRow(
                title="Device Type",
                subtitle=self.current_device.device_type.replace("_", " ").title(),
            )
        )

        # Status Info
        if hasattr(self, "_latest_status") and self._latest_status:
            status = self._latest_status
            if status.serial:
                group.add(Adw.ActionRow(title="Serial Number", subtitle=status.serial))
            if status.errors:
                group.add(Adw.ActionRow(title="Current Errors", subtitle=status.errors))
            group.add(
                Adw.ActionRow(
                    title="Lamp Hours",
                    subtitle=f"{status.lamp_hours} h" if status.lamp_hours else "Unknown",
                )
            )

        # Actions Group
        action_group = Adw.PreferencesGroup()

        wol_row = Adw.ActionRow(title="Wake-on-LAN", subtitle="Wake projector from deep standby")
        wol_btn = Gtk.Button(label="Wake", valign=Gtk.Align.CENTER)
        wol_btn.connect("clicked", self._on_wol_clicked)
        wol_row.add_suffix(wol_btn)
        wol_row.set_activatable_widget(wol_btn)
        action_group.add(wol_row)

        export_row = Adw.ActionRow(
            title="Export Information", subtitle="Save hardware details to CSV"
        )
        export_btn = Gtk.Button(label="Export", valign=Gtk.Align.CENTER)
        export_btn.connect("clicked", self._on_export_clicked)
        export_row.add_suffix(export_btn)
        export_row.set_activatable_widget(export_btn)
        action_group.add(export_row)

        box.append(action_group)

        dialog.set_extra_child(box)
        dialog.present(self)

    def _on_wol_clicked(self, _button) -> None:
        if not self.current_device:
            return
        self._toast(f"Broadcasting Wake-on-LAN magic packet for {self.current_device.address}...")

        # Run in background
        from .client import wake_on_lan

        def run_wol():
            success = wake_on_lan(self.current_device.address)
            GLib.idle_add(
                lambda: self._toast(
                    "Wake packet sent." if success else "Failed to send wake packet."
                )
            )

        import threading

        threading.Thread(target=run_wol, daemon=True).start()

    def _on_export_clicked(self, _button) -> None:
        if not self.current_device:
            return

        # Build CSV content
        lines = ["Property,Value"]
        lines.append(f"IP Address,{self.current_device.address}")
        lines.append(f"Name,{self.current_device.name or 'Unknown'}")
        if self.current_device.alias:
            lines.append(f"Alias,{self.current_device.alias}")

        if hasattr(self, "_latest_status") and self._latest_status:
            status = self._latest_status
            if status.serial:
                lines.append(f"Serial Number,{status.serial}")
            if status.lamp_hours:
                lines.append(f"Lamp Hours,{status.lamp_hours}")
            if status.errors:
                lines.append(f"Errors,{status.errors}")

        csv_content = "\\n".join(lines)

        from .config import get_state_dir

        export_path = get_state_dir() / f"projector_{self.current_device.address}.csv"

        try:
            with open(export_path, "w") as f:
                f.write(csv_content)
            self._toast(f"Exported to {export_path}")
        except Exception as e:
            self._toast(f"Export failed: {e}")

    def _on_console_send_clicked(self, _button, entry_row) -> None:
        if not self.current_device:
            return
        cmd = entry_row.get_text().strip()
        if not cmd:
            return
        self.console_output.set_label(f"> {cmd}\nSending...")

        @_run_async(self._client.send_raw(cmd))
        def done(result, error):
            if error:
                self.console_output.set_label(f"> {cmd}\nError: {error}")
                self._toast(f"Command failed: {error}")
            else:
                self.console_output.set_label(f"> {cmd}\n< {result}")
                self._toast("Command sent.")

    def _on_alias_changed(self, entry, _pspec) -> None:
        if not self.current_device:
            return
        new_alias = entry.get_text().strip()
        self.current_device.alias = new_alias if new_alias else None

        # Save to store
        persisted = self._device_store.load_devices()
        for p in persisted:
            if p.get("address") == self.current_device.address:
                p["alias"] = self.current_device.alias
        self._device_store.save_devices(persisted)

        # Update row in UI
        for child in self.device_list:
            if isinstance(child, DeviceRow) and child.device.address == self.current_device.address:
                child.update_from(self.current_device)
                break

        # Update title in control panel
        title = (
            self.current_device.alias
            if self.current_device.alias
            else (self.current_device.name or self.current_device.address)
        )
        self.device_title.set_label(title)

    def on_power_toggled(self, button: Gtk.ToggleButton) -> None:
        if not self.current_device:
            return
        state = button.get_active()
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                if state:
                    await client.power_on()
                else:
                    await client.power_off()

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Power command failed: {error}")
            else:
                self._toast(f"Power {'on' if state else 'off'}")
                GLib.timeout_add_seconds(2, lambda: (self._refresh_status(), False)[1])

    def on_mute_toggled(self, button: Gtk.ToggleButton) -> None:
        if not self.current_device:
            return
        state = button.get_active()
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_mute(state)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Mute command failed: {error}")

    def on_freeze_toggled(self, button: Gtk.ToggleButton) -> None:
        if not self.current_device:
            return
        state = button.get_active()
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_freeze(state)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Freeze command failed: {error}")

    def on_remote_key(self, key_code: str) -> None:
        if not self.current_device:
            return
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.send_key(key_code)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Key command failed: {error}")

    def _do_set_volume(self, value: float) -> None:
        if not self.current_device:
            return
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_volume(int(value))

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Volume command failed: {error}")

    def on_volume_changed(self, scale: Gtk.Scale) -> None:
        self._do_set_volume(scale.get_value())

    def on_volume_scroll(self, scale, scroll, value) -> bool:
        # For smooth scrolls (if connected to change-value), we can debounce this
        # or just let it update. We will rely on value-changed for simplicity.
        return False

    def on_source_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if not self.current_device:
            return
        source = list(Source)[dropdown.get_selected()]
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_source(source)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Source switch failed: {error}")
            else:
                self._toast(f"Switched to {source.name.replace('_', ' ').title()}")

        return None

    def on_color_mode_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if not self.current_device:
            return
        from .protocol import ColorMode

        mode = list(ColorMode)[dropdown.get_selected()]
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_color_mode(mode)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Color mode switch failed: {error}")
            else:
                self._toast(f"Switched to {mode.name.replace('_', ' ').title()}")

    def on_aspect_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if not self.current_device:
            return
        from .protocol import AspectRatio

        aspect = list(AspectRatio)[dropdown.get_selected()]
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_aspect_ratio(aspect)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Aspect ratio switch failed: {error}")
            else:
                self._toast(f"Switched to {aspect.name.replace('_', ' ').title()}")

    def on_luminance_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if not self.current_device:
            return
        from .protocol import LuminanceMode

        lum = list(LuminanceMode)[dropdown.get_selected()]
        host = self.current_device.address
        device_type = self.current_device.device_type

        async def cmd():
            async with ProjectorClient(host, device_type) as client:
                await client.set_luminance(lum)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Luminance switch failed: {error}")
            else:
                self._toast(f"Switched to {lum.name.replace('_', ' ').title()}")

    # Casting

    def on_cast_clicked(self, _button) -> None:
        if not self.current_device:
            self._toast("Select a projector first")
            return

        self.cast_btn.set_sensitive(False)
        self.cast_btn.set_label("Starting…")

        device = self.current_device
        audio_enabled = self.audio_switch.get_active()

        def start_cast():
            try:
                from .cast import CastTarget, RtpUdpSink, ScreenCaster

                target = CastTarget(
                    host=device.address,
                    port=getattr(device, "stream_port", 5004),
                    audio_port=getattr(device, "audio_port", 5006),
                    name=device.name or device.address,
                )

                sink = RtpUdpSink()
                self._caster = ScreenCaster(
                    sink=sink,
                    audio_enabled=audio_enabled,
                    stream_quality=self._config.stream_quality,
                    on_stats=self._on_cast_stats,
                    on_error=self._on_cast_error,
                )
                # Run the async portal request
                asyncio.run(self._caster.start(target))
                GLib.idle_add(self._on_cast_started, device.name or device.address)
            except Exception as e:
                log.error("Cast failed: %s", e)
                GLib.idle_add(self._on_cast_failed, str(e))

        threading.Thread(target=start_cast, daemon=True).start()

    def _on_cast_started(self, device_name: str) -> None:
        self._is_casting = True
        self.casting_title.set_label(f"Casting to {device_name}")
        self.casting_status.set_label("Streaming…")
        self.content_stack.set_visible_child_name("casting")
        self._toast(f"Casting to {device_name}")

    def _on_cast_failed(self, error_msg: str) -> None:
        self.cast_btn.set_sensitive(True)
        self.cast_btn.set_label("Start Casting")
        if "cancel" in error_msg.lower() or "dismissed" in error_msg.lower():
            self._toast("Screen sharing cancelled")
        else:
            self._toast(f"Casting failed: {error_msg}")

    def _on_cast_stats(self, stats) -> None:
        """Called from GStreamer thread - marshal to UI."""
        GLib.idle_add(self._update_cast_stats, stats)

    def _update_cast_stats(self, stats) -> None:
        if hasattr(stats, "bitrate_kbps"):
            br = stats.bitrate_kbps
            if br > 1000:
                self.stats_bitrate_row.set_subtitle(f"{br / 1000:.1f} Mbps")
            else:
                self.stats_bitrate_row.set_subtitle(f"{br:.0f} kbps")
        audio_str = "Audio: Active" if getattr(stats, "audio_active", False) else "Audio: Off"
        self.stats_fps_row.set_subtitle(audio_str)

    def _on_cast_error(self, error_msg: str) -> None:
        """Called from GStreamer thread."""
        GLib.idle_add(self._handle_cast_error, error_msg)

    def _handle_cast_error(self, error_msg: str) -> None:
        self._is_casting = False
        self.content_stack.set_visible_child_name("control")
        self.cast_btn.set_sensitive(True)
        self.cast_btn.set_label("Start Casting")
        self._toast(f"Stream ended: {error_msg}")

    def on_stop_cast_clicked(self, _button) -> None:
        if self._caster:
            self._caster.stop()
            self._caster = None
        self._is_casting = False
        self.content_stack.set_visible_child_name("control")
        self.cast_btn.set_sensitive(True)
        self.cast_btn.set_label("Start Casting")
        self._toast("Casting stopped")

    # Toast helper

    def _toast(self, message: str, action_name: str = None, action_target: str = None) -> None:
        toast = Adw.Toast(title=message, timeout=4)
        if action_name and action_target:
            toast.set_button_label(action_name)
            toast.set_action_name(action_target)
        self.toast_overlay.add_toast(toast)


# Application


class EpsonCtlApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        # Load compiled GResource for icons (bulletproof GTK4 approach)
        import os

        from gi.repository import Gdk, Gio

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Check local source tree first, then fallback to system installation path
        gresource_paths = [
            os.path.join(base_dir, "data", "linux_iprojection.gresource"),
            "/usr/share/linux-iprojection/linux_iprojection.gresource",
            os.path.join(sys.prefix, "share", "linux-iprojection", "linux_iprojection.gresource"),
        ]

        for path in gresource_paths:
            if os.path.isfile(path):
                try:
                    resource = Gio.Resource.load(path)
                    resource._register()
                    # Explicitly tell GTK to look for icons in our resource
                    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
                    theme.add_resource_path("/dev/linux-iprojection/EpsonCtl/icons")
                    # Also set the default window icon so all windows get it automatically
                    Gtk.Window.set_default_icon_name("dev.linux_iprojection.LinuxIProjection")
                    break
                except Exception as e:
                    print(f"Warning: Failed to load resource {path}: {e}")

        # Theme follows system by default
        config = load_config()
        sm = Adw.StyleManager.get_default()
        scheme_map = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        sm.set_color_scheme(scheme_map.get(config.theme, Adw.ColorScheme.DEFAULT))


# Entry point


def main() -> int:
    """Application entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Epson projector control & casting")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    app = EpsonCtlApp()
    return app.run(sys.argv[:1])  # Don't pass our args to GTK


if __name__ == "__main__":
    raise SystemExit(main())
