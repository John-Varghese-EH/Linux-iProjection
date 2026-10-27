import tempfile
from pathlib import Path
from unittest import mock

from linux_iprojection.config import AppConfig, load_config, save_config


def test_app_config_defaults():
    config = AppConfig()
    assert config.polling_interval == 10
    assert config.auto_connect is False
    assert config.theme == "system"
    assert config.stream_quality == "balanced"
    assert config.connection_timeout == 5
    assert config.default_port == 3629
    assert config.pjlink_password == ""
    assert config.debug_mode is False


def test_config_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Mock get_config_dir to return our tmpdir
        with mock.patch("linux_iprojection.config.get_config_dir", return_value=tmp_path):
            # Create a modified config
            config = AppConfig(
                polling_interval=15,
                auto_connect=True,
                theme="dark",
                stream_quality="high_quality",
                connection_timeout=10,
                default_port=4352,
                pjlink_password="secret_password",
                debug_mode=True,
            )

            # Save it
            save_config(config)

            # Ensure it wrote to disk
            assert (tmp_path / "config.json").exists()

            # Load it back
            loaded = load_config()

            # Verify fields
            assert loaded.polling_interval == 15
            assert loaded.auto_connect is True
            assert loaded.theme == "dark"
            assert loaded.stream_quality == "high_quality"
            assert loaded.connection_timeout == 10
            assert loaded.default_port == 4352
            assert loaded.pjlink_password == "secret_password"
            assert loaded.debug_mode is True
            assert loaded.stream_codec == "h264"

            # Verify resilient loading with unexpected/deprecated keys
            import json
            with open(tmp_path / "config.json", "w") as f:
                json.dump({"polling_interval": 20, "unknown_future_field": "test"}, f)
            resilient_loaded = load_config()
            assert resilient_loaded.polling_interval == 20
            assert resilient_loaded.stream_codec == "h264"


def test_resolution_presets_and_config():
    from linux_iprojection.config import RESOLUTION_PRESETS

    assert "1080p" in RESOLUTION_PRESETS
    assert RESOLUTION_PRESETS["1080p"] == (1920, 1080)
    assert "wxga" in RESOLUTION_PRESETS
    assert RESOLUTION_PRESETS["wxga"] == (1280, 800)
    assert "720p" in RESOLUTION_PRESETS
    assert RESOLUTION_PRESETS["720p"] == (1280, 720)
    assert "xga" in RESOLUTION_PRESETS
    assert RESOLUTION_PRESETS["xga"] == (1024, 768)

    cfg = AppConfig(stream_resolution="wxga", stream_fps=60, stream_mtu=1400)
    assert cfg.stream_resolution == "wxga"
    assert cfg.stream_fps == 60
    assert cfg.stream_mtu == 1400


def test_device_store_passwords():
    from linux_iprojection.config import DeviceStore

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with mock.patch("linux_iprojection.config.get_config_dir", return_value=tmp_path):
            store = DeviceStore()
            # Initially empty
            assert store.get_password("192.168.1.150") == ""

            # Set password and retrieve
            store.set_password("192.168.1.150", "4321")
            assert store.get_password("192.168.1.150") == "4321"

            # Re-instantiate store from disk to verify persistence
            store2 = DeviceStore()
            assert store2.get_password("192.168.1.150") == "4321"


def test_device_store_load_status_and_resilience():
    from linux_iprojection.config import DeviceStore

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with mock.patch("linux_iprojection.config.get_config_dir", return_value=tmp_path):
            # 1. Non-existent file defaults to succeeded = True
            store = DeviceStore()
            assert store.last_load_succeeded is True
            assert store.load_succeeded is True

            # 2. Add device and save
            store.add_or_update_device("Projector 1", "192.168.1.50", 3629)
            assert store.last_load_succeeded is True

            # Reload succeeds
            store_loaded = DeviceStore()
            assert store_loaded.last_load_succeeded is True
            assert len(store_loaded.load_devices()) == 1

            # 3. Invalid / malformed JSON
            dev_file = tmp_path / "devices.json"
            dev_file.write_text("NOT_VALID_JSON{:::}")

            store_corrupt = DeviceStore()
            assert store_corrupt.last_load_succeeded is False
            assert store_corrupt.load_succeeded is False
            assert store_corrupt.load_devices() == []

            # 4. JSON that is not a dictionary (e.g. list)
            dev_file.write_text("[1, 2, 3]")
            store_non_dict = DeviceStore()
            assert store_non_dict.last_load_succeeded is False
            assert store_non_dict.load_devices() == []

            # 5. Clear all alias works
            dev_file.write_text('{"proj": {"name": "proj", "ip": "1.2.3.4", "port": 3629}}')
            store_clear = DeviceStore()
            assert store_clear.last_load_succeeded is True
            store_clear.clear_all()
            assert len(store_clear.devices) == 0


def test_populate_devices_suppresses_announcements_on_load_failure():
    from unittest.mock import MagicMock

    from linux_iprojection.app import MainWindow
    from linux_iprojection.discovery import DiscoveredDevice

    win = MagicMock(spec=MainWindow)
    win.device_list = MagicMock()
    win.device_list.get_row_at_index.return_value = None
    win.sidebar_stack = MagicMock()
    win._known_device_addrs = set()
    win.show_toast = MagicMock()

    mock_store = MagicMock()
    mock_store.load_devices.return_value = []
    mock_store.last_load_succeeded = False
    win._device_store = mock_store
    win._delete_device_row = MagicMock()

    devices = [
        DiscoveredDevice(name="Proj1", address="192.168.1.10", port=3629, source="udp")
    ]

    MainWindow._populate_devices(win, devices)

    # Toast must not announce new projector when persistence loading failed
    win.show_toast.assert_not_called()
    # Store saving must also be suppressed to prevent wiping existing data
    mock_store.save_devices.assert_not_called()

