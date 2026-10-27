import unittest.mock as mock

import pytest

from linux_iprojection.cast import (
    CastTarget,
    EncoderPreset,
    EncoderUnavailableError,
    JpegRtpSink,
    RtpUdpSink,
    ScreenCaster,
    _probe_encoder,
    _probe_software_encoder,
)


def test_probe_encoder_auto():
    # Should return a usable H.264 encoder (a known element name), or raise a
    # clear error when no encoder is available in the environment.
    try:
        encoder_str = _probe_encoder(preset=EncoderPreset.AUTO)
    except EncoderUnavailableError:
        pytest.skip("No H.264 encoder available in this environment")

    known_encoders = {
        "x264enc",
        "openh264enc",
        "vah264enc",
        "vaapih264enc",
        "nvh264enc",
        "nvautogpuh264enc",
        "nvv4l2h264enc",
    }
    element_name = encoder_str.split(" ", 1)[0]
    assert element_name in known_encoders, f"unexpected encoder {element_name!r}"
    assert element_name.endswith("enc")


def test_probe_encoder_raises_when_no_encoder_available(monkeypatch):
    registry = mock.MagicMock()
    registry.lookup_feature.return_value = None
    monkeypatch.setattr("linux_iprojection.cast.Gst.Registry.get", lambda: registry)
    with pytest.raises(EncoderUnavailableError):
        _probe_encoder(preset=EncoderPreset.AUTO)


def test_probe_software_encoder_selects_verified_element(monkeypatch):
    # When x264enc is missing but openh264enc exists, the software probe must
    # return openh264enc rather than blindly returning a non-existent x264enc.
    registry = mock.MagicMock()

    def lookup(name):
        return name if name == "openh264enc" else None

    registry.lookup_feature.side_effect = lookup
    monkeypatch.setattr("linux_iprojection.cast.Gst.Registry.get", lambda: registry)

    encoder_str = _probe_software_encoder("balanced")
    assert encoder_str.startswith("openh264enc")


def test_probe_software_encoder_raises_when_none(monkeypatch):
    registry = mock.MagicMock()
    registry.lookup_feature.return_value = None
    monkeypatch.setattr("linux_iprojection.cast.Gst.Registry.get", lambda: registry)
    with pytest.raises(EncoderUnavailableError):
        _probe_software_encoder("balanced")


def test_probe_encoder_hw_preset_falls_back_to_software(monkeypatch):
    # A hardware preset (VAAPI/NVENC) with no matching encoder must fall back to
    # an available software encoder rather than raising.
    registry = mock.MagicMock()

    def lookup(name):
        return name if name == "openh264enc" else None

    registry.lookup_feature.side_effect = lookup
    monkeypatch.setattr("linux_iprojection.cast.Gst.Registry.get", lambda: registry)

    encoder_str = _probe_encoder(preset=EncoderPreset.VAAPI)
    assert encoder_str.startswith("openh264enc")


def test_stop_closes_only_own_portal_session(monkeypatch):
    # Regression: stop() must close only this caster's portal session, not a
    # shared/global one that another caster owns.
    closed = []
    monkeypatch.setattr("linux_iprojection.cast._close_session", lambda h: closed.append(h))

    caster1 = ScreenCaster(sink=RtpUdpSink())
    caster2 = ScreenCaster(sink=RtpUdpSink())
    caster1._portal_session_handle = "session-A"
    caster2._portal_session_handle = "session-B"

    caster1.stop()

    assert closed == ["session-A"]
    assert caster1._portal_session_handle is None
    assert caster2._portal_session_handle == "session-B"


@pytest.mark.asyncio
async def test_stop_during_portal_request_cancels_start(monkeypatch):
    # When the user stops casting while the portal prompt is pending, the
    # in-flight start() must not install/start the pipeline afterwards.
    caster = ScreenCaster(sink=RtpUdpSink())

    async def mock_portal(*args, **kwargs):
        caster.stop()
        return (42, "session-handle")

    monkeypatch.setattr("linux_iprojection.cast._request_portal_stream", mock_portal)
    monkeypatch.setattr("linux_iprojection.cast._close_session", lambda h: None)

    target = CastTarget(host="192.168.1.50", port=5004)
    success = await caster.start(target)

    assert success is False
    assert caster.is_casting is False


