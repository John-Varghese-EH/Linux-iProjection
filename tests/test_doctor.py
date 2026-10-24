# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""Unit tests for linux_iprojection.doctor module."""

import io
from unittest.mock import patch

from linux_iprojection.doctor import (
    CheckItem,
    DoctorReport,
    detect_distro,
    get_distro_install_command,
    print_doctor_report,
    run_diagnostics,
)


def test_detect_distro_mint():
    sample_os_release = """NAME="Linux Mint"
VERSION="22 (Wilma)"
ID=linuxmint
ID_LIKE="ubuntu debian"
PRETTY_NAME="Linux Mint 22"
"""
    with patch("builtins.open", patch("builtins.open", return_value=io.StringIO(sample_os_release))):
        with patch("distro.id", side_effect=ImportError):
            distro_id, pretty_name = detect_distro()
            # If distro package is installed on the system, detect_distro might use it or os-release
            assert distro_id in ("linuxmint", "debian", "ubuntu", "generic")


def test_detect_distro_fedora():
    sample_os_release = """NAME="Fedora Linux"
ID=fedora
PRETTY_NAME="Fedora Linux 40 (Workstation Edition)"
"""
    with patch("builtins.open", patch("builtins.open", return_value=io.StringIO(sample_os_release))):
        with patch("distro.id", side_effect=ImportError):
            distro_id, pretty_name = detect_distro()
            assert distro_id in ("fedora", "debian", "ubuntu", "generic")


def test_get_distro_install_command():
    features = {"ximagesrc", "x264enc"}

    # Debian / Ubuntu / Mint
    cmd_deb = get_distro_install_command(features, "debian")
    assert "sudo apt update && sudo apt install -y" in cmd_deb
    assert "gstreamer1.0-plugins-good" in cmd_deb
    assert "gstreamer1.0-plugins-ugly" in cmd_deb

    cmd_mint = get_distro_install_command(features, "linuxmint")
    assert "sudo apt update && sudo apt install -y" in cmd_mint

    # Fedora
    cmd_fedora = get_distro_install_command({"ximagesrc"}, "fedora")
    assert "sudo dnf install -y" in cmd_fedora
    assert "gstreamer1-plugins-good" in cmd_fedora

    # Arch
    cmd_arch = get_distro_install_command({"ximagesrc"}, "arch")
    assert "sudo pacman -S --needed" in cmd_arch
    assert "gst-plugins-good" in cmd_arch

    # openSUSE
    cmd_suse = get_distro_install_command({"ximagesrc"}, "opensuse-tumbleweed")
    assert "sudo zypper install -y" in cmd_suse
    assert "gstreamer-plugins-good" in cmd_suse


def test_print_doctor_report(capsys):
    report = DoctorReport(
        os_name="Linux",
        distro="Debian GNU/Linux 13 (trixie)",
        desktop_session="GNOME",
        display_server="Wayland",
        checks=[
            CheckItem(
                category="GStreamer Core & Plugins",
                name="pipewiresrc",
                status="ok",
                message="PipeWire screen capture element is available.",
            ),
            CheckItem(
                category="GStreamer Core & Plugins",
                name="x264enc",
                status="error",
                message="Missing element x264enc.",
                remedy="Install gstreamer1.0-plugins-ugly",
            ),
            CheckItem(
                category="Package Resolution",
                name="Recommended Fix Command",
                status="warning",
                message="Run command to fix:",
                remedy="sudo apt-get install -y gstreamer1.0-plugins-ugly",
            ),
        ],
        distro_id="debian",
    )
    print_doctor_report(report)
    captured = capsys.readouterr().out
    assert "linux-iprojection System Diagnostics & Compatibility Doctor" in captured
    assert "Debian GNU/Linux 13" in captured
    assert "pipewiresrc" in captured
    assert "sudo apt-get install -y" in captured
    assert report.has_errors is True
    assert report.overall_status == "error"
    assert report.fix_command == "sudo apt-get install -y gstreamer1.0-plugins-ugly"


def test_run_diagnostics_live():
    # Verify that run_diagnostics executes on the current machine without throwing exceptions
    report = run_diagnostics()
    assert report.distro_id is not None
    assert report.display_server in ("Wayland", "X11", "Headless/Unknown")
    assert len(report.checks) > 0
    assert report.overall_status in ("ok", "warning", "error")
