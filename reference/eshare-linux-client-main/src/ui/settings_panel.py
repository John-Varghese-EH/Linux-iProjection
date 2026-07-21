"""
settings_panel.py - Stream Settings Panel (Adw.PreferencesGroup)
================================================================

Shown in the right-hand detail pane when a device is selected.
Exposes all tunable stream parameters and emits a ``settings_changed``
signal when any value changes so the pipeline can be updated.

Groups
------
  1. Video - resolution, frame rate, encoder, bitrate slider
  2. Audio - enable toggle, codec selector
  3. Advanced - manual IP entry, stream ports
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, GObject, Gtk  # type: ignore

from src.streaming.gstreamer_pipeline import EncoderPreset


# ── Settings dataclass ────────────────────────────────────────────────────────

class StreamSettings(GObject.Object):
    """
    Observable settings object.  Connect to ``notify::<property>`` for
    incremental updates, or read all fields at once as a plain dict via
    :meth:`as_dict`.
    """

    __gtype_name__ = "StreamSettings"

    width      = GObject.Property(type=int,  default=1920)
    height     = GObject.Property(type=int,  default=1080)
    fps        = GObject.Property(type=int,  default=30)
    bitrate    = GObject.Property(type=int,  default=4000)   # kbps
    encoder    = GObject.Property(type=str,  default="auto")
    audio      = GObject.Property(type=bool, default=True)
    audio_codec = GObject.Property(type=str, default="opus")
    video_port = GObject.Property(type=int,  default=5004)
    audio_port = GObject.Property(type=int,  default=5006)

    def as_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height,
            "fps": self.fps, "bitrate_kbps": self.bitrate,
            "encoder": EncoderPreset[self.encoder.upper()],
            "audio_enabled": self.audio,
            "video_port": self.video_port, "audio_port": self.audio_port,
        }


# ── Preset mappings ───────────────────────────────────────────────────────────

RESOLUTION_PRESETS = [
    ("1920 × 1080  (1080p)", 1920, 1080),
    ("1280 × 720   (720p)",  1280, 720),
    ("1024 × 768   (XGA)",   1024, 768),
    ("Native / Auto",        0,    0),
]

FPS_PRESETS  = [("60 fps", 60), ("30 fps", 30), ("15 fps", 15)]
ENC_PRESETS  = [
    ("Auto-detect",     "auto"),
    ("Intel VA-API",    "vaapi"),
    ("NVIDIA NVENC",    "nvenc"),
    ("Software (x264)", "software"),
]
AUDIO_CODECS = [("Opus (recommended)", "opus"), ("AAC", "aac")]


# ── Panel ─────────────────────────────────────────────────────────────────────

class SettingsPanel(Gtk.Box):
    """
    Vertical box containing Adw preference rows for all stream settings.

    Usage::

        panel = SettingsPanel()
        panel.settings.connect("notify", lambda *_: rebuild_pipeline())
        box.append(panel)
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.settings = StreamSettings()
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header
        header = Gtk.Label(label="Stream Settings")
        header.add_css_class("title-4")
        header.set_margin_start(12)
        header.set_margin_top(16)
        header.set_margin_bottom(8)
        header.set_halign(Gtk.Align.START)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_bottom(12)
        scroll.set_child(content)

        content.append(self._build_video_group())
        content.append(self._build_audio_group())
        content.append(self._build_advanced_group())

    def _build_video_group(self) -> Adw.PreferencesGroup:
        grp = Adw.PreferencesGroup(title="Video")

        # Resolution
        res_row = Adw.ComboRow(title="Resolution")
        res_model = Gtk.StringList()
        for label, *_ in RESOLUTION_PRESETS:
            res_model.append(label)
        res_row.set_model(res_model)
        res_row.set_selected(0)
        res_row.connect("notify::selected", self._on_resolution_changed)
        grp.add(res_row)

        # Frame rate
        fps_row = Adw.ComboRow(title="Frame Rate")
        fps_model = Gtk.StringList()
        for label, _ in FPS_PRESETS:
            fps_model.append(label)
        fps_row.set_model(fps_model)
        fps_row.set_selected(1)  # default 30 fps
        fps_row.connect("notify::selected", self._on_fps_changed)
        grp.add(fps_row)

        # Encoder
        enc_row = Adw.ComboRow(title="Encoder")
        enc_model = Gtk.StringList()
        for label, _ in ENC_PRESETS:
            enc_model.append(label)
        enc_row.set_model(enc_model)
        enc_row.set_selected(0)  # auto
        enc_row.connect("notify::selected", self._on_encoder_changed)
        grp.add(enc_row)

        # Bitrate slider
        bitrate_row = Adw.ActionRow(title="Bitrate", subtitle="2000 kbps")
        self._bitrate_subtitle_row = bitrate_row
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 500, 20000, 500)
        slider.set_value(4000)
        slider.set_hexpand(True)
        slider.set_valign(Gtk.Align.CENTER)
        slider.connect("value-changed", self._on_bitrate_changed)
        bitrate_row.add_suffix(slider)
        grp.add(bitrate_row)

        return grp

    def _build_audio_group(self) -> Adw.PreferencesGroup:
        grp = Adw.PreferencesGroup(title="Audio")

        # Enable toggle
        audio_row = Adw.SwitchRow(title="Include Audio", subtitle="Capture system audio")
        audio_row.set_active(True)
        audio_row.connect("notify::active", self._on_audio_toggled)
        grp.add(audio_row)

        # Codec selector
        codec_row = Adw.ComboRow(title="Audio Codec")
        codec_model = Gtk.StringList()
        for label, _ in AUDIO_CODECS:
            codec_model.append(label)
        codec_row.set_model(codec_model)
        codec_row.set_selected(0)
        codec_row.connect("notify::selected", self._on_audio_codec_changed)
        grp.add(codec_row)

        return grp

    def _build_advanced_group(self) -> Adw.PreferencesGroup:
        grp = Adw.PreferencesGroup(title="Advanced")

        # Video port
        vport_row = Adw.EntryRow(title="Video RTP Port")
        vport_row.set_text("5004")
        vport_row.connect("changed", lambda r: self._set_port("video_port", r.get_text()))
        grp.add(vport_row)

        # Audio port
        aport_row = Adw.EntryRow(title="Audio RTP Port")
        aport_row.set_text("5006")
        aport_row.connect("changed", lambda r: self._set_port("audio_port", r.get_text()))
        grp.add(aport_row)

        return grp

    # ── Signal handlers ───────────────────────────────────────────────────

    def _on_resolution_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        if idx < len(RESOLUTION_PRESETS):
            _, w, h = RESOLUTION_PRESETS[idx]
            self.settings.width  = w
            self.settings.height = h

    def _on_fps_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        if idx < len(FPS_PRESETS):
            self.settings.fps = FPS_PRESETS[idx][1]

    def _on_encoder_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        if idx < len(ENC_PRESETS):
            self.settings.encoder = ENC_PRESETS[idx][1]

    def _on_bitrate_changed(self, slider) -> None:
        val = int(slider.get_value())
        self.settings.bitrate = val
        self._bitrate_subtitle_row.set_subtitle(f"{val} kbps")

    def _on_audio_toggled(self, row, _pspec) -> None:
        self.settings.audio = row.get_active()

    def _on_audio_codec_changed(self, row, _pspec) -> None:
        idx = row.get_selected()
        if idx < len(AUDIO_CODECS):
            self.settings.audio_codec = AUDIO_CODECS[idx][1]

    def _set_port(self, attr: str, text: str) -> None:
        try:
            val = int(text)
            if 1024 <= val <= 65535:
                setattr(self.settings, attr, val)
        except ValueError:
            pass
