import platform
import sys
import traceback
import urllib.parse
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

GITHUB_ISSUES_URL = "https://github.com/John-Varghese-EH/Linux-iProjection/issues/new"

def get_system_info() -> str:
    info = []
    info.append(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
    info.append(f"Python: {platform.python_version()}")
    
    try:
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init(None)
        info.append(f"GStreamer: {Gst.version_string()}")
    except Exception:
        info.append("GStreamer: Unknown/Unavailable")
        
    try:
        info.append(f"PyGObject: {gi.__version__}")
    except Exception:
        pass
        
    try:
        # Try to get distribution name if on Linux
        import distro
        info.append(f"Distro: {distro.name()} {distro.version()}")
    except ImportError:
        pass
        
    return "\n".join(info)

def generate_crash_report(exc_type, exc_value, exc_traceback) -> str:
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys_info = get_system_info()
    
    report = (
        "### Describe the bug\n\n"
        "A clear and concise description of what the bug is.\n\n"
        "### Crash Report\n"
        "```text\n"
        f"Time: {datetime.now().isoformat()}\n"
        f"{sys_info}\n\n"
        f"{tb_str}\n"
        "```\n"
    )
    return report

def _get_window():
    app = Gio.Application.get_default()
    if app and hasattr(app, "get_active_window"):
        return app.get_active_window()
    return None

def show_crash_dialog(exc_type, exc_value, exc_traceback):
    from gi.repository import Gio
    
    report_md = generate_crash_report(exc_type, exc_value, exc_traceback)
    
    title = f"Crash Detected: {exc_type.__name__}"
    body = (
        "An unexpected error has occurred.\n\n"
        "Please help improve Linux-iProjection by reporting this issue on GitHub. "
        "A crash report has been generated with all the necessary details."
    )
    
    app = Gio.Application.get_default()
    window = app.get_active_window() if app else None

    # Handle both old and new Adwaita dialog APIs
    if hasattr(Adw, "AlertDialog"):
        dialog = Adw.AlertDialog.new(heading=title, body=body)
        dialog.add_response("close", "Close")
        dialog.add_response("copy", "Copy Report")
        dialog.add_response("report", "Report on GitHub")
        dialog.set_response_appearance("report", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dlg, response, *args):
            if response == "copy":
                if window:
                    cb = window.get_clipboard()
                    cb.set(report_md)
            elif response == "report":
                encoded_body = urllib.parse.quote(report_md)
                encoded_title = urllib.parse.quote(f"Crash: {exc_type.__name__} - {str(exc_value)}")
                url = f"{GITHUB_ISSUES_URL}?title={encoded_title}&body={encoded_body}&labels=bug,crash"
                Gio.AppInfo.launch_default_for_uri(url, None)
            
            # Since this is a fatal crash, we should probably exit
            sys.exit(1)

        dialog.choose(window, None, on_response)
    else:
        dialog = Adw.MessageDialog(
            heading=title,
            body=body,
            transient_for=window,
        )
        dialog.add_response("close", "Close")
        dialog.add_response("copy", "Copy Report")
        dialog.add_response("report", "Report on GitHub")
        dialog.set_response_appearance("report", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dlg, response):
            if response == "copy":
                if window:
                    cb = window.get_clipboard()
                    cb.set(report_md)
            elif response == "report":
                encoded_body = urllib.parse.quote(report_md)
                encoded_title = urllib.parse.quote(f"Crash: {exc_type.__name__} - {str(exc_value)}")
                url = f"{GITHUB_ISSUES_URL}?title={encoded_title}&body={encoded_body}&labels=bug,crash"
                Gio.AppInfo.launch_default_for_uri(url, None)
                
            dlg.close()
            sys.exit(1)

        dialog.connect("response", on_response)
        dialog.present()

def setup_crash_handler():
    def custom_excepthook(exc_type, exc_value, exc_traceback):
        # Always print to stderr first
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        # Schedule the dialog on the GLib main loop to avoid threading issues
        GLib.idle_add(show_crash_dialog, exc_type, exc_value, exc_traceback)
        
    sys.excepthook = custom_excepthook
