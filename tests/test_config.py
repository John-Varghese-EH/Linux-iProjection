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
