#!/usr/bin/env python3
"""
mock_receiver.py — Local Mock Projection Receiver
==================================================

Simulates a network projector / EShare display for local development and
protocol testing WITHOUT requiring real hardware.

What it does
------------
1. Advertises itself via **mDNS** as both an Epson projector
   (_epson._tcp.local.) and an EShare display (_eshare._tcp.local.)
2. Runs an **ESC/VP.net mock control server** on TCP port 3629
   (responds to power, input-select, and status commands)
3. Runs an **RTP stream receiver** on UDP port 5004 (video) and 5006 (audio)
   and prints real-time statistics about received packets
4. Runs an **RTSP-like status HTTP server** on port 8554 so you can
   curl/browser-check receiver state

Usage
-----
    python tools/mock_receiver.py

    # Custom ports:
    python tools/mock_receiver.py --control-port 3629 --video-port 5004 \
                                   --audio-port 5006 --http-port 8554

    # Advertise as EShare only:
    python tools/mock_receiver.py --type eshare --name "MyMockDisplay"

Press Ctrl+C to stop all services cleanly.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

# zeroconf is a pure-Python dependency (pip install zeroconf)
try:
    from zeroconf import ServiceInfo, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False
    print("[WARN] zeroconf not installed — mDNS advertisement disabled.")
    print("       Run: pip install zeroconf")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mock_receiver")


# ──────────────────────────────────────────────────────────────────────────────
# Shared state (thread-safe via simple lock + dict)
# ──────────────────────────────────────────────────────────────────────────────

class ReceiverState:
    """Shared mutable state accessed by all server threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.power: str = "01"          # 01 = on, 00 = off, 02 = warming
        self.source: str = "30"         # 30 = network
        self.lamp_hours: int = 1234
        self.errors: str = "00"

        # Stream stats
        self.video_packets: int = 0
        self.audio_packets: int = 0
        self.video_bytes: int = 0
        self.audio_bytes: int = 0
        self.stream_start_time: Optional[float] = None
        self.last_video_seq: int = -1
        self.video_drops: int = 0

    def as_dict(self) -> dict:
        with self._lock:
            elapsed = (
                round(time.monotonic() - self.stream_start_time, 1)
                if self.stream_start_time else 0
            )
            return {
                "power": self.power,
                "source": self.source,
                "lamp_hours": self.lamp_hours,
                "stream_active": self.stream_start_time is not None,
                "stream_elapsed_s": elapsed,
                "video_packets": self.video_packets,
                "video_bytes": self.video_bytes,
                "video_drops": self.video_drops,
                "audio_packets": self.audio_packets,
                "audio_bytes": self.audio_bytes,
            }


STATE = ReceiverState()
STOP_EVENT = threading.Event()


# ──────────────────────────────────────────────────────────────────────────────
# mDNS Advertisement
# ──────────────────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Best-effort: find the LAN IP of this machine (not 127.x)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def advertise_mdns(
    name: str,
    device_type: str,
    control_port: int,
    video_port: int,
    local_ip: str,
) -> Optional["Zeroconf"]:
    """Register mDNS service records and return the Zeroconf instance."""
    if not HAS_ZEROCONF:
        return None

    zc = Zeroconf()
    services: list[ServiceInfo] = []
    ip_bytes = socket.inet_aton(local_ip)

    if device_type in ("epson", "both"):
        epson_info = ServiceInfo(
            type_="_epson._tcp.local.",
            name=f"{name}._epson._tcp.local.",
            addresses=[ip_bytes],
            port=control_port,
            properties={
                b"ty":   b"Epson Projector (Mock)",
                b"usb":  b"0",
                b"note": b"linux-iprojection mock receiver",
                b"vers": b"2.0",
            },
            server=f"{socket.gethostname()}.local.",
        )
        zc.register_service(epson_info)
        services.append(epson_info)
        log.info("mDNS: registered  %s._epson._tcp.local.  on %s:%d",
                 name, local_ip, control_port)

    if device_type in ("eshare", "both"):
        eshare_info = ServiceInfo(
            type_="_eshare._tcp.local.",
            name=f"{name}._eshare._tcp.local.",
            addresses=[ip_bytes],
            port=56789,
            properties={
                b"model":   b"MockDisplay-1080p",
                b"version": b"4.2",
                b"cap":     b"webcast,rtp",
            },
            server=f"{socket.gethostname()}.local.",
        )
        zc.register_service(eshare_info)
        services.append(eshare_info)
        log.info("mDNS: registered  %s._eshare._tcp.local.  on %s:%d",
                 name, local_ip, 56789)

    return zc


