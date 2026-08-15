"""
linux-iprojection command line interface.
"""

import argparse
import asyncio
import dataclasses
import json
import sys

from .cast import CastTarget, RtpUdpSink, ScreenCaster, TEST_PATTERNS
from .client import ProjectorClient, wake_on_lan
from .config import MacroStore
from .discovery import discover_all
from .pjlink import PJLinkController
from .protocol import (
    AspectRatio,
    ColorMode,
    KeystoneAxis,
    LuminanceMode,
    Source,
)


async def _discover(_args):
    print("Scanning for Epson projectors on the local network...")
    devices = await discover_all(mdns_timeout=3.0)
    if not devices:
        print("No projectors found.")
        return

    print(f"\nFound {len(devices)} projector(s):")
    for d in devices:
        name = d.name or "Unknown"
        alias = f" ({d.alias})" if d.alias else ""
        print(f"  - {d.address} : {name}{alias} [{d.device_type}]")


async def _status(args):
    async with ProjectorClient(args.ip, "eps") as client:
        status = await client.get_status()
        print(f"Status for {args.ip}:")
        print(f"  Power:      {'On' if status.power else 'Off'}")
        if status.source:
            source_str = status.source.name if hasattr(status.source, 'name') else str(status.source)
            print(f"  Source:     {source_str}")
        if status.lamp_hours is not None:
            print(f"  Lamp Hours: {status.lamp_hours}")
        if status.volume is not None:
            print(f"  Volume:     {status.volume}")
        if status.errors:
            print(f"  Errors:     {status.errors}")
        if status.mute is not None:
            print(f"  Mute:       {'Yes' if status.mute else 'No'}")


async def _power(args):
    async with ProjectorClient(args.ip, "eps") as client:
        if args.state.lower() == "on":
            await client.power_on()
        else:
            await client.power_off()
        print(f"Successfully turned {args.state} {args.ip}.")


async def _source(args):
    try:
        source_enum = Source[args.source.upper()]
    except KeyError:
        print(f"Invalid source '{args.source}'. Valid sources:")
        for s in Source:
            print(f"  {s.name}")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_source(source_enum)
        print(f"Successfully switched {args.ip} to {args.source.upper()}.")


async def _volume(args):
    if not (0 <= args.level <= 255):
        print("Volume level must be between 0 and 255.")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_volume(args.level)
        print(f"Successfully set {args.ip} volume to {args.level}.")


def _wake(args):
    success = wake_on_lan(args.mac)
    if success:
        print(f"Sent Wake-On-LAN magic packet to {args.mac}.")
    else:
        print(f"Failed to send Wake-On-LAN packet to {args.mac}.")
        sys.exit(1)


async def _mute(args):
    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_mute(args.state.lower() == "on")
        print(f"Successfully turned mute {args.state} on {args.ip}.")


async def _freeze(args):
    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_freeze(args.state.lower() == "on")
        print(f"Successfully turned freeze {args.state} on {args.ip}.")


async def _color_mode(args):
    try:
        mode_enum = ColorMode[args.mode.upper()]
    except KeyError:
        print(f"Invalid color mode '{args.mode}'. Valid modes:")
        for m in ColorMode:
            print(f"  {m.name}")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_color_mode(mode_enum)
        print(f"Successfully set {args.ip} color mode to {args.mode.upper()}.")


async def _aspect(args):
    try:
        ratio_enum = AspectRatio[args.ratio.upper()]
    except KeyError:
        print(f"Invalid aspect ratio '{args.ratio}'. Valid ratios:")
        for r in AspectRatio:
            print(f"  {r.name}")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_aspect_ratio(ratio_enum)
        print(f"Successfully set {args.ip} aspect ratio to {args.ratio.upper()}.")


async def _luminance(args):
    try:
        lum_enum = LuminanceMode[args.mode.upper()]
    except KeyError:
        print(f"Invalid luminance mode '{args.mode}'. Valid modes:")
        for m in LuminanceMode:
            print(f"  {m.name}")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_luminance_mode(lum_enum)
        print(f"Successfully set {args.ip} luminance mode to {args.mode.upper()}.")


async def _brightness(args):
    if not (0 <= args.level <= 255):
        print("Brightness level must be between 0 and 255.")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_brightness(args.level)
        print(f"Successfully set {args.ip} brightness to {args.level}.")


async def _contrast(args):
    if not (0 <= args.level <= 255):
        print("Contrast level must be between 0 and 255.")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_contrast(args.level)
        print(f"Successfully set {args.ip} contrast to {args.level}.")


