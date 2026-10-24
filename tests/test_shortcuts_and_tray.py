"""Tests for ShortcutsWindow and Tray subprocess error handling."""

import subprocess
import sys


def test_shortcuts_window_close_does_not_segfault():
    """Verify that Gtk.ShortcutsWindow with add_section closes without assertion errors."""
    import gi
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    import pytest
    from gi.repository import Gdk, Gtk

    # Skip if running in a headless environment without an active display server
    if Gdk.Display.get_default() is None:
        pytest.skip("No display server available (headless environment)")

    try:
        shortcuts = Gtk.ShortcutsWindow()
    except RuntimeError as e:
        if "Gtk couldn't be initialized" in str(e):
            pytest.skip("Gtk could not be initialized (headless environment)")
        raise
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
    # Using add_section preserves the internal widget tree of ShortcutsWindow
    shortcuts.add_section(section)
    shortcuts.present()

    # Emitting close-request (what happens when Escape or close is triggered)
    res = shortcuts.emit("close-request")
    assert res is False
    shortcuts.destroy()


def test_tray_subprocess_eof_handling():
    """Verify that tray.py handles stdin EOF and broken pipe gracefully in a separate subprocess."""
    code = """
import sys
import unittest.mock as mock

# Mock pystray before tray is imported
sys.modules['pystray'] = mock.MagicMock()
from linux_iprojection import tray

mock_icon = mock.MagicMock()
tray.icon_ref = mock_icon

# 1. Test BrokenPipeError in on_click
mock_item = mock.MagicMock()
mock_item.text = 'Quit'
with mock.patch('builtins.print', side_effect=BrokenPipeError):
    tray.on_click(mock_icon, mock_item)
    assert mock_icon.stop.call_count == 1

# 2. Test normal Quit in on_click
mock_icon.reset_mock()
with mock.patch('builtins.print'):
    tray.on_click(mock_icon, mock_item)
    assert mock_icon.stop.call_count == 1

# 3. Test EOF in stdin_listener
mock_icon.reset_mock()
import io
with mock.patch('sys.stdin', io.StringIO('')):
    tray.stdin_listener()
    assert mock_icon.stop.call_count == 1

print('ALL_TRAY_TESTS_PASSED')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ALL_TRAY_TESTS_PASSED" in result.stdout
