#!/usr/bin/env bash
# Synthetic H.264 encoding + pipeline test for linux-iprojection.
#
# Verifies that the x264enc GStreamer element is discoverable and that the
# screen-casting pipeline (software encoder -> h264parse -> RTP/UDP) can be
# constructed and started using synthetic input. Runs identically on a host
# GStreamer install and inside the Flatpak sandbox.
set -uo pipefail

# Ensure GStreamer discovers custom bundled plugins inside Flatpak (/app)
if [ -d "/app/lib/gstreamer-1.0" ] || [ -d "/app/lib/x86_64-linux-gnu/gstreamer-1.0" ]; then
    export GST_PLUGIN_PATH="/app/lib/gstreamer-1.0:/app/lib/x86_64-linux-gnu/gstreamer-1.0${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

FAILED=0

say() { printf '%s %s\n' "$1" "$2"; }

# 1. Element discovery ------------------------------------------------------
if gst-inspect-1.0 x264enc >/dev/null 2>&1; then
    say "OK" "gst-inspect-1.0 x264enc (encoder is discoverable)"
else
    say "FAIL" "gst-inspect-1.0 x264enc (encoder is NOT available)"
    FAILED=1
fi

if gst-inspect-1.0 h264parse >/dev/null 2>&1; then
    say "OK" "gst-inspect-1.0 h264parse (parser is discoverable)"
else
    say "FAIL" "gst-inspect-1.0 h264parse (parser is NOT available - install gstreamer1.0-plugins-bad)"
    FAILED=1
fi

# 2. Synthetic encode -> H.264 Annex-B file ---------------------------------
if gst-launch-1.0 -q \
    videotestsrc num-buffers=90 pattern=smpte ! \
    "video/x-raw,width=640,height=480,framerate=30/1" ! \
    videoconvert ! videoscale ! \
    x264enc bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30 ! \
    h264parse ! \
    filesink location="$TMPDIR/out.h264" 2>"$TMPDIR/encode.log"; then
    SIZE=$(wc -c < "$TMPDIR/out.h264")
    if [ "$SIZE" -gt 0 ]; then
        say "OK" "synthetic x264enc encode produced ${SIZE} bytes"
    else
        say "FAIL" "synthetic encode produced no output"
        FAILED=1
    fi
else
    say "FAIL" "synthetic x264enc encode failed"
    cat "$TMPDIR/encode.log" >&2
    FAILED=1
fi

# 3. Verify the output is a valid H.264 elementary stream --------------------
#    h264parse emits length-prefixed AVCC by default, so we parse the
#    length-prefixed NAL units and check that SPS (type 7), PPS (type 8) and
#    IDR (type 5) units are present at valid unit boundaries rather than just
#    scanning for coincidental byte values.
if [ -s "$TMPDIR/out.h264" ]; then
    if python3 - "$TMPDIR/out.h264" <<'PYEOF'
import struct
import sys

data = open(sys.argv[1], "rb").read()

def nal_units(buf):
    """Yield NAL units from an AVCC (length-prefixed) H.264 byte stream."""
    i = 0
    n = len(buf)
    while i + 4 <= n:
        (size,) = struct.unpack(">I", buf[i:i + 4])
        i += 4
        if size == 0 or i + size > n:
            break
        yield buf[i:i + size]
        i += size

nal_types = set()
for nal in nal_units(data):
    if nal:
        nal_types.add(nal[0] & 0x1F)  # nal_unit_type is the low 5 bits

missing = []
if 7 not in nal_types:   # SPS
    missing.append("SPS (type 7)")
if 8 not in nal_types:   # PPS
    missing.append("PPS (type 8)")
if 5 not in nal_types:   # IDR slice
    missing.append("IDR slice (type 5)")

if missing:
    print("FAIL: missing NAL units: " + ", ".join(missing))
    sys.exit(1)

print(f"OK output is a valid H.264 stream "
      f"({len(data)} bytes, {len(nal_types)} NAL types, SPS/PPS/IDR present)")
PYEOF
    then
        say "OK" "output verified as H.264 (SPS/PPS/IDR NAL units at valid boundaries)"
    else
        say "FAIL" "output is not a valid H.264 stream"
        FAILED=1
    fi
fi

# 4. The fallback-style pipeline (software encoder -> RTP/UDP) must start ---
#    num-buffers=60 yields EOS, so a clean exit proves the pipeline reached
#    PLAYING and negotiated the encoder without a missing-element failure.
if gst-launch-1.0 -q \
    videotestsrc num-buffers=60 pattern=smpte ! \
    "video/x-raw,width=640,height=480,framerate=30/1" ! \
    videoconvert ! videoscale ! \
    x264enc bitrate=4000 speed-preset=veryfast tune=zerolatency key-int-max=30 ! \
    h264parse ! \
    rtph264pay config-interval=1 pt=96 mtu=1400 ! \
    udpsink host=127.0.0.1 port=5004 sync=false 2>"$TMPDIR/rtp.log"; then
    say "OK" "fallback RTP/UDP pipeline started and completed"
else
    if grep -q "no element" "$TMPDIR/rtp.log"; then
        say "FAIL" "fallback RTP/UDP pipeline: missing element"
        cat "$TMPDIR/rtp.log" >&2
        FAILED=1
    else
        say "FAIL" "fallback RTP/UDP pipeline failed"
        cat "$TMPDIR/rtp.log" >&2
        FAILED=1
    fi
fi

if [ "$FAILED" -ne 0 ]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