async def _moderator(args):
    async with ProjectorClient(args.ip, "eps") as client:
        if not hasattr(client, "set_moderator_mode"):
            print("Moderator mode is not supported by this client layer.")
            sys.exit(1)
        await client.set_moderator_mode(args.state.lower() == "on")
        print(f"Successfully turned moderator mode {args.state} on {args.ip}.")


async def _whiteboard(args):
    async with ProjectorClient(args.ip, "eps") as client:
        if not hasattr(client, "set_whiteboard_sharing"):
            print("Whiteboard sharing is not supported by this client layer.")
            sys.exit(1)
        await client.set_whiteboard_sharing(args.state.lower() == "on")
        print(f"Successfully turned whiteboard sharing {args.state} on {args.ip}.")


async def _fcn(args):
    async with ProjectorClient(args.ip, "eps") as client:
        if not hasattr(client, "set_fcn"):
            print("FCN is not supported by this client layer.")
            sys.exit(1)
        await client.set_fcn(args.state.lower() == "on")
        print(f"Successfully turned FCN (Interactive Pen/Touch) {args.state} on {args.ip}.")


async def _encrypt(args):
    async with ProjectorClient(args.ip, "eps") as client:
        if not hasattr(client, "set_encryption"):
            print("Encryption is not supported by this client layer.")
            sys.exit(1)
        await client.set_encryption(args.mode.upper())
        print(f"Successfully set {args.ip} stream encryption to {args.mode.upper()}.")


async def _keystone(args):
    if not (-60 <= args.value <= 60):
        print("Keystone value must be between -60 and 60.")
        sys.exit(1)
        
    try:
        axis_enum = KeystoneAxis[args.axis.upper()]
    except KeyError:
        print(f"Invalid keystone axis '{args.axis}'. Valid axes:")
        for a in KeystoneAxis:
            print(f"  {a.name}")
        sys.exit(1)

    async with ProjectorClient(args.ip, "eps") as client:
        await client.set_keystone(axis_enum, args.value)
        print(f"Successfully set {args.ip} {args.axis.upper()} keystone to {args.value}.")


async def _raw(args):
    async with ProjectorClient(args.ip, "eps") as client:
        response = await client.send_command(args.command)
        print(f"Response: {response}")


async def _info(args):
    async with ProjectorClient(args.ip, "eps") as client:
        status = await client.get_status()
        print(f"Detailed Info for {args.ip}:")
        print(f"  Power:              {'On' if status.power else 'Off'}")
        if status.projector_name:
            print(f"  Projector Name:     {status.projector_name}")
        serial_val = getattr(status, "serial", getattr(status, "serial_number", ""))
        if serial_val:
            print(f"  Serial Number:      {serial_val}")
        if status.source:
            source_str = status.source.name if hasattr(status.source, "name") else str(status.source)
            print(f"  Source:             {source_str}")
        if getattr(status, "input_resolution", None):
            print(f"  Input Resolution:   {status.input_resolution}")
        if getattr(status, "signal_present", None) is not None:
            print(f"  Signal Present:     {'Yes' if status.signal_present else 'No'}")
        if status.lamp_hours is not None:
            print(f"  Lamp Hours:         {status.lamp_hours}")
        if getattr(status, "filter_hours", None) is not None:
            print(f"  Filter Hours:       {status.filter_hours}")
        if status.volume is not None:
            print(f"  Volume:             {status.volume}")
        if status.mute is not None:
            print(f"  Mute:               {'Yes' if status.mute else 'No'}")
        if getattr(status, "brightness", None) is not None:
            print(f"  Brightness:         {status.brightness}")
        if getattr(status, "contrast", None) is not None:
            print(f"  Contrast:           {status.contrast}")
        if getattr(status, "sharpness", None) is not None:
            print(f"  Sharpness:          {status.sharpness}")
        if getattr(status, "color_temp", None):
            print(f"  Color Temp:         {status.color_temp.name if hasattr(status.color_temp, 'name') else status.color_temp}")
        if status.errors:
            print("  Errors:")
            for k, v in status.errors.items():
                print(f"    - {k}: {v}")


