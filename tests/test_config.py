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

