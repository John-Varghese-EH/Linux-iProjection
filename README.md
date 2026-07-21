<div align="center">
  <img src="data/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg" width="128" alt="iProjection Logo"/>
  <h1>iProjection (Unofficial)</h1>
  <p><b>The ultimate, enterprise-grade controller for Epson projectors on Linux.</b></p>
  
  [![CI](https://github.com/John-Varghese-EH/Linux-iProjection/actions/workflows/ci.yml/badge.svg)](https://github.com/John-Varghese-EH/Linux-iProjection/actions/workflows/ci.yml)
  [![AUR Package](https://img.shields.io/aur/version/linux-iprojection)](https://aur.archlinux.org/packages/linux-iprojection)
  [![Ubuntu PPA](https://img.shields.io/badge/Ubuntu-PPA-orange.svg)](https://launchpad.net/iprojection)
  [![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
  [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
</div>

---

I built this application because I was frustrated by the lack of native, robust Linux support for Epson's enterprise hardware.

**Linux-iProjection** bridges the gap in enterprise projector management by delivering native, robust Linux support for Epson hardware. Built for environments that demand seamless control, instant diagnostics, and high-performance screen casting without relying on proprietary or unsupported drivers.

It bridges that gap. It gives you complete command over network and mDNS projection using native Linux technologies, packaged in a sleek, responsive GTK4 design.

## Core Capabilities

* **Native GTK4 Interface:** A hardware-accelerated, responsive graphical interface built on modern Linux desktop standards.
* **Comprehensive Automation:** A feature-complete Command Line Interface (CLI) designed for shell scripting and remote SSH administration.
* **Network Auto-Discovery:** Instant, zero-configuration projector detection across local subnets using mDNS and SSDP.
* **Enterprise Diagnostics:** Real-time hardware telemetry including lamp hours, thermal warnings, and error state monitoring.
* **PipeWire Screen Casting:** Low-latency, high-bandwidth screen mirroring optimized for Wayland and X11 display servers.
* **PJLink Security:** Robust authentication support for secured enterprise environments.

---

## Installation

### Arch Linux (AUR)
The application is available on the [Arch User Repository (AUR)](https://aur.archlinux.org/packages/linux-iprojection). Install using your preferred helper:
```bash
yay -S linux-iprojection
# or
paru -S linux-iprojection
```

### Ubuntu / Debian (PPA)
For automated updates on Debian-based systems, add the [official PPA](https://launchpad.net/iprojection):
```bash
sudo add-apt-repository ppa:john-varghese/linux-iprojection
sudo apt update
sudo apt install linux-iprojection
```

Alternatively, you can deploy the standalone `.deb` package directly from the [Releases](https://github.com/John-Varghese-EH/Linux-iProjection/releases) page:
```bash
sudo dpkg -i linux-iprojection_*.deb
sudo apt-get install -f
```

### Universal Linux (Flatpak)
Download the sandboxed `linux-iprojection-linux.flatpak` bundle from the [Releases](https://github.com/John-Varghese-EH/Linux-iProjection/releases) page and install it natively on any modern distribution:
```bash
flatpak install --user linux-iprojection-linux.flatpak
```

### Build from Source
To run the application via Python or deploy a development environment:
```bash
git clone https://github.com/John-Varghese-EH/Linux-iProjection.git
cd Linux-iProjection
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Command Line Interface

The included `linux-iprojection` binary provides full parity with the graphical interface, making it ideal for automation.

```bash
# Discover all projectors broadcasting on the local subnet
linux-iprojection discover

# Manage hardware power state
linux-iprojection power on 192.168.1.100
linux-iprojection power off 192.168.1.100

# Switch the active video input (e.g., HDMI1, VGA, LAN)
linux-iprojection source HDMI1 192.168.1.100

# Retrieve real-time telemetry and hardware status
linux-iprojection status 192.168.1.100
```

---

## Contributing

Contributions to the codebase are strongly encouraged. For major architectural changes or new protocol support, please open an issue first to discuss the implementation strategy. All patches must pass the integrated test suite prior to review.

To run the automated tests and linter locally:
```bash
make test
make lint
```

---

## License & Attribution

Architected & developed with ❤️ by **[John Varghese (J0X)](https://github.com/John-Varghese-EH)**. 
- Connect with me on [LinkedIn](https://www.linkedin.com/in/John--Varghese).

This project is licensed under the **AGPL-3.0 License**. See the [LICENSE](LICENSE) file for the full legal text. 

*Disclaimer: This is an unofficial, community-driven application and is not affiliated with, endorsed by, or sponsored by Seiko Epson Corporation.*