async def _cast(args):
    """Start screen casting to the projector."""
    import signal

    if args.switch_source:
        print(f"Switching {args.ip} to LAN source...")
        try:
            async with ProjectorClient(args.ip, "eps") as client:
                await client.set_source(Source.LAN)
        except Exception as e:
            print(f"Warning: could not switch source: {e}")

    target = CastTarget(
        host=args.ip,
        port=args.video_port,
        audio_port=args.audio_port,
        name=args.ip,
    )
    caster = ScreenCaster(
        sink=RtpUdpSink(),
        audio_enabled=not args.no_audio,
        stream_quality=args.quality,
        on_stats=lambda s: None,
        on_error=lambda e: print(f"Stream error: {e}"),
    )

    print(f"Starting screen cast to {args.ip}:{args.video_port} (quality={args.quality})...")
    success = await caster.start(target)
    if not success:
        print("Failed to start casting (portal cancelled or pipeline error).")
        return

    print(f"Casting to {args.ip} — press Ctrl+C to stop.")

    stop_event = asyncio.Event()

    def _sigint(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _sigint)

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        caster.stop()
        print("Casting stopped.")


async def _test_pattern(args):
    """Send a test pattern to the projector for calibration."""
    target = CastTarget(host=args.ip, port=args.port, name="Test Pattern")
    caster = ScreenCaster(
        sink=RtpUdpSink(),
        stream_quality=args.quality,
        on_error=lambda e: print(f"Stream error: {e}"),
    )

    print(f"Starting test pattern '{args.pattern}' → {args.ip}:{args.port} ...")
    success = await caster.start_test_pattern(target, pattern=args.pattern)
    if not success:
        print("Failed to start test pattern.")
        return

    print("Test pattern streaming — press Ctrl+C to stop.")
    try:
        while caster.is_casting:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        caster.stop()
        print("Test pattern stopped.")


async def _pjlink(args):
    """Send a PJLink command to the projector."""
    async with PJLinkController(args.ip, port=args.port, password=args.password) as ctl:
        if args.value == "?" and args.command.upper() == "STATUS":
            status = await ctl.query_status()
            print(f"PJLink Status for {args.ip}:")
            print(f"  Power:        {status.power_label}")
            print(f"  Input:        {status.input_label} ({status.input_code})")
            print(f"  Lamp:         {status.lamp_hours} h ({'on' if status.lamp_on else 'off'})")
            print(f"  Name:         {status.name}")
            print(f"  Manufacturer: {status.manufacturer}")
            print(f"  Model:        {status.model}")
            print(f"  Class:        {status.pjlink_class}")
            if status.serial:
                print(f"  Serial:       {status.serial}")
            if status.errors:
                print(f"  Errors:       {', '.join(status.errors)}")
        else:
            resp = await ctl.send_raw(args.command, args.value)
            print(f"Response: {resp}")


async def _macro_run(args):
    store = MacroStore()
    macro = store.get_macro(args.name)
    if not macro:
        print(f"Macro '{args.name}' not found.")
        sys.exit(1)
        
    async with ProjectorClient(args.ip, "eps") as client:
        for step in macro.steps:
            print(f"Running step: {step.command} {step.args}")
            method = getattr(client, step.command, None)
            if method is None:
                print(f"  Warning: unknown command '{step.command}', skipping.")
                continue
            if step.args:
                await method(**step.args)
            else:
                await method()
            if step.delay_ms:
                await asyncio.sleep(step.delay_ms / 1000.0)


async def _macro_list(_args):
    store = MacroStore()
    macros = store.list_macros()
    if not macros:
        print("No macros found.")
        return
        
    print("Available macros:")
    for macro in macros:
        print(f"  - {macro.name}")


async def _export(args):
    async with ProjectorClient(args.ip, "eps") as client:
        status = await client.get_status()
        
        # Helper function to serialize Enums
        def default_serializer(obj):
            if hasattr(obj, "name"):
                return obj.name
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        data = json.dumps(dataclasses.asdict(status), indent=2, default=default_serializer)
        if args.file:
            with open(args.file, 'w') as f:
                f.write(data)
            print(f"Exported status to {args.file}.")
        else:
            print(data)


