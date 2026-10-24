# Implementation Plan: Full Epson iProjection Protocol Reverse Engineering

## Goal Description
The objective is to completely reverse-engineer the proprietary streaming and signaling stack from the Windows `Epson iProjection` application (specifically the `EMP_PJCON.dll` and `WebRTCManager.dll` mechanisms) and implement a robust, feature-complete native Linux equivalent. This will replace the generic EShare/RTP streams with the authentic WebRTC-based encrypted streaming protocol used by modern Epson projectors.

## Current Findings & Reverse Engineering Status
From static analysis of the Windows binaries and your recent Python additions:
1. **Control & Discovery**: Your additions to `protocol.py` and `discovery.py` successfully implement the proprietary EEMP (UDP 3620) discovery and ESC/VP.net (TCP 3629) Enterprise commands (`MODERATOR ON`, `WBSHARE ON`, `FCN ON`, `ENCRYPT AESEPCTR`).
2. **Media Stack**: The Windows app relies heavily on `WebRTCManager.dll`. It uses standard WebRTC (ICE, DTLS, SRTP, H.264/VP8, Opus) to encapsulate the video/audio streams.
3. **The Missing Link**: While we know the stream is WebRTC and we can trigger encryption modes via ESC/VP.net, the actual **WebRTC Signaling Phase** (how the SDP Offer/Answer and ICE candidates are exchanged between the PC and the projector) is currently opaque. It is not transmitted over standard HTTP based on string analysis, suggesting a proprietary binary exchange over TCP 3629 or a secondary port.

> [!CAUTION]
> **User Review Required: Dynamic Analysis Traces Needed**
> Because the WebRTC signaling is compiled into C++ (`EMP_PJCON.dll`) and .NET (`EMP_MPP.exe`) binaries without source code, I cannot "guess" the exact byte structure of the signaling protocol just from strings. 
> 
> **To complete the reverse-engineering, I need network traffic.** Please run Wireshark (or tcpdump) while connecting the Windows iProjection app to the projector and starting a stream. Save the `.pcap` file in the workspace so I can parse the exact packets used to negotiate the WebRTC session.

## Proposed Changes & Execution Path

Once the PCAP is provided and the signaling handshake is identified, I will execute the following architecture changes:

### `src/linux_iprojection/signaling.py`
#### [NEW] `signaling.py`
- Create an asynchronous WebRTC signaling manager.
- Implement the exact handshake observed in the PCAP (parsing SDP offers/answers and ICE candidates).

### `src/linux_iprojection/cast.py`
#### [MODIFY] `cast.py`
- Refactor `ScreenCaster` to use `webrtcbin` instead of raw `udpsink` for target projectors that require WebRTC (detected via EEMP capability flags).
- Connect GStreamer's `webrtcbin` signals (`on-negotiation-needed`, `on-ice-candidate`) to the new `signaling.py` module.

### `src/linux_iprojection/protocol.py`
#### [MODIFY] `protocol.py`
- Add any new ESC/VP.net magic commands discovered in the PCAP trace that prepare the projector for the incoming WebRTC stream.

## Verification Plan
### Automated Tests
- Write `pytest` fixtures that mock the projector's WebRTC signaling responses to ensure our handshake implementation perfectly mimics the Windows client.
### Manual Verification
- Compile the updated Linux app and verify a successful, encrypted, low-latency screen cast to a physical Epson projector.