# ──────────────────────────────────────────────────────────────────────────────
# ESC/VP.net Control Server (TCP)
# ──────────────────────────────────────────────────────────────────────────────

ESCVPNET_HANDSHAKE = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"
ESCVPNET_ACK       = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"  # echo back


def handle_escvpnet_client(conn: socket.socket, addr: tuple) -> None:
    """Handle one ESC/VP.net TCP connection in its own thread."""
    peer = f"{addr[0]}:{addr[1]}"
    log.info("[ESC/VP.net] New connection from %s", peer)

    try:
        # ── Handshake ──────────────────────────────────────────────────────
        data = conn.recv(16)
        if not data.startswith(b"ESC/VP.net"):
            log.warning("[ESC/VP.net] Bad handshake from %s: %r", peer, data)
            return
        conn.sendall(ESCVPNET_ACK)
        log.info("[ESC/VP.net] Handshake OK with %s", peer)

        # ── Command loop ───────────────────────────────────────────────────
        buf = b""
        while not STOP_EVENT.is_set():
            chunk = conn.recv(256)
            if not chunk:
                break
            buf += chunk

            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                response = _process_escvpnet_command(cmd, peer)
                conn.sendall(response.encode() + b"\r\n")

    except (OSError, ConnectionResetError) as exc:
        log.debug("[ESC/VP.net] Connection closed (%s): %s", peer, exc)
    finally:
        conn.close()
        log.info("[ESC/VP.net] Disconnected %s", peer)


def _process_escvpnet_command(cmd: str, peer: str) -> str:
    """Parse one ESC/VP.net command and return the response string."""
    log.info("[ESC/VP.net] ← %s: %r", peer, cmd)

    with STATE._lock:
        # ── Power ──────────────────────────────────────────────────────────
        if cmd == "PWR ON":
            STATE.power = "01"
            return "PWR=01"
        if cmd == "PWR OFF":
            STATE.power = "00"
            return "PWR=00"
        if cmd in ("PWR?", "PWR ON?"):
            return f"PWR={STATE.power}"

        # ── Source / Input ─────────────────────────────────────────────────
        if cmd.startswith("SOURCE "):
            STATE.source = cmd.split()[1]
            return f"SOURCE={STATE.source}"
        if cmd == "SOURCE?":
            return f"SOURCE={STATE.source}"

        # ── Lamp / status ──────────────────────────────────────────────────
        if cmd == "LAMP?":
            return f"LAMP={STATE.lamp_hours} 01"   # hours + status (01=ok)
        if cmd == "ERR?":
            return f"ERR={STATE.errors}"
        if cmd == "SNO?":
            return "SNO=MOCK123456"
        if cmd == "INFO?":
            return (
                f"INFO=MOCK PWR={STATE.power} "
                f"SOURCE={STATE.source} "
                f"LAMP={STATE.lamp_hours}"
            )

    log.warning("[ESC/VP.net] Unknown command: %r", cmd)
    return "ERR=01"   # 01 = unrecognised command


