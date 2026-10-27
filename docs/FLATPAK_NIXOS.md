# Flatpak on NixOS & the H.264 encoder fix

This document explains why screen casting previously failed on NixOS, how the
Flatpak now bundles a compatible H.264 encoder, and how to build, install, test,
and troubleshoot the package.

## What caused the NixOS screen-casting failure

The Flatpak uses the **GNOME 48** runtime, which ships the GStreamer core and
the base/good plugin sets, but **not** `gst-plugins-ugly`. That means the
`x264enc` element (the software H.264 encoder) is absent inside the sandbox.

The application's software-fallback path then hard-coded `x264enc` as its "safe"
encoder and substituted it into the pipeline, producing:

```text
Fallback pipeline parse error:
gst_parse_error: no element "x264enc" (1)
```

The NixOS host has a system `libgstx264.so` under
`/run/current-system/sw/lib/gstreamer-1.0`, but that path is not visible inside
the Flatpak sandbox, and even if it were mounted, a host plugin built against
GStreamer 1.26.x is not ABI-compatible with the runtime's GStreamer 1.24.x.

## Why host plugin paths cannot be relied upon

- Flatpak runs the app in a sandbox; host library paths are not exposed by default.
- The host GStreamer version (e.g. 1.26.11) differs from the runtime's (1.24.x),
  so a host `.so` is not a valid drop-in for the runtime's GStreamer ABI.
- NixOS stores libraries under generation-specific `/nix/store` hashes, so any
  absolute path (or `GST_PLUGIN_PATH`) pointing into the Nix profile is fragile
  across upgrades and generations.

For a reliable, reproducible result, the encoder must be built against the exact
GStreamer ABI of the runtime and bundled inside the sandbox.

## Runtime and codec packaging strategy

The manifest (`packaging/flatpak/dev.linux_iprojection.LinuxIProjection.yml`)
builds two extra modules inside the Flatpak build environment:

1. **libx264** — pinned to the `stable` branch commit
   `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`.
2. **gst-plugins-ugly 1.24.12** — with `-Dgpl=enabled -Dx264=enabled` and all
   other plugins disabled, producing only the `libgstx264.so` plugin.

Both are installed under `/app/lib`, and `libgstx264.so` lands at
`/app/lib/gstreamer-1.0/libgstx264.so`, which is already on GStreamer's plugin
search path (`GST_PLUGIN_SYSTEM_PATH` includes `/app/lib/gstreamer-1.0`).

The runtime stays `org.gnome.Platform//48`; the SDK is `org.gnome.Sdk//48`,
whose GStreamer is 1.24.12 — bit-identical to the runtime, so the plugin links
cleanly.

> **Note:** GNOME 48 is an end-of-life runtime. The app still targets it for
> continuity with the existing installation; a future maintenance task is to
> bump the runtime to a supported GNOME branch and re-verify the encoder.

## Build and test the Flatpak

Prerequisites: `flatpak` and `flatpak-builder`, plus `appstream` (for
`appstreamcli`). On NixOS you can enter the provided dev shell:

```bash
nix develop          # or: nix develop .#full  (full shell also has host x264enc)
```

Build the Flatpak (exports to a local OSTree `repo/`):

```bash
make flatpak
```

Verify the encoder and run the synthetic encode test inside the built sandbox:

```bash
make flatpak-verify
# equivalent:
flatpak-builder --run build-dir packaging/flatpak/dev.linux_iprojection.LinuxIProjection.yml gst-inspect-1.0 x264enc
flatpak-builder --run build-dir packaging/flatpak/dev.linux_iprojection.LinuxIProjection.yml bash tests/gstreamer/encode_test.sh
```

Build the distributable bundle:

```bash
make flatpak-bundle
# produces: dist/linux-iprojection-nixos-x86_64.flatpak
```

## Install and run the bundle

```bash
flatpak install --user dist/linux-iprojection-nixos-x86_64.flatpak
flatpak run dev.linux_iprojection.LinuxIProjection
```

Or from the CLI:

```bash
flatpak run dev.linux_iprojection.LinuxIProjection doctor      # diagnostics
flatpak run dev.linux_iprojection.LinuxIProjection discover    # find projectors
```

Remove the installed bundle:

```bash
flatpak uninstall --user dev.linux_iprojection.LinuxIProjection
```

## Troubleshooting missing encoders

Confirm the encoder is visible inside the installed app:

```bash
flatpak run --command=gst-inspect-1.0 dev.linux_iprojection.LinuxIProjection x264enc
```

Run the full diagnostics:

```bash
flatpak run dev.linux_iprojection.LinuxIProjection doctor
```

On a host install, `make check-deps` reports which GStreamer elements are
present, and `make test-gstreamer` runs the synthetic encode test.

## Reproducing the synthetic encoding test

The script `tests/gstreamer/encode_test.sh`:

1. checks `gst-inspect-1.0 x264enc`;
2. encodes a synthetic `videotestsrc` stream to a file;
3. verifies the output contains the SPS/PPS/IDR NAL units of a real H.264 stream;
4. runs the exact software-encoder → `h264parse` → `rtph264pay` → `udpsink`
   pipeline used by screen casting.

Run it in the sandbox (see above), or on the host if a full GStreamer stack is
installed (`nix develop .#full && make test-gstreamer`).

## Releasing

The release bundle name, install command, and checksum are printed by
`make flatpak-bundle`. For a full release, `make flatpak-bundle` plus
`sha256sum dist/linux-iprojection-nixos-x86_64.flatpak` records the artifact
provenance.

## What was tested

- Python unit tests (`make test`, or `nix develop` + `pytest`) — 80 passed, 1 skipped.
- Ruff lint (`make lint`) — clean.
- `gst-inspect-1.0 x264enc` in the built sandbox and installed bundle — passes.
- Synthetic H.264 encode + fallback RTP/UDP pipeline in the sandbox and bundle — passes.
- `linux-iprojection doctor` reports `x264enc` available.
- Bundle installs into an isolated user installation and uninstalls cleanly.

**Not tested:** physical Epson projector hardware. Discovery, protocol, and
streaming paths were validated against unit tests and deterministic GStreamer
pipeline tests only.

## Known limitations

- GNOME 48 is end-of-life; a future release should migrate to a supported runtime.
- The tray icon (`pystray`) needs an AppIndicator/StatusNotifier backend that is
  not present in the GNOME runtime; the app degrades gracefully when it is absent.
- Physical projector screen casting was not exercised in this environment.

## Licenses

See `THIRD_PARTY_NOTICES.md` for the x264 and gst-plugins-ugly provenance and
licensing notes.