def main():
    ASCII_ART = r"""⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⣄⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⣠⣤⣤⣤⡀⠀⢀⣼⣿⣿⣿⣿⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⡄⢸⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢿⣿⣿⣿⣿⣿⠃⠘⢿⣿⣿⣿⣿⣿⣿⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠙⠛⠛⠛⠁⠀⠀⠀⠙⠛⠛⠛⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⡆⢰⣶⣶⣶⣶⣶⣶⣶⣶⣶⣶⣶⣶⣶⡆⠀⠀⠀⢀⣀⣤⠀⠀⠀⠀
⠀⠀⠀⠀⠁⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⢠⣴⣾⣿⣿⣿⠀⠀⠀⠀
⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠈⠉⠛⠿⣿⣿⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠈⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠁⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣿⢻⣟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣸⠃⣿⠈⢿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⡟⠀⣿⠀⠘⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢠⡿⠁⠀⣿⠀⠀⠘⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠚⠃⠀⠀⠛⠀⠀⠀⠙⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
Linux-iProjection: Native Linux control app for Epson projectors (ESC/VP.net + EShare)
Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""
    parser = argparse.ArgumentParser(
        prog="linux-iprojection",
        description=ASCII_ART,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Discover
    subparsers.add_parser("discover", help="Scan the LAN for Epson projectors")

    # Status
    status_parser = subparsers.add_parser("status", help="Get projector status")
    status_parser.add_argument("ip", help="IP address of the projector")

    # Power
    power_parser = subparsers.add_parser("power", help="Turn projector on or off")
    power_parser.add_argument("state", choices=["on", "off"], help="Power state")
    power_parser.add_argument("ip", help="IP address of the projector")

    # Source
    source_parser = subparsers.add_parser("source", help="Switch input source")
    source_parser.add_argument("source", help="Input source (e.g., HDMI1, VGA)")
    source_parser.add_argument("ip", help="IP address of the projector")

    # Volume
    vol_parser = subparsers.add_parser("volume", help="Set projector volume")
    vol_parser.add_argument("level", type=int, help="Volume level (0-255)")
    vol_parser.add_argument("ip", help="IP address of the projector")

    # Wake
    wake_parser = subparsers.add_parser("wake", help="Send Wake-On-LAN packet")
    wake_parser.add_argument("mac", help="MAC address of the projector")

    # Mute
    mute_parser = subparsers.add_parser("mute", help="Turn mute on or off")
    mute_parser.add_argument("state", choices=["on", "off"], help="Mute state")
    mute_parser.add_argument("ip", help="IP address of the projector")

    # Freeze
    freeze_parser = subparsers.add_parser("freeze", help="Turn freeze on or off")
    freeze_parser.add_argument("state", choices=["on", "off"], help="Freeze state")
    freeze_parser.add_argument("ip", help="IP address of the projector")

    # Color Mode
    color_mode_parser = subparsers.add_parser("color-mode", help="Set color mode")
    color_mode_parser.add_argument("mode", help="Color mode name")
    color_mode_parser.add_argument("ip", help="IP address of the projector")

    # Aspect
    aspect_parser = subparsers.add_parser("aspect", help="Set aspect ratio")
    aspect_parser.add_argument("ratio", help="Aspect ratio name")
    aspect_parser.add_argument("ip", help="IP address of the projector")

    # Luminance
    luminance_parser = subparsers.add_parser("luminance", help="Set luminance mode")
    luminance_parser.add_argument("mode", choices=["normal", "eco"], help="Luminance mode")
    luminance_parser.add_argument("ip", help="IP address of the projector")

    # Brightness
    bright_parser = subparsers.add_parser("brightness", help="Set brightness")
    bright_parser.add_argument("level", type=int, help="Brightness level (0-255)")
    bright_parser.add_argument("ip", help="IP address of the projector")

    # Contrast
    contrast_parser = subparsers.add_parser("contrast", help="Set contrast")
    contrast_parser.add_argument("level", type=int, help="Contrast level (0-255)")
    contrast_parser.add_argument("ip", help="IP address of the projector")

    # Keystone
    keystone_parser = subparsers.add_parser("keystone", help="Set keystone")
    keystone_parser.add_argument("axis", choices=["h", "v"], help="Keystone axis")
    keystone_parser.add_argument("value", type=int, help="Keystone value (-60 to 60)")
    keystone_parser.add_argument("ip", help="IP address of the projector")

    # Enterprise features
    mod_parser = subparsers.add_parser("moderator", help="Turn moderator mode on or off")
    mod_parser.add_argument("state", choices=["on", "off"], help="Moderator state")
    mod_parser.add_argument("ip", help="IP address of the projector")

    wb_parser = subparsers.add_parser("whiteboard", help="Turn whiteboard sharing on or off")
    wb_parser.add_argument("state", choices=["on", "off"], help="Whiteboard state")
    wb_parser.add_argument("ip", help="IP address of the projector")

    fcn_parser = subparsers.add_parser("fcn", help="Turn FCN (Interactive Pen/Touch) on or off")
    fcn_parser.add_argument("state", choices=["on", "off"], help="FCN state")
    fcn_parser.add_argument("ip", help="IP address of the projector")

    enc_parser = subparsers.add_parser("encrypt", help="Set stream encryption mode")
    enc_parser.add_argument("mode", choices=["off", "aes", "des", "aesepctr"], help="Encryption mode")
    enc_parser.add_argument("ip", help="IP address of the projector")

    # Raw
    raw_parser = subparsers.add_parser("raw", help="Send raw command")
    raw_parser.add_argument("command", help="Raw ESC/VP.net command")
    raw_parser.add_argument("ip", help="IP address of the projector")

    # Info
    info_parser = subparsers.add_parser("info", help="Get detailed diagnostic dump")
    info_parser.add_argument("ip", help="IP address of the projector")

    # Macro
    macro_parser = subparsers.add_parser("macro", help="Manage macros")
    macro_subparsers = macro_parser.add_subparsers(dest="macro_command", required=True)
    
    macro_run_parser = macro_subparsers.add_parser("run", help="Run a macro")
    macro_run_parser.add_argument("name", help="Macro name")
    macro_run_parser.add_argument("ip", help="IP address of the projector")
    
    macro_subparsers.add_parser("list", help="List macros")

    # Export
    export_parser = subparsers.add_parser("export", help="Export status to JSON")
    export_parser.add_argument("ip", help="IP address of the projector")
    export_parser.add_argument("file", nargs="?", help="Output JSON file (optional)")

    # Cast
    cast_parser = subparsers.add_parser("cast", help="Start screen casting to projector")
    cast_parser.add_argument("ip", help="IP address of the projector")
    cast_parser.add_argument("--video-port", type=int, default=5004, help="Video RTP port (default: 5004)")
    cast_parser.add_argument("--audio-port", type=int, default=5006, help="Audio RTP port (default: 5006)")
    cast_parser.add_argument("--no-audio", action="store_true", help="Disable audio streaming")
    cast_parser.add_argument("--quality", choices=["low_latency", "balanced", "high_quality"], default="balanced",
                             help="Stream quality preset")
    cast_parser.add_argument("--switch-source", action="store_true",
                             help="Automatically switch projector to LAN source before casting")

    # Test Pattern
    tp_parser = subparsers.add_parser("test-pattern", help="Send a test pattern to projector")
    tp_parser.add_argument("ip", help="IP address of the projector")
    tp_parser.add_argument("--pattern", choices=list(TEST_PATTERNS.keys()), default="smpte",
                           help="Test pattern name (default: smpte)")
    tp_parser.add_argument("--port", type=int, default=5004, help="Video RTP port (default: 5004)")
    tp_parser.add_argument("--quality", choices=["low_latency", "balanced", "high_quality"], default="balanced")

    # PJLink
    pjlink_parser = subparsers.add_parser("pjlink", help="Send PJLink commands")
    pjlink_parser.add_argument("ip", help="IP address of the projector")
    pjlink_parser.add_argument("command", help="PJLink command (e.g. POWR, INPT, AVMT, LAMP, ERST, NAME, INF1, INF2)")
    pjlink_parser.add_argument("value", nargs="?", default="?", help="Command value (default: ? for query)")
    pjlink_parser.add_argument("--password", default="", help="PJLink password")
    pjlink_parser.add_argument("--port", type=int, default=4352, help="PJLink port (default: 4352)")

    # Firewall
    subparsers.add_parser("firewall", help="Configure Linux firewall for iProjection ports")

    args = parser.parse_args()

    handlers = {
        "discover": _discover,
        "status": _status,
        "power": _power,
        "source": _source,
        "volume": _volume,
        "wake": _wake,
        "mute": _mute,
        "freeze": _freeze,
        "color-mode": _color_mode,
        "aspect": _aspect,
        "luminance": _luminance,
        "brightness": _brightness,
        "contrast": _contrast,
        "keystone": _keystone,
        "moderator": _moderator,
        "whiteboard": _whiteboard,
        "fcn": _fcn,
        "encrypt": _encrypt,
        "raw": _raw,
        "info": _info,
        "export": _export,
        "cast": _cast,
        "test-pattern": _test_pattern,
        "pjlink": _pjlink,
        "firewall": lambda a: __import__("linux_iprojection.firewall", fromlist=[""]).configure_firewall(),
    }

    try:
        if args.command == "macro":
            if args.macro_command == "run":
                asyncio.run(_macro_run(args))
            elif args.macro_command == "list":
                asyncio.run(_macro_list(args))
        elif args.command in handlers:
            handler = handlers[args.command]
            if asyncio.iscoroutinefunction(handler):
                asyncio.run(handler(args))
            else:
                handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
