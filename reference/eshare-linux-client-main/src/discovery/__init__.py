# discovery package
"""
Discovery backends for linux-iprojection.

Each backend runs in its own thread and calls a shared callback when a
device is found or lost::

    from src.discovery.mdns_scanner import MdnsScanner

    def on_found(device):
        print("Found:", device)

    def on_lost(ip, port):
        print("Lost:", ip, port)

    scanner = MdnsScanner(on_found=on_found, on_lost=on_lost)
    scanner.start()
    ...
    scanner.stop()
"""
from src.discovery.mdns_scanner import MdnsScanner
from src.discovery.ssdp_scanner import SsdpScanner
from src.discovery.network_scanner import NetworkScanner

__all__ = ["MdnsScanner", "SsdpScanner", "NetworkScanner"]
