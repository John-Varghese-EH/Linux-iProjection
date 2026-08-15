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
| VOL? | Query volume level | VOL=XX |
| VOL XX | Set volume (0-255) | (no response body) |
| FREEZE ON/OFF | Freeze/unfreeze image | (no response body) |
| BRIGHT XX | Set brightness (1-255) | (no response body) |
| CONTRAST XX | Set contrast (0-255) | (no response body) |
| CMODE XX | Set color mode | (no response body) |
| ASPECT XX | Set aspect ratio | (no response body) |
| LUMINANCE XX | Set eco mode (00=normal, 01=eco) | (no response body) |
| KEY XX | Simulate remote key press | (no response body) |
| HKEYSTONE XX | Horizontal keystone (-60 to 60) | (no response body) |
| VKEYSTONE XX | Vertical keystone (-60 to 60) | (no response body) |
| PNAME? | Query projector name | PNAME=string |
| SIGNAL? | Query signal status | SIGNAL=01 (present) / SIGNAL=00 (absent) |
| FILTER? | Query filter hours | FILTER=XXXX |

### Enterprise Commands (Reverse-engineered from EMP_PJCON.dll)
| Command | Description |
|---------|-------------|
| MODERATOR ON/OFF | Multi-PC moderator mode |
| WBSHARE ON/OFF | Whiteboard sharing |
| FCN ON/OFF | Forward Coordinates (interactive pen/touch) |
| ENCRYPT mode | Stream encryption (OFF, AES, DES, AESEPCTR) |

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
| F1 | iProjection virtual source 1 | All iProjection models |
| F2 | iProjection virtual source 2 | All iProjection models |

### Firmware Quirks
- Keep-alive required: some firmware drops TCP after ~30s idle. Send `PWR?\r` periodically.
- Some older firmware sends `\r:` instead of `\r\n:` (handle both).

## Discovery

### mDNS/DNS-SD

Service types:
- `_epson._tcp.local.` - Epson network projectors (iProjection/EasyMP)
- `_eshare._tcp.local.` - EShare wireless display receivers
- `_http._tcp.local.` - Generic HTTP devices (filtered by keywords)
- `_pjlink._tcp.local.` - PJLink-compatible projectors

### EEMP UDP Broadcast (Reverse-engineered from EMP_PJCON.dll / EMP_NMANG.dll)

Epson proprietary discovery protocol:
- Client broadcasts UDP packet on port **3620**
- Packet structure: `EEMP` (4 bytes) + `0100` (4 bytes version) + 56 bytes padding = 64 bytes total
- Projectors respond on port **3621** with their capabilities
- Response contains: magic bytes, projector name (ASCII), capability flags
- Capability flags at byte 16: bit 0 = JPEG rect, bit 1 = MPEG4-AVC, bit 2 = audio, bit 3 = AES

## Screen Casting Protocol

### Stream Transport

Pure **RTP over UDP** (not RTSP). No session negotiation handshake; the sender simply starts pushing RTP packets to the receiver's IP. Before streaming, the sender switches the projector to SOURCE 53 (LAN input).

#### Video (port 5004)
- Codec: H.264 (Baseline/Main profile)
- RTP payload type: 96
- RTP packetization: `rtph264pay` with `config-interval=1` (SPS/PPS in every keyframe)
- Resolution: 1920×1080 (negotiable via caps)
- Framerate: 30fps
- Pixel format: I420 (mandatory caps filter for encoder compatibility)
- Encoding: Hardware preferred (vaapih264enc, nvv4l2h264enc), software fallback (x264enc)

#### Audio (port 5006)
- Codec: Opus (preferred) or AAC (fallback)
- RTP payload type: 97
- Sample rate: 48000 Hz, stereo, S16LE
- Opus bitrate: 128 kbps
- Source: PipeWire (preferred) or PulseAudio monitor (fallback)

### GStreamer Pipeline

Video branch:
```
pipewiresrc path={NODE_ID} do-timestamp=true !
videoconvert ! videoscale ! videorate !
video/x-raw,format=I420,framerate=30/1 !
{encoder} !
h264parse !
rtph264pay config-interval=1 pt=96 !
udpsink host={TARGET_IP} port=5004 sync=false
```

Audio branch:
```
pipewiresrc do-timestamp=true !
audioconvert ! audioresample !
audio/x-raw,format=S16LE,channels=2,rate=48000 !
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

