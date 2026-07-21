"""
epsonctl — main application.

GTK4 + libadwaita, run under an asyncio-friendly GLib main loop via
`gbulb` -- avoided here to keep the dependency list small: instead we run
async control/discovery calls with `asyncio.run()` inside GLib idle
callbacks, which is the common lightweight pattern for small PyGObject
apps that only need occasional async network I/O (not a full async UI).
"""

from __future__ import annotations

import asyncio
import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, Gio  # noqa: E402

from .discovery import discover_all, DiscoveredDevice
from .protocol import EscVpNetClient, Source, ProjectorError

log = logging.getLogger(__name__)
APP_ID = "dev.epsonctl.EpsonCtl"


def _run_async(coro):
    """Run an async coroutine on a background thread so the GTK main
    loop never blocks on network I/O, then marshal the result back to
    the UI thread via GLib.idle_add.
    """

    def worker():
        try:
            result = asyncio.run(coro)
            error = None
        except Exception as e:  # noqa: BLE001 — surfaced to the UI
            result, error = None, e
        return result, error

    def runner(callback):
        result, error = worker()
        GLib.idle_add(callback, result, error)

    def decorator(callback):
        threading.Thread(target=runner, args=(callback,), daemon=True).start()

    return decorator


class DeviceRow(Adw.ActionRow):
    def __init__(self, device: DiscoveredDevice):
        super().__init__(title=device.name or device.address, subtitle=device.address)
        self.device = device
        icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        self.add_prefix(icon)
        self.set_activatable(True)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Epson Control", default_width=760, default_height=560)

        self.current_device: DiscoveredDevice | None = None

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Scan for projectors")
        self.refresh_btn.connect("clicked", self.on_refresh)
        header.pack_start(self.refresh_btn)

        self.add_manual_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add projector by IP")
        self.add_manual_btn.connect("clicked", self.on_add_manual)
        header.pack_end(self.add_manual_btn)

        split = Adw.NavigationSplitView()

        # --- sidebar: device list -------------------------------------
        sidebar_page = Adw.NavigationPage(title="Projectors")
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar(show_start_title_buttons=False)
        sidebar_toolbar.add_top_bar(sidebar_header)

        self.device_list = Gtk.ListBox(css_classes=["boxed-list"], margin_start=12, margin_end=12, margin_top=12)
        self.device_list.connect("row-activated", self.on_device_selected)
        self.status_page = Adw.StatusPage(
            title="No projectors found",
            description="Scan the network or add one by IP address",
            icon_name="network-wireless-symbolic",
        )

        sidebar_scroller = Gtk.ScrolledWindow(child=self.device_list, vexpand=True)
        sidebar_toolbar.set_content(sidebar_scroller)
        sidebar_page.set_child(sidebar_toolbar)
        split.set_sidebar(sidebar_page)

        # --- content: control panel -------------------------------------
        content_page = Adw.NavigationPage(title="Control")
        content_toolbar = Adw.ToolbarView()
        content_header = Adw.HeaderBar()
        content_toolbar.add_top_bar(content_header)

        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.add_named(self._build_empty_state(), "empty")
        self.content_stack.add_named(self._build_control_panel(), "control")
        content_toolbar.set_content(self.content_stack)
        content_page.set_child(content_toolbar)
        split.set_content(content_page)

        toolbar_view.set_content(split)
        self.set_content(toolbar_view)

        self.toast_overlay = Adw.ToastOverlay(child=self.get_content())
        self.set_content(self.toast_overlay)

        self.on_refresh(None)

    # ------------------------------------------------------------------
    def _build_empty_state(self) -> Gtk.Widget:
        return Adw.StatusPage(
            title="Select a projector",
            description="Choose a device from the list to view controls",
            icon_name="video-display-symbolic",
        )

    def _build_control_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)

        self.device_title = Gtk.Label(css_classes=["title-1"], xalign=0)
        box.append(self.device_title)

        power_group = Adw.PreferencesGroup(title="Power")
        power_row = Adw.ActionRow(title="Projector power")
        self.power_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.power_switch.connect("state-set", self.on_power_toggled)
        power_row.add_suffix(self.power_switch)
        power_row.set_activatable_widget(self.power_switch)
        power_group.add(power_row)
        box.append(power_group)

        source_group = Adw.PreferencesGroup(title="Input source")
        source_row = Adw.ActionRow(title="Active source")
        self.source_dropdown = Gtk.DropDown.new_from_strings(
            [s.name.replace("_", " ").title() for s in Source]
        )
        self.source_dropdown.connect("notify::selected", self.on_source_changed)
        source_row.add_suffix(self.source_dropdown)
        source_group.add(source_row)
        box.append(source_group)

        mute_group = Adw.PreferencesGroup(title="Video")
        mute_row = Adw.ActionRow(title="A/V mute (blank screen)")
        self.mute_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.mute_switch.connect("state-set", self.on_mute_toggled)
        mute_row.add_suffix(self.mute_switch)
        mute_row.set_activatable_widget(self.mute_switch)
        mute_group.add(mute_row)
        box.append(mute_group)

        status_group = Adw.PreferencesGroup(title="Status")
        self.lamp_row = Adw.ActionRow(title="Lamp hours", subtitle="—")
        status_group.add(self.lamp_row)
        box.append(status_group)

        cast_group = Adw.PreferencesGroup(title="Cast")
        cast_row = Adw.ActionRow(
            title="Mirror this screen",
            subtitle="Requires the casting pipeline (see cast.py — delivery protocol pending)",
        )
        cast_btn = Gtk.Button(label="Start casting", css_classes=["suggested-action"], valign=Gtk.Align.CENTER)
        cast_btn.connect("clicked", self.on_cast_clicked)
        cast_row.add_suffix(cast_btn)
        cast_group.add(cast_row)
        box.append(cast_group)

        scroller = Gtk.ScrolledWindow(child=box)
        return scroller

    # --- event handlers ------------------------------------------------
    def on_refresh(self, _button) -> None:
        self.refresh_btn.set_sensitive(False)

        @_run_async(discover_all())
        def done(devices, error):
            self.refresh_btn.set_sensitive(True)
            if error:
                self._toast(f"Scan failed: {error}")
                return
            self._populate_devices(devices or [])

    def _populate_devices(self, devices) -> None:
        child = self.device_list.get_row_at_index(0)
        while child is not None:
            self.device_list.remove(child)
            child = self.device_list.get_row_at_index(0)
        for d in devices:
            self.device_list.append(DeviceRow(d))
        if not devices:
            self._toast("No projectors found on the local network")

    def on_add_manual(self, _button) -> None:
        dialog = Adw.AlertDialog(heading="Add projector", body="Enter the projector's IP address")
        entry = Gtk.Entry(placeholder_text="192.168.1.50")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response == "add" and entry.get_text().strip():
                device = DiscoveredDevice(name=entry.get_text().strip(), address=entry.get_text().strip(), port=3629, source="manual")
                self.device_list.append(DeviceRow(device))

        dialog.connect("response", on_response)
        dialog.present(self)

    def on_device_selected(self, _listbox, row: DeviceRow) -> None:
        self.current_device = row.device
        self.device_title.set_label(row.device.name or row.device.address)
        self.content_stack.set_visible_child_name("control")
        self._refresh_status()

    def _refresh_status(self) -> None:
        if not self.current_device:
            return
        host = self.current_device.address

        async def query():
            async with EscVpNetClient(host) as client:
                return await client.get_status()

        @_run_async(query())
        def done(status, error):
            if error:
                self._toast(f"Couldn't reach projector: {error}")
                return
            if status.power:
                self.power_switch.set_state(status.power == "01")
            if status.lamp_hours is not None:
                self.lamp_row.set_subtitle(f"{status.lamp_hours} h")

    def on_power_toggled(self, switch: Gtk.Switch, state: bool) -> bool:
        if not self.current_device:
            return False
        host = self.current_device.address

        async def cmd():
            async with EscVpNetClient(host) as client:
                if state:
                    await client.power_on()
                else:
                    await client.power_off()

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Power command failed: {error}")

        return False  # let the switch update its own visual state

    def on_mute_toggled(self, switch: Gtk.Switch, state: bool) -> bool:
        if not self.current_device:
            return False
        host = self.current_device.address

        async def cmd():
            async with EscVpNetClient(host) as client:
                await client.set_mute(state)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Mute command failed: {error}")

        return False

    def on_source_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if not self.current_device:
            return
        source = list(Source)[dropdown.get_selected()]
        host = self.current_device.address

        async def cmd():
            async with EscVpNetClient(host) as client:
                await client.set_source(source)

        @_run_async(cmd())
        def done(_result, error):
            if error:
                self._toast(f"Source switch failed: {error}")

        return None

    def on_cast_clicked(self, _button) -> None:
        self._toast("Casting pipeline needs the confirmed EShare delivery protocol — see cast.py")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=4))


class EpsonCtlApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        win = self.props.active_window or MainWindow(self)
        win.present()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    app = EpsonCtlApp()
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
