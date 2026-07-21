# epsonctl

A native Linux app for controlling and (eventually) screen-casting to
Epson projectors - GTK4 + libadwaita UI, works the same across GNOME,
KDE, niri, Hyprland, and other Wayland compositors/X11.

## Status

| Feature | State |
|---|---|
| ESC/VP.net control (power, source, mute, lamp hours) | Implemented, untested against real hardware |
| Device discovery (LAN port scan) | Implemented |
| Device discovery (mDNS) | Implemented, service-type strings are placeholders - need confirming |
| GTK4/libadwaita UI | Implemented - device list, control panel, manual add |
| Screen capture (XDG portal + PipeWire) | Scaffolded, portal D-Bus negotiation not yet written |
| Screen cast delivery to EShare receiver | **Not implemented** - wire protocol unconfirmed, see `cast.py` |

## Why it's split this way

Two protocols are involved and they have very different confidence levels:

- **ESC/VP.net** (control: power/input/mute/status) is documented by Epson
  and third parties (Atlona, openHAB's Epson binding, Epson's own KB
  articles). `protocol.py` implements the handshake and commands directly
  from that documentation.
- **EShare casting** (mirroring your screen to the projector) has no public
  protocol spec that I could verify. `eshare-linux-client` clearly solved
  this - likely via packet capture/reverse engineering - but I didn't want
  to fabricate wire-format details in code that would just fail silently
  against a real device. `cast.py` has the capture half (which *is*
  standards-based, via `xdg-desktop-portal` + PipeWire) built out, with a
  clearly-marked seam (`CastSink`) for the delivery half once we've
  confirmed it against that project's source.

## Setup

```bash
# System packages (Fedora/Arch names shown; adjust for your distro)
sudo pacman -S python-gobject gtk4 libadwaita gstreamer gst-plugins-good gst-plugins-bad python-zeroconf
# or: sudo dnf install python3-gobject gtk4-devel libadwaita-devel gstreamer1-plugins-good gstreamer1-plugins-bad-free python3-zeroconf

python -m venv .venv --system-site-packages   # --system-site-packages needed for PyGObject
source .venv/bin/activate
pip install -e .

epsonctl
```

`--system-site-packages` is required because PyGObject/GTK bindings are
normally installed as distro packages, not via pip, on most distros.

## Testing the control protocol without the GUI

```python
import asyncio
from epsonctl.protocol import EscVpNetClient

async def main():
    async with EscVpNetClient("192.168.1.50") as p:
        print(await p.get_status())

asyncio.run(main())
```

## Next steps (in priority order)

1. Confirm the mDNS service type EShare receivers advertise, and the
   casting wire protocol - both from `eshare-linux-client`'s source.
2. Implement the XDG portal `ScreenCast` D-Bus negotiation in
   `cast.py::ScreenCaster._request_portal_stream` (isolated on purpose -
   this is a self-contained ~50-line addition).
3. Test `protocol.py` against real hardware; adjust the `Source` enum
   codes for your specific projector model (they vary - check its
   ESC/VP21 command guide).
4. Package as a Flatpak for easy install across distros (GTK4/libadwaita
   apps are the easiest case for this).
