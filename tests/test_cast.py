import pytest
from linux_iprojection.cast import (
    ScreenCaster,
    CastTarget,
    RtpUdpSink,
    JpegRtpSink,
    EncoderPreset,
    _probe_encoder,
)

def test_probe_encoder_auto():
    # Should return a string that is a valid element + config
    encoder_str = _probe_encoder(preset=EncoderPreset.AUTO)
    assert isinstance(encoder_str, str)
    assert "enc" in encoder_str

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
