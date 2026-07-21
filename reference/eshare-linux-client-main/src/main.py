"""
main.py — Application Entry Point
===================================

Creates the Gtk.Application, registers actions, and launches AppWindow.

Usage
-----
    python -m src.main           # run directly
    linux-iprojection            # after pip install -e .
"""

from __future__ import annotations

import logging
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gio, Gtk  # type: ignore

from src.app_window import AppWindow

log = logging.getLogger(__name__)

APP_ID      = "com.linux.iprojection"
APP_VERSION = "0.1.0"


class Application(Adw.Application):
    """
    Top-level Adw.Application subclass.

    Responsible for:
    - Registering GLib actions (about, shortcuts, quit)
    - Applying the app stylesheet
    - Creating and showing AppWindow on activate
    """

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self._window: AppWindow | None = None

        # Connect lifecycle signals
        self.connect("activate", self._on_activate)
        self.connect("startup",  self._on_startup)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _on_startup(self, _app) -> None:
        """Register actions and load the CSS stylesheet."""
        self._register_actions()
        self._load_stylesheet()

    def _on_activate(self, _app) -> None:
        """Create (or raise) the main window."""
        if self._window is None:
            self._window = AppWindow(application=self)
            self._window.present()
            # Kick off auto-discovery after UI is shown
            GLib.idle_add(self._window.start_discovery)
        else:
            self._window.present()

    # ── Actions ───────────────────────────────────────────────────────────

    def _register_actions(self) -> None:
        # Quit
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])

        # About dialog
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        # Shortcuts window (placeholder)
        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts_action)

    # ── Dialogs ───────────────────────────────────────────────────────────

    def _on_about(self, _action, _param) -> None:
        dialog = Adw.AboutWindow(
            transient_for=self._window,
            application_name="linux-iprojection",
            application_icon="video-display-symbolic",
            developer_name="linux-iprojection contributors",
            version=APP_VERSION,
            website="https://github.com/example/linux-iprojection",
            issue_url="https://github.com/example/linux-iprojection/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=(
                "Wireless desktop projection to Epson projectors and "
                "EShare-enabled displays from Linux, using GStreamer and GTK4."
            ),
        )
        dialog.present()

    def _on_shortcuts(self, _action, _param) -> None:
        # TODO: full ShortcutsWindow in Phase 7
        pass

    # ── Stylesheet ────────────────────────────────────────────────────────

    def _load_stylesheet(self) -> None:
        css = b"""
        /* ── Global tweaks ────────────────────────────────────────────── */
        .status-dot {
            border-radius: 50%;
            min-width:  10px;
            min-height: 10px;
        }
        .dot-streaming { background-color: #2ec27e; }
        .dot-connected { background-color: #e5a50a; }
        .dot-idle      { background-color: #9a9996; }
        .dot-error     { background-color: #e01b24; }

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
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            # GTK4: use Gdk.Display.get_default()
            __import__("gi.repository.Gdk", fromlist=["Gdk"]).Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
