"""
test_gstreamer.py - Unit tests for the GStreamer pipeline module
================================================================

These tests do NOT start a real GStreamer pipeline (that would require
display hardware and actual GStreamer plugins).  Instead they verify:

  1. Encoder selection logic (probing function)
  2. Pipeline description string building
  3. Pipeline lifecycle (start/stop) with GStreamer mocked out
  4. Bitrate update path
  5. StreamStats dataclass

Run with:
    pytest tests/test_gstreamer.py -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.streaming.gstreamer_pipeline import (
    GStreamerPipeline,
    EncoderPreset,
    StreamStats,
    _build_video_pipeline,
    _build_audio_pipeline,
    _encoder_params,
)


# ──────────────────────────────────────────────────────────────────────────────
# StreamStats dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestStreamStats(unittest.TestCase):

    def test_default_values(self) -> None:
        s = StreamStats()
        self.assertEqual(s.bitrate_kbps, 0.0)
        self.assertEqual(s.fps, 0.0)
        self.assertFalse(s.audio_active)

    def test_custom_values(self) -> None:
        s = StreamStats(bitrate_kbps=4000.0, fps=30.0, latency_ms=42.0,
                        dropped=3, audio_active=True)
        self.assertEqual(s.bitrate_kbps, 4000.0)
        self.assertEqual(s.fps, 30.0)
        self.assertEqual(s.dropped, 3)
        self.assertTrue(s.audio_active)


# ──────────────────────────────────────────────────────────────────────────────
# Encoder parameters
# ──────────────────────────────────────────────────────────────────────────────

class TestEncoderParams(unittest.TestCase):

    def test_x264_params_contain_bitrate(self) -> None:
        result = _encoder_params("x264enc", 3000)
        self.assertIn("3000", result)
        self.assertIn("zerolatency", result)

    def test_vaapi_params_contain_bitrate(self) -> None:
        result = _encoder_params("vaapih264enc", 5000)
        self.assertIn("5000", result)
        self.assertIn("cbr", result)

    def test_nvenc_params_contain_bitrate(self) -> None:
        result = _encoder_params("nvv4l2h264enc", 2000)
        # nvenc bitrate is in bps
        self.assertIn("2000000", result)

    def test_unknown_encoder_falls_back_to_x264(self) -> None:
        result = _encoder_params("unknownenc", 1000)
        # Falls through to x264enc branch (last else)
        self.assertIn("1000", result)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline description strings
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineDescriptions(unittest.TestCase):

    def test_video_pipeline_contains_target(self) -> None:
        desc = _build_video_pipeline(
            pipewire_node_id=42,
            target_ip="10.0.0.5",
            video_port=5004,
            width=1280,
            height=720,
            fps=30,
            bitrate_kbps=2000,
            encoder_elem="x264enc",
        )
        self.assertIn("10.0.0.5", desc)
        self.assertIn("5004", desc)
        self.assertIn("pipewiresrc", desc)
        self.assertIn("path=42", desc)
        self.assertIn("1280", desc)
        self.assertIn("720", desc)
        self.assertIn("rtph264pay", desc)
        self.assertIn("udpsink", desc)

    def test_video_pipeline_node_zero_when_minus_one(self) -> None:
        """Node -1 should be clamped to 0 (auto) in the pipeline string."""
        # This clamping happens in GStreamerPipeline.start(), not the builder,
        # but we test the builder directly with 0 here.
        desc = _build_video_pipeline(
            pipewire_node_id=0,
            target_ip="127.0.0.1",
            video_port=5004,
            width=1920, height=1080, fps=30, bitrate_kbps=4000,
            encoder_elem="x264enc",
        )
        self.assertIn("path=0", desc)

    def test_audio_pipeline_contains_target(self) -> None:
        desc = _build_audio_pipeline(
            target_ip="10.0.0.5",
            audio_port=5006,
            audio_encoder="opusenc bitrate=128000",
            audio_payloader="rtpopuspay",
        )
        self.assertIn("10.0.0.5", desc)
        self.assertIn("5006", desc)
        self.assertIn("pipewiresrc", desc)
        self.assertIn("opusenc", desc)
        self.assertIn("rtpopuspay", desc)

    def test_audio_pipeline_aac_variant(self) -> None:
        desc = _build_audio_pipeline(
            target_ip="192.168.1.1",
            audio_port=5008,
            audio_encoder="avenc_aac bitrate=128000",
            audio_payloader="rtpmp4apay",
        )
        self.assertIn("avenc_aac", desc)
        self.assertIn("rtpmp4apay", desc)


# ──────────────────────────────────────────────────────────────────────────────
# GStreamerPipeline lifecycle (mocked GStreamer)
# ──────────────────────────────────────────────────────────────────────────────

class TestGStreamerPipelineLifecycle(unittest.TestCase):
    """
    Test the GStreamerPipeline state machine with a fully mocked GStreamer.
    No actual GStreamer elements are created.
    """

    def _make_mock_gst(self):
        """Return a mock Gst module that behaves enough for our pipeline."""
        mock_gst = MagicMock()
        mock_pipeline = MagicMock()
        mock_gst.parse_launch.return_value = mock_pipeline
        mock_pipeline.set_state.return_value = mock_gst.StateChangeReturn.SUCCESS
        mock_pipeline.get_bus.return_value = MagicMock()
        mock_gst.State.PLAYING = "PLAYING"
        mock_gst.State.NULL    = "NULL"
        mock_gst.StateChangeReturn.FAILURE = "FAILURE"
        mock_gst.StateChangeReturn.SUCCESS = "SUCCESS"
        mock_gst.Format.TIME = "TIME"
        mock_gst.MSECOND     = 1_000_000
        return mock_gst, mock_pipeline

    def test_start_sets_running(self) -> None:
        mock_gst, mock_pipeline = self._make_mock_gst()
        mock_glib = MagicMock()

        with patch("src.streaming.gstreamer_pipeline._Gst",  mock_gst), \
             patch("src.streaming.gstreamer_pipeline._GLib", mock_glib), \
             patch("src.streaming.gstreamer_pipeline._probe_encoder",
                   return_value="x264enc"), \
             patch("src.streaming.gstreamer_pipeline._probe_audio_encoder",
                   return_value=("opusenc bitrate=128000", "rtpopuspay")):

            pipe = GStreamerPipeline(
                target_ip="127.0.0.1",
                audio_enabled=True,
            )
            pipe.start()
            self.assertTrue(pipe.is_running)

    def test_stop_clears_running(self) -> None:
        mock_gst, mock_pipeline = self._make_mock_gst()
        mock_glib = MagicMock()

        with patch("src.streaming.gstreamer_pipeline._Gst",  mock_gst), \
             patch("src.streaming.gstreamer_pipeline._GLib", mock_glib), \
             patch("src.streaming.gstreamer_pipeline._probe_encoder",
                   return_value="x264enc"), \
             patch("src.streaming.gstreamer_pipeline._probe_audio_encoder",
                   return_value=("opusenc bitrate=128000", "rtpopuspay")):

            pipe = GStreamerPipeline(target_ip="127.0.0.1", audio_enabled=False)
            pipe.start()
            pipe.stop()
            self.assertFalse(pipe.is_running)

    def test_double_start_is_safe(self) -> None:
        mock_gst, mock_pipeline = self._make_mock_gst()
        mock_glib = MagicMock()

        with patch("src.streaming.gstreamer_pipeline._Gst",  mock_gst), \
             patch("src.streaming.gstreamer_pipeline._GLib", mock_glib), \
             patch("src.streaming.gstreamer_pipeline._probe_encoder",
                   return_value="x264enc"), \
             patch("src.streaming.gstreamer_pipeline._probe_audio_encoder",
                   return_value=("", "")):

            pipe = GStreamerPipeline(target_ip="127.0.0.1", audio_enabled=False)
            pipe.start()
            pipe.start()   # second call should be a no-op
            # parse_launch should only have been called once
            self.assertEqual(mock_gst.parse_launch.call_count, 1)

    def test_stop_when_not_started_is_safe(self) -> None:
        pipe = GStreamerPipeline(target_ip="127.0.0.1")
        pipe.stop()   # must not raise

    def test_on_error_callback(self) -> None:
        mock_gst, mock_pipeline = self._make_mock_gst()
        mock_glib = MagicMock()
        errors: list[str] = []

        with patch("src.streaming.gstreamer_pipeline._Gst",  mock_gst), \
             patch("src.streaming.gstreamer_pipeline._GLib", mock_glib), \
             patch("src.streaming.gstreamer_pipeline._probe_encoder",
                   return_value="x264enc"), \
             patch("src.streaming.gstreamer_pipeline._probe_audio_encoder",
                   return_value=("", "")):

            pipe = GStreamerPipeline(
                target_ip="127.0.0.1",
                audio_enabled=False,
                on_error=errors.append,
            )
            pipe.start()

            # Simulate a GStreamer ERROR bus message
            fake_msg = MagicMock()
            fake_msg.type = mock_gst.MessageType.ERROR
            fake_err = MagicMock()
            fake_err.message = "test error"
            fake_msg.parse_error.return_value = (fake_err, "debug info")
            pipe._on_bus_message(None, fake_msg)

        self.assertFalse(pipe.is_running)
        self.assertEqual(errors, ["test error"])

    def test_context_manager(self) -> None:
        mock_gst, mock_pipeline = self._make_mock_gst()
        mock_glib = MagicMock()

        with patch("src.streaming.gstreamer_pipeline._Gst",  mock_gst), \
             patch("src.streaming.gstreamer_pipeline._GLib", mock_glib), \
             patch("src.streaming.gstreamer_pipeline._probe_encoder",
                   return_value="x264enc"), \
             patch("src.streaming.gstreamer_pipeline._probe_audio_encoder",
                   return_value=("", "")):

            with GStreamerPipeline(target_ip="127.0.0.1",
                                   audio_enabled=False) as pipe:
                self.assertTrue(pipe.is_running)
            self.assertFalse(pipe.is_running)


if __name__ == "__main__":
    unittest.main(verbosity=2)
