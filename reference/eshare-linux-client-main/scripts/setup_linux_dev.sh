#!/usr/bin/env bash
# =============================================================================
# setup_linux_dev.sh - linux-iprojection One-Click Dev Environment Setup
# =============================================================================
#
# Installs all system and Python dependencies needed to build, run, and test
# the linux-iprojection wireless projection app on:
#
#   • Ubuntu 24.04 LTS  (apt / dpkg)
#   • Fedora 39 / 40    (dnf)
#
# Usage (on your Linux machine / VM / Live USB):
#   chmod +x scripts/setup_linux_dev.sh
#   ./scripts/setup_linux_dev.sh
#
# What it installs
# ----------------
#   GTK4 + Adwaita UI library
#   GStreamer 1.x core + all plugin packs (good/bad/ugly/vaapi/pipewire)
#   PipeWire + WirePlumber session manager
#   xdg-desktop-portal + GNOME/KDE backend (for screen-cast portal)
#   Python 3 PyGObject bindings (python3-gi)
#   Python pip packages: zeroconf, netifaces, dasbus, pytest
#
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'   # No Colour

banner() {
    echo -e "\n${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }
err()  { echo -e "  ${RED}✗ ERROR:${NC} $1" >&2; exit 1; }

# ── Detect distro ─────────────────────────────────────────────────────────────
detect_distro() {
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        source /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_VERSION="${VERSION_ID:-0}"
    else
        err "Cannot detect Linux distribution (no /etc/os-release)."
    fi

    case "${DISTRO_ID}" in
        ubuntu|debian|linuxmint)
            PKG_MANAGER="apt"
            ;;
        fedora|rhel|centos)
            PKG_MANAGER="dnf"
            ;;
        *)
            warn "Unrecognised distro '${DISTRO_ID}'. Attempting apt-based install."
            PKG_MANAGER="apt"
            ;;
    esac

    echo -e "${BOLD}Detected:${NC} ${DISTRO_ID} ${DISTRO_VERSION} (using ${PKG_MANAGER})"
}

# ── Check we have sudo ────────────────────────────────────────────────────────
check_sudo() {
    if ! command -v sudo &>/dev/null; then
        err "sudo is required. Install it or run this script as root."
    fi
    if ! sudo -n true 2>/dev/null; then
        warn "This script needs sudo for system package installation."
        warn "You may be prompted for your password."
    fi
}

# ── Python version check ──────────────────────────────────────────────────────
check_python() {
    if ! command -v python3 &>/dev/null; then
        err "python3 not found. Install Python 3.11+ first."
    fi
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "${PY_MAJOR}" -lt 3 ] || ([ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 11 ]); then
        err "Python 3.11+ is required. Found Python ${PY_VERSION}."
    fi
    ok "Python ${PY_VERSION} found."
}

# ── Ubuntu / Debian package install ───────────────────────────────────────────
install_apt() {
    banner "Installing system packages (apt)"

    info "Updating package lists…"
    sudo apt-get update -qq

    APT_PACKAGES=(
        # ── GTK4 + Adwaita ──────────────────────────────────────────────
        python3-gi
        python3-gi-cairo
        gir1.2-gtk-4.0
        gir1.2-adw-1
        libadwaita-1-dev
        libgtk-4-dev

        # ── GStreamer core ───────────────────────────────────────────────
        gstreamer1.0-tools
        gstreamer1.0-plugins-base
        gstreamer1.0-plugins-good
        gstreamer1.0-plugins-bad
        gstreamer1.0-plugins-ugly
        gstreamer1.0-libav

        # ── GStreamer Python bindings ─────────────────────────────────────
        gir1.2-gst-plugins-base-1.0
        gir1.2-gstreamer-1.0
        python3-gst-1.0

        # ── GStreamer hardware acceleration ───────────────────────────────
        gstreamer1.0-vaapi          # Intel / AMD VA-API
        # gstreamer1.0-nvcodec      # Uncomment for NVIDIA (needs nvidia drivers)

        # ── PipeWire + WirePlumber ────────────────────────────────────────
        pipewire
        pipewire-pulse
        pipewire-audio
        wireplumber
        libpipewire-0.3-dev
        gstreamer1.0-pipewire

        # ── xdg-desktop-portal (ScreenCast) ──────────────────────────────
        xdg-desktop-portal
        xdg-desktop-portal-gnome    # GNOME backend (use -kde for KDE)
        # xdg-desktop-portal-kde    # Uncomment for KDE Plasma

        # ── DBus (for dasbus) ─────────────────────────────────────────────
        python3-dbus
        libdbus-1-dev

        # ── Network / mDNS ────────────────────────────────────────────────
        avahi-daemon
        avahi-utils
        libnss-mdns

        # ── Dev tools ────────────────────────────────────────────────────
        python3-pip
        python3-venv
        pkg-config
        build-essential
    )

    sudo apt-get install -y "${APT_PACKAGES[@]}"
    ok "All apt packages installed."
}

