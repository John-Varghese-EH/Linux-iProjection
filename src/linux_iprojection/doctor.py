"""
linux-iprojection: Comprehensive System Diagnostics & Environment Doctor.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

Analyzes the host Linux system to ensure 100% compatibility across all
distributions (Debian, Ubuntu, Mint, Fedora, Arch, openSUSE, etc.) and
display servers (Wayland, X11). Verifies GStreamer codecs, portal backends,
audio pipelines, and firewall configurations.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class CheckItem:
    category: str
    name: str
    status: str  # "ok", "warning", "error"
    message: str
    details: str = ""
    remedy: str = ""


@dataclass
class DoctorReport:
    os_name: str
    distro: str
    desktop_session: str
    display_server: str
    checks: list[CheckItem] = field(default_factory=list)
    distro_id: str = "generic"

    @property
    def distro_name(self) -> str:
        return self.distro

    @property
    def has_errors(self) -> bool:
        return any(c.status == "error" for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.status == "warning" for c in self.checks)

    @property
    def overall_status(self) -> str:
        if self.has_errors:
            return "error"
        if self.has_warnings:
            return "warning"
        return "ok"

    @property
    def issues(self) -> list[CheckItem]:
        return [
            c
            for c in self.checks
            if c.status in ("error", "warning") and c.category != "Package Resolution"
        ]

    @property
    def fix_command(self) -> str:
        for c in self.checks:
            if c.remedy and c.category == "Package Resolution":
                return c.remedy
        return ""


def detect_distro() -> tuple[str, str]:
    """Detect distribution ID and readable name."""
    distro_id = "generic"
    distro_name = platform.system()

    try:
        import distro

        distro_id = distro.id().lower()
        distro_name = f"{distro.name()} {distro.version()}".strip()
        return distro_id, distro_name
    except ImportError:
        pass

    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                data = {}
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        data[k] = v.strip('"\'')
                distro_id = data.get("ID", "generic").lower()
                distro_name = data.get("PRETTY_NAME", data.get("NAME", "Linux"))
        except Exception:
            pass

    return distro_id, distro_name


def get_distro_install_command(missing_features: set[str], distro_id: str) -> str:
    """Generate distro-specific package installation commands for missing features."""
    if not missing_features:
        return ""

    is_debian_like = distro_id in ("ubuntu", "debian", "linuxmint", "pop", "elementary", "zorin")
    is_fedora_like = distro_id in ("fedora", "rhel", "centos", "rocky", "alma")
    is_arch_like = distro_id in ("arch", "manjaro", "endeavouros", "artix")
    is_suse_like = distro_id in ("opensuse", "opensuse-tumbleweed", "opensuse-leap", "sles")

    pkg_map = {
        "ximagesrc": {
            "deb": "gstreamer1.0-plugins-good",
            "rpm": "gstreamer1-plugins-good",
            "arch": "gst-plugins-good",
            "suse": "gstreamer-plugins-good",
        },
        "pipewiresrc": {
            "deb": "gstreamer1.0-pipewire",
            "rpm": "gstreamer1-pipewire",
            "arch": "gst-plugin-pipewire",
            "suse": "gstreamer-plugin-pipewire",
        },
        "x264enc": {
            "deb": "gstreamer1.0-plugins-ugly",
            "rpm": "gstreamer1-plugins-ugly-free",
            "arch": "gst-plugins-ugly",
            "suse": "gstreamer-plugins-ugly",
        },
        "openh264enc": {
            "deb": "gstreamer1.0-plugins-bad",
            "rpm": "gstreamer1-plugins-bad-free",
            "arch": "gst-plugins-bad",
            "suse": "gstreamer-plugins-bad",
        },
        "vaapih264enc": {
            "deb": "gstreamer1.0-vaapi",
            "rpm": "gstreamer1-vaapi",
            "arch": "gst-vaapi",
            "suse": "gstreamer-plugins-vaapi",
        },
        "pulsesrc": {
            "deb": "gstreamer1.0-pulseaudio",
            "rpm": "gstreamer1-plugins-good",
            "arch": "gst-plugins-good",
            "suse": "gstreamer-plugins-good",
        },
        "opusenc": {
            "deb": "gstreamer1.0-plugins-base",
            "rpm": "gstreamer1-plugins-base",
            "arch": "gst-plugins-base",
            "suse": "gstreamer-plugins-base",
        },
        "rtph264pay": {
            "deb": "gstreamer1.0-plugins-good",
            "rpm": "gstreamer1-plugins-good",
            "arch": "gst-plugins-good",
            "suse": "gstreamer-plugins-good",
        },
        "portal": {
            "deb": "xdg-desktop-portal",
            "rpm": "xdg-desktop-portal",
            "arch": "xdg-desktop-portal",
            "suse": "xdg-desktop-portal",
        },
    }

    target_pkgs = set()
    for feat in missing_features:
        if feat in pkg_map:
            if is_debian_like:
                target_pkgs.add(pkg_map[feat]["deb"])
            elif is_fedora_like:
                target_pkgs.add(pkg_map[feat]["rpm"])
            elif is_arch_like:
                target_pkgs.add(pkg_map[feat]["arch"])
            elif is_suse_like:
                target_pkgs.add(pkg_map[feat]["suse"])
            else:
                target_pkgs.add(pkg_map[feat]["deb"])

    pkgs_str = " ".join(sorted(target_pkgs))
    if is_debian_like:
        return f"sudo apt update && sudo apt install -y {pkgs_str}"
    elif is_fedora_like:
        return f"sudo dnf install -y {pkgs_str}"
    elif is_arch_like:
        return f"sudo pacman -S --needed {pkgs_str}"
    elif is_suse_like:
        return f"sudo zypper install -y {pkgs_str}"
    return f"Install packages: {pkgs_str}"


def run_diagnostics() -> DoctorReport:
    """Run full system diagnostics and return a comprehensive report."""
    distro_id, distro_name = detect_distro()
    desktop_session = os.environ.get("XDG_CURRENT_DESKTOP", "Unknown")
    is_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    display_server = "Wayland" if is_wayland else ("X11" if os.environ.get("DISPLAY") else "Headless/Unknown")

    report = DoctorReport(
        os_name=platform.system(),
        distro=distro_name,
        desktop_session=desktop_session,
        display_server=display_server,
        distro_id=distro_id,
    )

    missing_features = set()

    # ── 1. Display & ScreenCast Portal Check ─────────────────────────────
    portal_ok = False
    portal_err_msg = ""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.ScreenCast",
            None,
        )
        if proxy.get_name_owner():
            portal_ok = True
        else:
            portal_err_msg = "ScreenCast portal service not actively owned on D-Bus"
    except Exception as e:
        portal_err_msg = str(e)

    if is_wayland:
        if portal_ok:
            report.checks.append(CheckItem(
                category="Display Server",
                name="Wayland ScreenCast Portal",
                status="ok",
                message="Wayland ScreenCast portal is active and responsive.",
            ))
        else:
            missing_features.add("portal")
            report.checks.append(CheckItem(
                category="Display Server",
                name="Wayland ScreenCast Portal",
                status="warning",
                message="ScreenCast portal is not responding.",
                details=portal_err_msg,
                remedy="Install a portal backend for your desktop (e.g. xdg-desktop-portal-gnome, xdg-desktop-portal-kde, or xdg-desktop-portal-wlr).",
            ))
    else:
        # X11 session
        report.checks.append(CheckItem(
            category="Display Server",
            name="X11 Native Capture Support",
            status="ok",
            message=f"X11 display active ({os.environ.get('DISPLAY', ':0')}). Direct capture enabled via ximagesrc.",
        ))

    # ── 2. GStreamer Core & Plugins Check ────────────────────────────────
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)

        version_str = Gst.version_string()
        report.checks.append(CheckItem(
            category="GStreamer",
            name="GStreamer Framework",
            status="ok",
            message=f"{version_str} initialized successfully.",
        ))

        registry = Gst.Registry.get()

        # Video capture elements
        has_ximage = registry.lookup_feature("ximagesrc") is not None
        has_pipewire = registry.lookup_feature("pipewiresrc") is not None

        if has_ximage:
            report.checks.append(CheckItem(
                category="GStreamer",
                name="X11 Video Source (ximagesrc)",
                status="ok",
                message="ximagesrc plugin available for X11 screen capture.",
            ))
        else:
            missing_features.add("ximagesrc")
            report.checks.append(CheckItem(
                category="GStreamer",
                name="X11 Video Source (ximagesrc)",
                status="warning" if is_wayland else "error",
                message="ximagesrc plugin missing.",
                remedy="Required for screen capture on X11 and Linux Mint.",
            ))

        if has_pipewire:
            report.checks.append(CheckItem(
                category="GStreamer",
                name="Wayland Video Source (pipewiresrc)",
                status="ok",
                message="pipewiresrc plugin available for Wayland screen capture.",
            ))
        else:
            missing_features.add("pipewiresrc")
            report.checks.append(CheckItem(
                category="GStreamer",
                name="Wayland Video Source (pipewiresrc)",
                status="error" if is_wayland else "warning",
                message="pipewiresrc plugin missing.",
                remedy="Required for screen capture on Wayland.",
            ))

        # Encoders
        hw_encoders = []
        for enc in ("vaapih264enc", "vah264enc", "nvh264enc", "nvautogpuh264enc"):
            if registry.lookup_feature(enc):
                hw_encoders.append(enc)

        if hw_encoders:
            report.checks.append(CheckItem(
                category="Hardware Acceleration",
                name="H.264 Hardware Encoder",
                status="ok",
                message=f"Hardware encoder detected: {', '.join(hw_encoders)}",
                details="Zero-latency GPU encoding enabled.",
            ))
        else:
            report.checks.append(CheckItem(
                category="Hardware Acceleration",
                name="H.264 Hardware Encoder",
                status="warning",
                message="No GPU hardware encoder found (VA-API / NVENC).",
                details="Will use CPU software encoder (x264enc).",
            ))

        has_x264 = registry.lookup_feature("x264enc") is not None
        has_openh264 = registry.lookup_feature("openh264enc") is not None

        if has_x264 or has_openh264:
            sw_name = "x264enc" if has_x264 else "openh264enc"
            report.checks.append(CheckItem(
                category="GStreamer",
                name="H.264 Software Fallback Encoder",
                status="ok",
                message=f"Software encoder available ({sw_name}).",
            ))
        else:
            missing_features.add("x264enc")
            report.checks.append(CheckItem(
                category="GStreamer",
                name="H.264 Software Fallback Encoder",
                status="error",
                message="No H.264 software encoder found (x264enc / openh264enc missing).",
                remedy="Install GStreamer plugins-ugly for H.264 streaming.",
            ))

        # Video RTP payloader
        if registry.lookup_feature("rtph264pay"):
            report.checks.append(CheckItem(
                category="GStreamer",
                name="RTP H.264 Payloader (rtph264pay)",
                status="ok",
                message="rtph264pay available for projector RTP/UDP streaming.",
            ))
        else:
            missing_features.add("rtph264pay")
            report.checks.append(CheckItem(
                category="GStreamer",
                name="RTP H.264 Payloader (rtph264pay)",
                status="error",
                message="rtph264pay missing. Cannot package H.264 stream for projector.",
            ))

        # Audio capture & encoders
        has_pulse = registry.lookup_feature("pulsesrc") is not None
        if has_pulse or has_pipewire:
            aud_sources = []
            if has_pulse:
                aud_sources.append("PulseAudio (pulsesrc)")
            if has_pipewire:
                aud_sources.append("PipeWire (pipewiresrc)")
            report.checks.append(CheckItem(
                category="Audio Pipeline",
                name="Audio Capture Sources",
                status="ok",
                message=f"Available: {', '.join(aud_sources)}",
            ))
        else:
            report.checks.append(CheckItem(
                category="Audio Pipeline",
                name="Audio Capture Sources",
                status="warning",
                message="No audio capture source plugin found.",
                remedy="Audio streaming will be disabled.",
            ))

        has_opus = registry.lookup_feature("opusenc") is not None
        has_aac = registry.lookup_feature("avenc_aac") is not None
        if has_opus or has_aac:
            enc_name = "Opus" if has_opus else "AAC"
            report.checks.append(CheckItem(
                category="Audio Pipeline",
                name="Audio Stream Encoder",
                status="ok",
                message=f"{enc_name} encoder ready.",
            ))
        else:
            report.checks.append(CheckItem(
                category="Audio Pipeline",
                name="Audio Stream Encoder",
                status="warning",
                message="Neither opusenc nor avenc_aac found.",
            ))

    except Exception as e:
        report.checks.append(CheckItem(
            category="GStreamer",
            name="GStreamer Initialization",
            status="error",
            message="Failed to initialize GStreamer.",
            details=str(e),
        ))

    # ── 3. Network & Firewall Check ──────────────────────────────────────
    from .firewall import is_firewalld_active, is_ufw_active

    if is_ufw_active():
        report.checks.append(CheckItem(
            category="Security & Firewall",
            name="UFW Firewall",
            status="warning",
            message="UFW is active.",
            details="Ensure ports 3629 (TCP), 4352 (TCP), and 5004/5006 (UDP) are allowed.",
            remedy="Run 'linux-iprojection firewall' to automatically permit required ports.",
        ))
    elif is_firewalld_active():
        report.checks.append(CheckItem(
            category="Security & Firewall",
            name="Firewalld",
            status="warning",
            message="Firewalld is active.",
            details="Ensure ports 3629 (TCP), 4352 (TCP), and 5004/5006 (UDP) are allowed.",
            remedy="Run 'linux-iprojection firewall' to automatically configure firewalld.",
        ))
    else:
        report.checks.append(CheckItem(
            category="Security & Firewall",
            name="Local Firewall",
            status="ok",
            message="No active blocking firewall detected on standard filters.",
        ))

    # Network connectivity & local interfaces
    from .discovery import _local_ipv4_networks
    nets = _local_ipv4_networks()
    if nets:
        nets_str = ", ".join(str(n) for n in nets[:3])
        report.checks.append(CheckItem(
            category="Network Configuration",
            name="Active IPv4 Subnets",
            status="ok",
            message=f"Subnets ready for discovery: {nets_str}",
        ))
    else:
        report.checks.append(CheckItem(
            category="Network Configuration",
            name="Active IPv4 Subnets",
            status="warning",
            message="No active non-loopback IPv4 subnets found.",
            details="Connect to Wi-Fi or Ethernet to discover network projectors.",
        ))

    # Add remedy command if any packages are missing
    install_cmd = get_distro_install_command(missing_features, distro_id)
    if install_cmd:
        report.checks.append(CheckItem(
            category="Package Resolution",
            name="Recommended Fix Command",
            status="warning",
            message=f"Run the following command to install all missing plugins on {distro_name}:",
            details=install_cmd,
            remedy=install_cmd,
        ))

    return report


def print_doctor_report(report: DoctorReport) -> None:
    """Print a polished terminal view of the diagnostics report."""
    print("═" * 68)
    print(" linux-iprojection System Diagnostics & Compatibility Doctor")
    print("═" * 68)
    print(f" OS / Distribution:   {report.distro} ({report.os_name})")
    print(f" Desktop Environment: {report.desktop_session}")
    print(f" Display Server:      {report.display_server}")
    print("─" * 68)

    status_icons = {
        "ok": " [✓] OK:      ",
        "warning": " [!] WARNING: ",
        "error": " [✗] ERROR:   ",
    }

    current_cat = ""
    for item in report.checks:
        if item.category != current_cat:
            current_cat = item.category
            print(f"\n▶ {current_cat}")

        prefix = status_icons.get(item.status, " [*] ")
        print(f"  {prefix}{item.name}")
        print(f"        {item.message}")
        if item.details:
            print(f"        Details: {item.details}")
        if item.remedy and item.status != "ok":
            print(f"        Action:  {item.remedy}")

    print("\n" + "═" * 68)
    if report.has_errors:
        print(" Summary: Errors detected that may prevent screen casting.")
    elif report.has_warnings:
        print(" Summary: Fully functional, with minor warnings noted above.")
    else:
        print(" Summary: All systems green! Your Linux environment is 100% ready.")
    print("═" * 68)
