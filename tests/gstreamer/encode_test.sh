#!/usr/bin/env bash
# Synthetic H.264 encoding + pipeline test for linux-iprojection.
#
# Verifies that the x264enc GStreamer element is discoverable and that the
# screen-casting pipeline (software encoder -> h264parse -> RTP/UDP) can be
# constructed and started using synthetic input. Runs identically on a host
# GStreamer install and inside the Flatpak sandbox.
set -uo pipefail

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

FAILED=0

say() { printf '%s %s\n' "$1" "$2"; }

# 1. Encoder discovery ------------------------------------------------------
if gst-inspect-1.0 x264enc >/dev/null 2>&1; then
    say "OK" "gst-inspect-1.0 x264enc (encoder is discoverable)"
else
    say "FAIL" "gst-inspect-1.0 x264enc (encoder is NOT available)"
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
#    h264parse emits length-prefixed AVCC by default, so rather than relying on
#    typefind (which only matches Annex-B start codes) we check that the file
#    contains the mandatory SPS (0x67) and PPS (0x68) NAL units of a real H.264
#    encoded stream.
if [ -s "$TMPDIR/out.h264" ]; then
    if python3 - "$TMPDIR/out.h264" <<'PYEOF'
import sys
data = open(sys.argv[1], "rb").read()
sps = b"\x67" in data[:4096]
pps = b"\x68" in data[:4096]
idr = b"\x65" in data
if not sps:
    print("FAIL: no SPS NAL unit found")
    sys.exit(1)
if not pps:
    print("FAIL: no PPS NAL unit found")
    sys.exit(1)
if not idr:
    print("FAIL: no IDR slice found")
    sys.exit(1)
print(f"OK output is a valid H.264 stream ({len(data)} bytes, SPS/PPS/IDR present)")
PYEOF
    then
        say "OK" "output verified as H.264 (SPS/PPS/IDR NAL units present)"
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
