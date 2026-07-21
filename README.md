<div align="center">
  <img src="data/icons/hicolor/scalable/apps/dev.epsonctl.EpsonCtl.svg" width="128" alt="iProjection Logo"/>
  <h1>iProjection (Unofficial)</h1>
  <p><b>The ultimate, enterprise-grade controller for Epson projectors on Linux.</b></p>
  
  [![CI](https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux/actions/workflows/ci.yml/badge.svg)](https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux/actions/workflows/ci.yml)
  [![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
  [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
</div>

---

Hey, I'm **John Varghese (J0X)**.

I built this application because I was frustrated by the lack of native, robust Linux support for Epson's enterprise hardware. In professional IT environments, you need seamless control, instant diagnostics, and the ability to cast your screen without fighting proprietary drivers. 

**iProjection for Linux** bridges that gap. It gives you complete command over network and mDNS projection using native Linux technologies, packaged in a sleek, responsive GTK4 design.

## ✨ Features

- 🖥️ **Native GTK4 GUI**: A beautiful, responsive interface that matches your Linux desktop environment.
- ⌨️ **Powerful CLI**: Automate and control everything directly from your terminal.
- 📡 **mDNS Auto-Discovery**: Instantly find projectors on your local network—no manual IP configuration required.
- 🛠️ **Enterprise Diagnostics**: Monitor lamp hours, current errors, and hardware status in real-time.
- 📺 **PipeWire Screen Casting**: Low-latency, high-quality screen casting built specifically for modern Wayland and X11 desktops.
- 🔒 **PJLink Support**: Secure authentication for enterprise environments.

## 🚀 Installation

### Debian / Ubuntu
Download the latest `.deb` package from the [Releases](https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux/releases) page.
```bash
sudo dpkg -i epsonctl_*.deb
sudo apt-get install -f
```

### Arch Linux
You can build the package using the provided `PKGBUILD`:
```bash
makepkg -si
```

### Build from Source (Python)
If you want to run it directly via Python or develop the tool:
```bash
git clone https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux.git
cd EPSON-iProjection-For-Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 💻 CLI Usage

You can automate `epsonctl` using its built-in Command Line Interface. 

```bash
# Discover projectors on your local network
epsonctl discover

# Turn a projector ON or OFF
epsonctl power on 192.168.1.100
epsonctl power off 192.168.1.100

# Switch the input source (e.g., HDMI1, VGA)
epsonctl source HDMI1 192.168.1.100

# Check hardware status and lamp hours
epsonctl status 192.168.1.100
```

## 🤝 Contributing

Pull requests are always welcome. For major changes, please open an issue first to discuss what you would like to change.
Please make sure to update tests as appropriate.

Run the test suite using:
```bash
make test
```

## 📝 Credits & License

Architected & developed with ❤️ by **[John Varghese (J0X)](https://github.com/John-Varghese-EH)**. 
- Connect with me on [LinkedIn](https://www.linkedin.com/in/John--Varghese).

This project is licensed under the **AGPL-3.0 License** - see the [LICENSE](LICENSE) file for details. 

*Note: This is an unofficial, community-driven application and is not affiliated with Seiko Epson Corporation.*
