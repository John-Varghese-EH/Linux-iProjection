"""
linux-iprojection - Configuration and logging management
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional

try:
    from gi.repository import GLib
except ImportError:

    class GLib:
        @staticmethod
        def get_user_config_dir():
            return os.path.expanduser("~/.config")


@dataclass
class AppConfig:
    polling_interval: int = 10
    default_source: Optional[str] = None
    auto_connect: bool = False
    theme: str = "system"
    stream_quality: str = "balanced"  # 'low_latency', 'balanced', 'high_quality'
    connection_timeout: int = 5
    default_port: int = 3629
    pjlink_password: str = ""
    debug_mode: bool = False


def get_config_dir() -> Path:
    config_dir = Path(GLib.get_user_config_dir()) / "linux-iprojection"
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_state_dir() -> Path:
    state_dir = Path(os.path.expanduser("~/.local/state/linux-iprojection"))
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def load_config() -> AppConfig:
    config_path = get_config_dir() / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return AppConfig(**data)
        except Exception as e:
            logging.error(f"Failed to load config, using defaults: {e}")
    return AppConfig()


def save_config(config: AppConfig) -> None:
    config_path = get_config_dir() / "config.json"
    try:
        with open(config_path, "w") as f:
            json.dump(asdict(config), f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")


class DeviceStore:
    def __init__(self):
        self.store_path = get_config_dir() / "devices.json"
        self.devices: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if self.store_path.exists():
            try:
                with open(self.store_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Failed to load device store: {e}")
        return {}

    def save(self):
        try:
            with open(self.store_path, "w") as f:
                json.dump(self.devices, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save device store: {e}")

    def add_or_update_device(self, name: str, ip: str, port: int, source_list: List[str] = None):
        self.devices[name] = {
            "name": name,
            "ip": ip,
            "port": port,
            "last_seen_sources": source_list or [],
        }
        self.save()

    def get_device(self, name: str) -> Optional[dict]:
        return self.devices.get(name)

    def get_all_devices(self) -> List[dict]:
        return list(self.devices.values())

    def load_devices(self) -> List[dict]:
        """Load devices as a plain list of dicts (for app.py compatibility)."""
        return self.get_all_devices()

    def save_devices(self, devices_list: List[dict]) -> None:
        """Save a list of device dicts, keyed by address."""
        self.devices = {}
        for d in devices_list:
            key = d.get("address", d.get("ip", d.get("name", "unknown")))
            self.devices[key] = d
        self.save()


def setup_logging(verbose: bool = False):
    log_level = logging.DEBUG if verbose else logging.INFO
    log_file = get_state_dir() / "linux-iprojection.log"

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=2)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logging.basicConfig(level=log_level, handlers=[file_handler, console_handler], force=True)