def test_build_pipeline_jpeg_skips_h264_probe(monkeypatch):
    def fail_probe(*a, **k):
        raise AssertionError("H.264 encoder must not be probed for a JPEG sink")

    monkeypatch.setattr("linux_iprojection.cast._probe_encoder", fail_probe)
    caster = ScreenCaster(sink=JpegRtpSink(), audio_enabled=False)
    target = CastTarget(host="192.168.1.50", port=5004)
    pipeline = caster._build_pipeline(target, node_id=12, is_file=False)
    assert "jpegenc" in pipeline
    assert "h264parse" not in pipeline

def test_rtp_udp_sink_bin():
    target = CastTarget(host="192.168.1.10", port=5004)
    sink = RtpUdpSink()
    bin_str = sink.build_sink_bin(target)
    assert "udpsink host=192.168.1.10 port=5004" in bin_str
    assert "rtph264pay" in bin_str

def test_jpeg_rtp_sink_bin():
    target = CastTarget(host="192.168.1.10", port=5004)
    sink = JpegRtpSink()
    bin_str = sink.build_sink_bin(target)
    assert "udpsink host=192.168.1.10 port=5004" in bin_str
    assert "jpegenc" in bin_str
    assert "rtpjpegpay" in bin_str

def test_screencaster_init():
    caster = ScreenCaster(sink=RtpUdpSink())
    assert caster.sink is not None
    assert caster.is_casting is False
    assert caster.last_error is None
    assert caster.user_cancelled is False


def test_build_pipeline_pipewire(monkeypatch):
    monkeypatch.setattr(
        "linux_iprojection.cast._probe_encoder",
        lambda *a, **k: "x264enc bitrate=4000",
    )
    caster = ScreenCaster(sink=RtpUdpSink(), audio_enabled=False)
    target = CastTarget(host="192.168.1.50", port=5004)
    pipeline = caster._build_pipeline(target, node_id=42, is_file=False)
    assert "pipewiresrc path=42" in pipeline
    assert "udpsink host=192.168.1.50 port=5004" in pipeline


