# linux-iprojection

A Linux desktop application for wireless screen projection to **Epson projectors** and **EShare-enabled displays**, built with Python, GTK4, and GStreamer.

## Features

- 🔍 **Auto-discovery** - mDNS (Zeroconf), SSDP, and subnet port-scan fallback
- 📡 **Wayland-native** - PipeWire screen capture via `pipewiresrc` + xdg-desktop-portal
- 🔊 **Audio support** - System audio capture via PipeWire/PulseAudio mixed into the stream
- 🎮 **Epson control** - ESC/VP.net (TCP 3629) for power, input switching, and status queries
- 🖥️ **GTK4 UI** - Native GNOME look with Libadwaita

## Quick Start

### System Dependencies

```bash
sudo apt install \
  python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  gir1.2-gst-plugins-base-1.0 gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-vaapi gstreamer1.0-pipewire \
  libpipewire-0.3-dev
```

### Python Dependencies

```bash
pip install -r requirements.txt
```

### Run the Mock Receiver (local testing)

Start a mock projector/display on your machine before you have access to real hardware:

```bash
python tools/mock_receiver.py --port 5004 --control-port 3629
```

This advertises itself via mDNS as `MockProjector._epson._tcp.local.` and listens for RTP streams on UDP port 5004.

### Run the Discovery Scanner (CLI test)

```bash
python -m src.discovery.mdns_scanner
```

## Architecture

```
src/
├── main.py                  # Gtk.Application entry point
├── app_window.py            # Main GTK4 window
├── models/device.py         # Device dataclass
├── discovery/               # mDNS + SSDP + subnet scan
├── control/                 # ESC/VP.net + PJLink control
└── streaming/               # GStreamer pipeline (pipewiresrc + encoding + RTP)

tools/
└── mock_receiver.py         # Local mock projector for development testing
```

## Protocol Notes

- **Epson ESC/VP.net**: TCP port 3629, hex handshake, text commands (`PWR ON\r`, `SOURCE 30\r`)
- **mDNS service types**: `_epson._tcp.local.`, `_eshare._tcp.local.`
- **SSDP**: UDP multicast to `239.255.255.250:1900`
- **Stream transport**: RTP/H.264 over UDP, or RTSP server mode

## License

GPL-3.0-or-later