def run_escvpnet_server(host: str, port: int) -> None:
    """Accept ESC/VP.net TCP connections until STOP_EVENT is set."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(5)
        srv.settimeout(1.0)
        log.info("[ESC/VP.net] Listening on %s:%d (TCP)", host, port)

        while not STOP_EVENT.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            t = threading.Thread(
                target=handle_escvpnet_client,
                args=(conn, addr),
                daemon=True,
            )
            t.start()

    log.info("[ESC/VP.net] Server stopped.")


# ──────────────────────────────────────────────────────────────────────────────
# RTP Stream Receiver (UDP)
# ──────────────────────────────────────────────────────────────────────────────

# RTP header is 12 bytes minimum:
#   0       1       2       3
#   V P X CC  M PT    Sequence Number
#   Timestamp
#   SSRC

def _parse_rtp_header(data: bytes) -> dict:
    """Parse minimal RTP fixed header fields. Returns dict or empty on error."""
    if len(data) < 12:
        return {}
    first_word, seq, ts, ssrc = struct.unpack("!BBHII", data[:12])
    version = (first_word >> 6) & 0x3
    payload_type = data[1] & 0x7F
    return {
        "version": version,
        "payload_type": payload_type,
        "seq": seq,
        "timestamp": ts,
        "ssrc": ssrc,
    }


def run_rtp_receiver(host: str, port: int, label: str, state_attr: str) -> None:
    """
    Listen on a UDP port and collect RTP stream statistics.

    :param host:        bind address
    :param port:        UDP port to listen on
    :param label:       'VIDEO' or 'AUDIO' (for log messages)
    :param state_attr:  'video' or 'audio' (prefix for STATE attributes)
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(1.0)
        log.info("[RTP/%s] Listening on %s:%d (UDP)", label, host, port)

        packets_attr = f"{state_attr}_packets"
        bytes_attr   = f"{state_attr}_bytes"
        last_seq     = -1
        log_interval = 50  # log a summary every N packets

        while not STOP_EVENT.is_set():
            try:
                data, addr = sock.recvfrom(65536)
            except socket.timeout:
                continue

            rtp = _parse_rtp_header(data)
            if not rtp or rtp.get("version") != 2:
                log.debug("[RTP/%s] Non-RTP or malformed packet from %s", label, addr)
                continue

            with STATE._lock:
                if STATE.stream_start_time is None:
                    STATE.stream_start_time = time.monotonic()
                    log.info("[RTP/%s] First packet received from %s — stream started!",
                             label, addr)

                setattr(STATE, packets_attr, getattr(STATE, packets_attr) + 1)
                setattr(STATE, bytes_attr,   getattr(STATE, bytes_attr) + len(data))

                if label == "VIDEO":
                    if last_seq >= 0:
                        gap = (rtp["seq"] - last_seq) & 0xFFFF
                        if gap > 1:
                            STATE.video_drops += gap - 1
                    last_seq = rtp["seq"]
                    pkt_count = STATE.video_packets

            if pkt_count % log_interval == 0:
                state_snap = STATE.as_dict()
                log.info(
                    "[RTP/%s] pkt=%d  bytes=%.1fKB  drops=%d  "
                    "PT=%d  SSRC=0x%08X  from=%s",
                    label,
                    state_snap[f"{state_attr}_packets"],
                    state_snap[f"{state_attr}_bytes"] / 1024,
                    state_snap.get("video_drops", 0),
                    rtp["payload_type"],
                    rtp["ssrc"],
                    addr,
                )

    log.info("[RTP/%s] Receiver stopped.", label)


# ──────────────────────────────────────────────────────────────────────────────
# HTTP Status Server
# ──────────────────────────────────────────────────────────────────────────────

