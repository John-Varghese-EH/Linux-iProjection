# Third-Party Protocols, Specifications & Dependencies

## Epson ESC/VP.net & ESC/VP21

Command protocol logic is implemented directly from Epson's publicly available "ESC/VP.net Software Development Manual" and ESC/VP21 command guides.

## Open Networking Standards

Network discovery and media streaming are implemented using standard open networking protocols: mDNS/DNS-SD for device discovery, RTP over UDP for media streaming, and PipeWire via the XDG Desktop Portal specification for screen capture.

## Bundled GStreamer H.264 Encoder (Flatpak only)

The Flatpak package bundles a `libgstx264.so` GStreamer plugin and its
`libx264` dependency so that `x264enc` is available inside the sandbox. These
are built from source during the Flatpak build and installed under
`/app/lib/gstreamer-1.0`.

| Component | Version / source | License |
| --------- | ---------------- | ------- |
| x264 | commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55` (`stable` branch, <https://code.videolan.org/videolan/x264>) | GPL-2.0-or-later |
| gst-plugins-ugly (x264enc element) | 1.24.12, <https://gstreamer.freedesktop.org/src/gst-plugins-ugly/> | LGPL-2.1-or-later; the `x264` plugin is distributed under GPL-2.0-or-later because it links against libx264 |

Source archives:
- gst-plugins-ugly 1.24.12: `https://gstreamer.freedesktop.org/src/gst-plugins-ugly/gst-plugins-ugly-1.24.12.tar.xz` (SHA-256 `19ed6eef4ea1a742234fb35e2cdb107168595a4dd409a9fac0b7a16543eee78b`)

This project is licensed AGPL-3.0-or-later. GPL-2.0-or-later code may be
combined with AGPL-3.0-or-later code (the GPLv2 component is distributed under
GPL-3.0-or-later, which is one-way compatible with AGPL-3.0-or-later). The
bundled encoder is only linked at runtime; it is not incorporated into the
application source.

## Python Dependencies

The application depends on PyGObject (GTK4/libadwaita bindings), zeroconf,
pystray, and Pillow. See `pyproject.toml` for the declared versions and their
licenses (all LGPL/MIT/BSD compatible with the project license).
