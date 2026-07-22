# Epson Projector Protocol Notes

Documentation compiled directly from Epson network protocol specifications and public technical documentation. Sufficient detail for reimplementation.

## ESC/VP.net Control Protocol

### Connection
- TCP port 3629
- 16-byte handshake: client sends `ESC/VP.net\x10\x03\x00\x00\x00\x00`
- Projector echoes back the exact same 16 bytes
- After handshake, projector sends `:` prompt

### Command Format
- ASCII text commands terminated by `\r` (carriage return)
- Responses terminated by `\r\n` followed by `:` prompt
- Error responses: `ERR=XX` where XX is error code

### Known Commands
| Command | Description | Response |
|---------|-------------|----------|
| PWR ON | Power on | PWR=01 |
| PWR OFF | Power off | PWR=00 |
| PWR? | Query power state | PWR=XX (00=off,01=on,02=warmup,03=cooldown,04=standby,05=abnormal) |
| SOURCE XX | Set input source | SOURCE=XX |
| SOURCE? | Query input source | SOURCE=XX |
| MUTE ON/OFF | A/V mute | (no response body) |
| LAMP? | Query lamp hours | LAMP=XXXX YY (hours + status) |
| ERR? | Query error state | ERR=XX |
| SNO? | Query serial number | SNO=XXXXXXXXX |

### Input Source Codes
| Code | Source | Confirmed Models |
|------|--------|-----------------|
| 10 | VGA/Computer 1 | EB-series, EX-series |
| 11 | Computer 1 (alt) | Some PowerLite models |
| 20 | VGA/Computer 2 | EB-series |
| 21 | Computer 2 (alt) | Some PowerLite models |
| 30 | HDMI 1 | All modern models |
| 41 | Video (composite) | EB-series |
| 42 | S-Video | Older EB-series |
| 52 | USB | EB-series, EX-series |
| 53 | LAN/Wireless LAN | EB-series (iProjection) |
| 56 | Wireless HDMI | Newer models |
| A0 | HDMI 2 | Dual-HDMI models |

### Firmware Quirks
- Keep-alive required: some firmware drops TCP after ~30s idle. Send `PWR?\r` periodically.
- Some older firmware sends `\r:` instead of `\r\n:` (handle both).

## Screen Casting Protocol

### Discovery (mDNS/DNS-SD)

Service types:
- `_epson._tcp.local.` - Epson network projectors (iProjection/EasyMP)
- `_eshare._tcp.local.` - EShare wireless display receivers
- `_http._tcp.local.` - Generic HTTP devices (filtered by keywords)

TXT records for `_epson._tcp.local.`:
- `ty` - device type string (e.g., "Epson Projector")
- `vers` - firmware version
- `note` - description
- `usb` - USB availability flag

TXT records for `_eshare._tcp.local.`:
- `model` - model name
- `version` - firmware version
- `cap` - capabilities (comma-separated: `webcast`, `rtp`)

### Stream Transport

Pure **RTP over UDP** (not RTSP). No session negotiation handshake; the sender simply starts pushing RTP packets to the receiver's IP.

#### Video (port 5004)
- Codec: H.264 (Baseline/Main profile)
- RTP payload type: 96
- RTP packetization: `rtph264pay` with `config-interval=1` (SPS/PPS in every keyframe)
- Resolution: 1920×1080 (negotiable via caps)
- Framerate: 30fps
- Encoding: Hardware preferred (vaapih264enc, nvv4l2h264enc), software fallback (x264enc)
- Color space: I420

#### Audio (port 5006)
- Codec: Opus (preferred) or AAC (fallback)
- RTP payload type: 97
- Sample rate: 48000 Hz, stereo, F32LE input
- Opus bitrate: 128 kbps
- Source: PipeWire default audio monitor (captures all desktop audio)

### GStreamer Pipeline (complete)

Video branch:
```
pipewiresrc path={NODE_ID} do-timestamp=true !
video/x-raw,width=1920,height=1080,framerate=30/1 !
videoconvert ! videoscale ! videorate !
video/x-raw,format=I420 !
{encoder} !
h264parse !
rtph264pay config-interval=1 pt=96 !
udpsink host={TARGET_IP} port=5004 sync=false
```

Audio branch:
```
pipewiresrc do-timestamp=true !
audio/x-raw,format=F32LE,channels=2,rate=48000 !
audioconvert ! audioresample !
opusenc bitrate=128000 !
rtpopuspay pt=97 !
udpsink host={TARGET_IP} port=5006 sync=false
```

### Screen Capture (XDG Desktop Portal)

Uses `org.freedesktop.portal.ScreenCast` D-Bus interface:
1. CreateSession → session handle
2. SelectSources(types=1 for monitor, cursor_mode=2 for metadata)
3. Start → user permission dialog → streams list
4. Extract PipeWire node ID from first stream
5. Pass node ID to `pipewiresrc path={NODE_ID}`

Compatible with all major Wayland compositors:
- GNOME (xdg-desktop-portal-gnome)
- KDE Plasma (xdg-desktop-portal-kde)
- niri (xdg-desktop-portal-gnome or -wlr)
- Hyprland (xdg-desktop-portal-hyprland)
- Sway (xdg-desktop-portal-wlr)