class StatusHandler(BaseHTTPRequestHandler):
    """Tiny HTTP server that exposes receiver state as JSON."""

    def log_message(self, fmt, *args) -> None:  # suppress default access log
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/status"):
            body = json.dumps(STATE.as_dict(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/reset":
            with STATE._lock:
                STATE.video_packets = 0
                STATE.audio_packets = 0
                STATE.video_bytes = 0
                STATE.audio_bytes = 0
                STATE.video_drops = 0
                STATE.stream_start_time = None
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"reset": true}')
        else:
            self.send_response(404)
            self.end_headers()


def run_http_status_server(host: str, port: int) -> None:
    """Run a simple HTTP status API until STOP_EVENT is set."""
    server = HTTPServer((host, port), StatusHandler)
    server.timeout = 1.0
    log.info("[HTTP] Status API on http://%s:%d/status", host, port)

    while not STOP_EVENT.is_set():
        server.handle_request()

    log.info("[HTTP] Status server stopped.")


# ──────────────────────────────────────────────────────────────────────────────
# Console Stats Printer
# ──────────────────────────────────────────────────────────────────────────────

def run_stats_printer(interval: float = 5.0) -> None:
    """Print a periodic summary table to stdout."""
    while not STOP_EVENT.is_set():
        time.sleep(interval)
        if STOP_EVENT.is_set():
            break
        s = STATE.as_dict()
        elapsed = s["stream_elapsed_s"]
        if elapsed > 0:
            vbps = s["video_bytes"] * 8 / elapsed / 1_000_000
            abps = s["audio_bytes"] * 8 / elapsed / 1_000_000
        else:
            vbps = abps = 0.0

        print(
            f"\n┌─ Stream Stats ──────────────────────────────────┐\n"
            f"│  Video:  {s['video_packets']:>7} pkts  "
            f"{s['video_bytes']/1024:>8.1f} KB  {vbps:>5.2f} Mbps  "
            f"drops={s['video_drops']}\n"
            f"│  Audio:  {s['audio_packets']:>7} pkts  "
            f"{s['audio_bytes']/1024:>8.1f} KB  {abps:>5.2f} Mbps\n"
            f"│  Elapsed: {elapsed}s   Power={s['power']}   "
            f"Source={s['source']}\n"
            f"└────────────────────────────────────────────────┘"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mock projector/display receiver for linux-iprojection testing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--name",         default="MockProjector",
                   help="mDNS service name")
    p.add_argument("--type",         default="both",
                   choices=["epson", "eshare", "both"],
                   help="Device type to advertise via mDNS")
    p.add_argument("--bind",         default="0.0.0.0",
                   help="Network interface to bind servers to")
    p.add_argument("--control-port", type=int, default=3629,
                   help="ESC/VP.net TCP control port")
    p.add_argument("--video-port",   type=int, default=5004,
                   help="RTP video UDP port")
    p.add_argument("--audio-port",   type=int, default=5006,
                   help="RTP audio UDP port")
    p.add_argument("--http-port",    type=int, default=8554,
                   help="HTTP status API port")
    p.add_argument("--stats-interval", type=float, default=5.0,
                   help="Seconds between console stats printout")
    p.add_argument("--no-mdns",      action="store_true",
                   help="Disable mDNS advertisement")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    local_ip = get_local_ip()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║          linux-iprojection  —  Mock Receiver                 ║
╠══════════════════════════════════════════════════════════════╣
║  Name        : {args.name:<46}║
║  Type        : {args.type:<46}║
║  Local IP    : {local_ip:<46}║
║  Control TCP : {args.control_port:<46}║
║  Video UDP   : {args.video_port:<46}║
║  Audio UDP   : {args.audio_port:<46}║
║  Status HTTP : http://{local_ip}:{args.http_port}/status{'':<{23 - len(str(args.http_port)) - len(local_ip)}}║
╚══════════════════════════════════════════════════════════════╝
Press Ctrl+C to stop.
""")

    # ── mDNS ──────────────────────────────────────────────────────────────
    zc = None
    if not args.no_mdns:
        zc = advertise_mdns(
            name=args.name,
            device_type=args.type,
            control_port=args.control_port,
            video_port=args.video_port,
            local_ip=local_ip,
        )

    # ── Background threads ────────────────────────────────────────────────
    threads = [
        threading.Thread(
            target=run_escvpnet_server,
            args=(args.bind, args.control_port),
            name="escvpnet",
            daemon=True,
        ),
        threading.Thread(
            target=run_rtp_receiver,
            args=(args.bind, args.video_port, "VIDEO", "video"),
            name="rtp-video",
            daemon=True,
        ),
        threading.Thread(
            target=run_rtp_receiver,
            args=(args.bind, args.audio_port, "AUDIO", "audio"),
            name="rtp-audio",
            daemon=True,
        ),
        threading.Thread(
            target=run_http_status_server,
            args=(args.bind, args.http_port),
            name="http-status",
            daemon=True,
        ),
        threading.Thread(
            target=run_stats_printer,
            args=(args.stats_interval,),
            name="stats-printer",
            daemon=True,
        ),
    ]

    for t in threads:
        t.start()

    # ── Graceful shutdown on SIGINT/SIGTERM ────────────────────────────────
    def _shutdown(sig, frame) -> None:
        log.info("Shutdown signal received — stopping all services …")
        STOP_EVENT.set()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    STOP_EVENT.wait()   # block main thread until shutdown

    if zc:
        log.info("Unregistering mDNS services …")
        zc.close()

    log.info("Mock receiver stopped. Goodbye.")
    sys.exit(0)


if __name__ == "__main__":
    main()