def test_build_pipeline_ximagesrc_fallback(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(
        "linux_iprojection.cast._probe_encoder",
        lambda *a, **k: "x264enc bitrate=4000",
    )
    caster = ScreenCaster(sink=RtpUdpSink(), audio_enabled=False)
    target = CastTarget(host="192.168.1.50", port=5004)
    pipeline = caster._build_pipeline(target, node_id=None, is_file=False)
    assert "ximagesrc" in pipeline


def test_build_pipeline_jpeg_sink(monkeypatch):
    monkeypatch.setattr(
        "linux_iprojection.cast._probe_encoder",
        lambda *a, **k: "x264enc bitrate=4000",
    )
    caster = ScreenCaster(sink=JpegRtpSink(), audio_enabled=False)
    target = CastTarget(host="192.168.1.50", port=5004)
    pipeline = caster._build_pipeline(target, node_id=12, is_file=False)
    assert "pipewiresrc path=12" in pipeline
    assert "jpegenc" in pipeline
    assert "rtpjpegpay" in pipeline
    assert "h264parse" not in pipeline


def test_build_pipeline_encoder_override_uses_provided_encoder(monkeypatch):
    # Regression: the software fallback must use a verified-available encoder
    # (encoder_override), never a hard-coded element that may be missing.
    monkeypatch.setenv("DISPLAY", ":0")
    caster = ScreenCaster(sink=RtpUdpSink(), audio_enabled=False)
    target = CastTarget(host="192.168.1.50", port=5004)
    override = "openh264enc bitrate=4000000"
    pipeline = caster._build_pipeline(
        target, node_id=42, is_file=False, encoder_override=override
    )
    assert override in pipeline


@pytest.mark.asyncio
async def test_screencaster_user_cancelled(monkeypatch):
    from linux_iprojection.cast import UserCancelledError

    async def mock_portal(*args, **kwargs):
        raise UserCancelledError("User dismissed dialog")

    monkeypatch.setattr("linux_iprojection.cast._request_portal_stream", mock_portal)
    caster = ScreenCaster(sink=RtpUdpSink())
    target = CastTarget(host="192.168.1.50", port=5004)

    success = await caster.start(target)
    assert success is False
    assert caster.user_cancelled is True
    assert "cancelled by user" in caster.last_error.lower()


@pytest.mark.asyncio
async def test_screencaster_x11_fallback_on_portal_error(monkeypatch):
    from linux_iprojection.cast import PortalError

    async def mock_portal(*args, **kwargs):
        raise PortalError("No backend for ScreenCast")

    monkeypatch.setattr("linux_iprojection.cast._request_portal_stream", mock_portal)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    monkeypatch.setattr(
        "linux_iprojection.cast._probe_encoder",
        lambda *a, **k: "x264enc bitrate=4000",
    )
    monkeypatch.setattr(
        "linux_iprojection.cast._probe_audio_encoder",
        lambda *a, **k: ("", ""),
    )

    mock_pipeline = mock.MagicMock()
    mock_pipeline.set_state.return_value = 1  # Gst.StateChangeReturn.SUCCESS = 1
    mock_pipeline.get_bus.return_value = mock.MagicMock()

    monkeypatch.setattr("gi.repository.Gst.parse_launch", lambda pipe: mock_pipeline)

    caster = ScreenCaster(sink=RtpUdpSink())
    target = CastTarget(host="192.168.1.50", port=5004)

    success = await caster.start(target)
    assert success is True
    assert caster.is_casting is True
    assert caster.user_cancelled is False
    caster.stop()


def test_rtp_udp_sink_enterprise_buffer_and_mtu():
    target = CastTarget(host="192.168.1.10", port=5004)
    sink = RtpUdpSink(mtu=1400, buffer_size=524288)
    bin_str = sink.build_sink_bin(target)
    assert "mtu=1400" in bin_str
    assert "buffer-size=524288" in bin_str


def test_jpeg_rtp_sink_enterprise_buffer_and_mtu():
    target = CastTarget(host="192.168.1.10", port=5004)
    sink = JpegRtpSink(mtu=1400, buffer_size=524288)
    bin_str = sink.build_sink_bin(target)
    assert "mtu=1400" in bin_str
    assert "buffer-size=524288" in bin_str


def test_build_pipeline_custom_resolution(monkeypatch):
    monkeypatch.setattr(
        "linux_iprojection.cast._probe_encoder",
        lambda *a, **k: "x264enc bitrate=4000",
    )
    caster = ScreenCaster(sink=RtpUdpSink(), audio_enabled=False)
    # Test WXGA 1280x800 @ 60fps
    target = CastTarget(
        host="192.168.1.50",
        port=5004,
        width=1280,
        height=800,
        fps=60,
    )
    pipeline = caster._build_pipeline(target, node_id=15, is_file=False)
    assert "video/x-raw,width=1280,height=800,framerate=60/1" in pipeline


@pytest.mark.asyncio
async def test_prepare_projector_for_stream_with_password():
    caster = ScreenCaster(sink=RtpUdpSink())
    target = CastTarget(
        host="192.168.1.99",
        port=5004,
        password="4321",
    )

    mock_client = mock.AsyncMock()
    mock_client.get_power.return_value = "04"  # Standby
    mock_client.power_on = mock.AsyncMock()
    mock_client.set_source = mock.AsyncMock()

    class MockContextManager:
        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with mock.patch("linux_iprojection.protocol.EscVpNetClient", return_value=MockContextManager()) as mock_cls:
        await caster._prepare_projector_for_stream(target)
        mock_cls.assert_called_with("192.168.1.99", password="4321")
        mock_client.power_on.assert_awaited_once()
        mock_client.set_source.assert_awaited_once()