# ── Fedora / RHEL package install ─────────────────────────────────────────────
install_dnf() {
    banner "Installing system packages (dnf)"

    # Enable RPM Fusion for GStreamer plugins (ugly/ffmpeg)
    info "Enabling RPM Fusion repositories…"
    sudo dnf install -y \
        "https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
        "https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm" \
        2>/dev/null || warn "RPM Fusion already enabled or unreachable - continuing."

    DNF_PACKAGES=(
        # ── GTK4 + Adwaita ──────────────────────────────────────────────
        python3-gobject
        python3-gobject-base
        gtk4
        gtk4-devel
        libadwaita
        libadwaita-devel

        # ── GStreamer core ───────────────────────────────────────────────
        gstreamer1
        gstreamer1-devel
        gstreamer1-plugins-base
        gstreamer1-plugins-good
        gstreamer1-plugins-bad-free
        gstreamer1-plugins-ugly
        gstreamer1-libav

        # ── GStreamer Python ─────────────────────────────────────────────
        python3-gstreamer1

        # ── GStreamer VA-API ─────────────────────────────────────────────
        gstreamer1-vaapi

        # ── PipeWire + WirePlumber ────────────────────────────────────────
        pipewire
        pipewire-pulseaudio
        wireplumber
        pipewire-devel
        gstreamer1-plugin-pipewire

        # ── xdg-desktop-portal ────────────────────────────────────────────
        xdg-desktop-portal
        xdg-desktop-portal-gnome
        # xdg-desktop-portal-kde    # Uncomment for KDE Plasma

        # ── DBus ──────────────────────────────────────────────────────────
        python3-dbus
        dbus-devel

        # ── Network / mDNS ────────────────────────────────────────────────
        avahi
        avahi-tools
        nss-mdns

        # ── Dev tools ────────────────────────────────────────────────────
        python3-pip
        python3-virtualenv
        pkgconf
        gcc
        make
    )

    sudo dnf install -y "${DNF_PACKAGES[@]}"
    ok "All dnf packages installed."
}

# ── Python pip packages ────────────────────────────────────────────────────────
install_pip() {
    banner "Installing Python packages (pip)"

    # Prefer installing into the project venv if it exists; otherwise user-level
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
    VENV_DIR="${PROJECT_ROOT}/.venv"

    if [ ! -d "${VENV_DIR}" ]; then
        info "Creating virtual environment at ${VENV_DIR} …"
        python3 -m venv "${VENV_DIR}"
        ok "Virtual environment created."
    else
        ok "Virtual environment already exists at ${VENV_DIR}."
    fi

    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"

    info "Upgrading pip…"
    pip install --upgrade pip -q

    info "Installing project requirements…"
    pip install -r "${PROJECT_ROOT}/requirements.txt"

    # dasbus needs to be installed even if listed in requirements, confirm it:
    pip install dasbus

    ok "Python packages installed into ${VENV_DIR}."
    echo -e "\n  ${YELLOW}Activate your venv with:${NC}  source ${VENV_DIR}/bin/activate"
}

# ── Enable / start system services ────────────────────────────────────────────
setup_services() {
    banner "Configuring system services"

    # PipeWire runs as a user service (not system)
    info "Enabling PipeWire user services…"
    systemctl --user enable --now pipewire pipewire-pulse wireplumber 2>/dev/null \
        || warn "Could not start PipeWire services (you may need to log out and back in)."

    # Avahi (mDNS)
    if systemctl list-unit-files avahi-daemon.service &>/dev/null; then
        info "Enabling avahi-daemon…"
        sudo systemctl enable --now avahi-daemon 2>/dev/null \
            || warn "avahi-daemon could not be started."
    fi

    ok "Services configured."
}

# ── Post-install verification ──────────────────────────────────────────────────
verify_install() {
    banner "Verifying installation"

    check_tool() {
        if command -v "$1" &>/dev/null; then
            ok "$1 found ($(command -v "$1"))"
        else
            warn "$1 not found in PATH - check installation."
        fi
    }

    check_tool gst-launch-1.0
    check_tool gst-inspect-1.0
    check_tool pw-cli
    check_tool avahi-browse

    # Check key GStreamer plugins
    info "Checking GStreamer plugin availability…"
    for plugin in x264enc opusenc videotestsrc audiotestsrc rtph264pay udpsink; do
        if gst-inspect-1.0 "${plugin}" &>/dev/null; then
            ok "  GStreamer: ${plugin}"
        else
            warn "  GStreamer: ${plugin} NOT FOUND (some features may not work)"
        fi
    done

    # Check pipewiresrc
    if gst-inspect-1.0 pipewiresrc &>/dev/null; then
        ok "  GStreamer: pipewiresrc (Wayland capture ready)"
    else
        warn "  GStreamer: pipewiresrc not found - PipeWire GStreamer integration may need a reboot/re-login."
    fi
}

# ── Print next steps ──────────────────────────────────────────────────────────
print_next_steps() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
    VENV_DIR="${PROJECT_ROOT}/.venv"

    banner "Setup Complete - Next Steps"
    cat <<EOF
  1. Activate the virtual environment:
       source ${VENV_DIR}/bin/activate

  2. Start the mock projector receiver (Terminal 1):
       python tools/mock_receiver.py

  3. Test mDNS discovery (Terminal 2):
       python -m src.discovery.mdns_scanner

  4. Launch the full GTK4 application:
       python -m src.main

  If the screen capture portal dialog doesn't appear:
    → Make sure you're running a Wayland session (not X11)
    → Log out and back in after install to start PipeWire

  For hardware-accelerated encoding, install your GPU drivers first:
    Intel iGPU:  sudo apt install intel-media-va-driver-non-free
    AMD:         sudo apt install mesa-va-drivers
    NVIDIA:      install proprietary driver + gstreamer1.0-nvcodec
EOF
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    banner "linux-iprojection Dev Environment Setup"
    echo -e "  ${BOLD}OS:${NC} $(uname -srm)\n"

    detect_distro
    check_sudo
    check_python

    case "${PKG_MANAGER}" in
        apt) install_apt ;;
        dnf) install_dnf ;;
    esac

    install_pip
    setup_services
    verify_install
    print_next_steps
}

main "$@"
