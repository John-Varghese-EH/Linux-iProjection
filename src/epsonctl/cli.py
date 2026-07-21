"""
epsonctl - Command Line Interface
"""

import argparse
import asyncio
import sys

from .client import ProjectorClient
from .discovery import discover_all
from .protocol import Power, Source


async def _discover(_args):
    print("Scanning for Epson projectors on the local network...")
    devices = await discover_all(mdns_timeout=3.0)
    if not devices:
        print("No projectors found.")
        return

    print(f"\\nFound {len(devices)} projector(s):")
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
            print(f"  Source:     {status.source.name}")
        if status.lamp_hours:
            print(f"  Lamp Hours: {status.lamp_hours}")
        if status.volume is not None:
            print(f"  Volume:     {status.volume}")
        if status.errors:
            print(f"  Errors:     {status.errors}")
        if status.mute is not None:
            print(f"  Mute:       {'Yes' if status.mute else 'No'}")


async def _power(args):
    async with ProjectorClient(args.ip, "eps") as client:
        state = Power.ON if args.state.lower() == "on" else Power.STANDBY
        await client.set_power(state)
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
    from .client import wake_on_lan
    success = wake_on_lan(args.mac)
    if success:
        print(f"Sent Wake-On-LAN magic packet to {args.mac}.")
    else:
        print(f"Failed to send Wake-On-LAN packet to {args.mac}.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="epsonctl",
        description="Native Linux control app for Epson projectors (ESC/VP.net + EShare)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Discover command
    subparsers.add_parser("discover", help="Scan the LAN for Epson projectors")

    # Status command
    status_parser = subparsers.add_parser("status", help="Get projector status")
    status_parser.add_argument("ip", help="IP address of the projector")

    # Power command
    power_parser = subparsers.add_parser("power", help="Turn projector on or off")
    power_parser.add_argument("state", choices=["on", "off"], help="Power state")
    power_parser.add_argument("ip", help="IP address of the projector")

    # Source command
    source_parser = subparsers.add_parser("source", help="Switch input source")
    source_parser.add_argument("source", help="Input source (e.g., HDMI1, VGA)")
    source_parser.add_argument("ip", help="IP address of the projector")

    # Volume command
    vol_parser = subparsers.add_parser("volume", help="Set projector volume")
    vol_parser.add_argument("level", type=int, help="Volume level (0-255)")
    vol_parser.add_argument("ip", help="IP address of the projector")

    # Wake on LAN command
    wake_parser = subparsers.add_parser("wake", help="Send Wake-On-LAN packet")
    wake_parser.add_argument("mac", help="MAC address of the projector")

    args = parser.parse_args()

    try:
        if args.command == "discover":
            asyncio.run(_discover(args))
        elif args.command == "status":
            asyncio.run(_status(args))
        elif args.command == "power":
            asyncio.run(_power(args))
        elif args.command == "source":
            asyncio.run(_source(args))
        elif args.command == "volume":
            asyncio.run(_volume(args))
        elif args.command == "wake":
            _wake(args)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
