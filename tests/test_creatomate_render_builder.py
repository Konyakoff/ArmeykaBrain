"""Юнит-тесты для creatomate_render_builder.build_render_script."""
from __future__ import annotations

import pytest

from app.services.creatomate_render_builder import (
    build_render_script,
    FORMAT_PRESETS,
    SUBTITLE_PRESETS,
    DEFAULT_PRESET,
)


VIDEO = "https://example.com/video.mp4"


def _find(elements: list[dict], etype: str, name: str | None = None) -> list[dict]:
    out = [e for e in elements if e.get("type") == etype]
    if name:
        out = [e for e in out if e.get("name") == name]
    return out


def test_minimal_vertical_9_16():
    rs = build_render_script(video_url=VIDEO)
    assert rs["output_format"] == "mp4"
    assert rs["width"] == 1080 and rs["height"] == 1920
    assert rs["frame_rate"] == 30
    elems = rs["elements"]
    main = _find(elems, "video", "main")
    assert len(main) == 1
    assert main[0]["source"] == VIDEO
    assert main[0]["audio_volume"] == "100%"


def test_horizontal_16_9_60fps():
    rs = build_render_script(video_url=VIDEO, video_format="16:9", fps=60)
    assert rs["width"] == 1920 and rs["height"] == 1080
    assert rs["frame_rate"] == 60


def test_invalid_fps_normalized():
    rs = build_render_script(video_url=VIDEO, fps=99)
    assert rs["frame_rate"] == 30


def test_invalid_format_falls_back():
    rs = build_render_script(video_url=VIDEO, video_format="weird")
    assert rs["width"] == FORMAT_PRESETS["9:16"]["width"]


def test_subtitle_element_uses_transcript_source():
    rs = build_render_script(video_url=VIDEO, subtitle_preset="hormozi_white")
    subs = _find(rs["elements"], "text", "subtitles")
    assert len(subs) == 1
    s = subs[0]
    assert s["transcript_source"] == "main"
    assert s["transcript_effect"] == "karaoke"
    assert s["transcript_split"] == "word"
    assert s["transcript_color"] == SUBTITLE_PRESETS["hormozi_white"]["transcript_color"]


@pytest.mark.parametrize("preset_key", list(SUBTITLE_PRESETS.keys()))
def test_all_subtitle_presets(preset_key):
    rs = build_render_script(video_url=VIDEO, subtitle_preset=preset_key)
    subs = _find(rs["elements"], "text", "subtitles")
    assert subs and subs[0]["font_family"] == SUBTITLE_PRESETS[preset_key]["font_family"]


def test_invalid_preset_falls_back():
    rs = build_render_script(video_url=VIDEO, subtitle_preset="nonsense")
    subs = _find(rs["elements"], "text", "subtitles")
    assert subs[0]["font_family"] == SUBTITLE_PRESETS[DEFAULT_PRESET]["font_family"]


def test_invalid_transcript_effect_normalized():
    rs = build_render_script(video_url=VIDEO, transcript_effect="weird")
    subs = _find(rs["elements"], "text", "subtitles")
    assert subs[0]["transcript_effect"] == "karaoke"


def test_music_element_added():
    rs = build_render_script(video_url=VIDEO, music_url="https://m.mp3", music_volume_pct=30)
    music = _find(rs["elements"], "audio", "background_music")
    assert len(music) == 1
    assert music[0]["audio_volume"] == "30%"
    assert music[0]["loop"] is True


def test_no_music_by_default():
    rs = build_render_script(video_url=VIDEO)
    assert _find(rs["elements"], "audio") == []


def test_broll_clips_added_to_track3():
    """B-roll размещаются на track 3 (выше main_focus на 2 и main на 1)."""
    clips = [
        {"source": "https://b1.mp4", "time": 5, "duration": 4},
        {"source": "https://b2.mp4", "time": 12, "duration": 5},
    ]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips)
    brolls = [e for e in rs["elements"] if e.get("type") == "video" and e.get("name", "").startswith("broll_")]
    assert len(brolls) == 2
    assert all(b["track"] == 3 for b in brolls)
    assert all(b["audio_volume"] == "0%" for b in brolls)
    assert brolls[0]["time"] == 5 and brolls[0]["duration"] == 4


def test_broll_skips_empty_source():
    clips = [{"time": 0, "duration": 3}]  # no source
    rs = build_render_script(video_url=VIDEO, broll_clips=clips)
    brolls = [e for e in rs["elements"] if e.get("name", "").startswith("broll_")]
    assert brolls == []


def test_broll_animations_no_negative_time():
    """Все анимационные time в B-roll должны быть >= 0."""
    clips = [{"source": "https://b.mp4", "time": 2, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips)
    broll = next(e for e in rs["elements"] if e.get("name", "").startswith("broll_"))
    for anim in broll.get("animations", []):
        assert anim["time"] >= 0, f"Negative animation time: {anim}"


def test_broll_layout_pip():
    """PIP-режим: B-roll элемент должен иметь width < 100% и координаты угла."""
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout="pip")
    broll = next(e for e in rs["elements"] if e.get("name", "").startswith("broll_"))
    assert "width" in broll
    assert broll["width"] not in ("100%", None)
    assert "x" in broll
    assert "border_radius" in broll
    # Основное видео не сужается в PIP-режиме
    main = next(e for e in rs["elements"] if e.get("name") == "main")
    assert "width" not in main or main.get("width") == "100%"


def test_broll_layout_split():
    """Split-режим (исправленный):
    - main: полный кадр (track 1)
    - main_focus: только левые 50% (track 2), x=0%, fit:cover центрирует спикера
    - B-roll: правые 50% (track 3)
    - blend gradient: визуальный шов без mask_mode (track 4)
    """
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout="split")
    main = next(e for e in rs["elements"] if e.get("name") == "main")
    main_focus = next((e for e in rs["elements"] if e.get("name", "").startswith("main_focus_")), None)
    broll = next(e for e in rs["elements"] if e.get("name", "").startswith("broll_") and not e.get("name", "").startswith("broll_mask_"))
    blend = next((e for e in rs["elements"] if e.get("name", "").startswith("broll_mask_")), None)

    # Main НЕ сужается — полный кадр (нет явного width)
    assert "width" not in main

    # main_focus: track 2, ограничен ЛЕВОЙ половиной (width=50%, x=0%)
    assert main_focus is not None
    assert main_focus.get("track") == 2
    assert main_focus.get("source") == VIDEO
    assert main_focus.get("x") == "0%"
    assert main_focus.get("width") == "50%"   # только левая половина
    assert main_focus.get("trim_start") == 5
    assert main_focus.get("trim_duration") == 4
    assert main_focus.get("audio_volume") == "0%"
    for anim in main_focus.get("animations", []):
        assert anim["time"] >= 0

    # B-roll: track 3, правая половина
    assert broll.get("track") == 3
    assert broll.get("width") == "50%"
    assert broll.get("x") == "75%"

    # Blend gradient: track 4, НЕТ mask_mode (исправление — alpha-маска делала B-roll невидимым)
    assert blend is not None
    assert blend.get("track") == 4
    assert "mask_mode" not in blend, "mask_mode нельзя — делает B-roll невидимым"
    assert blend.get("x") == "50%"   # у шва
    assert blend.get("time") == 5
    assert blend.get("duration") == 4
    # Цветовые точки используют "offset"
    fill = blend.get("fill_color", [])
    assert len(fill) > 0
    for stop in fill:
        assert "offset" in stop
        assert "position" not in stop
    for anim in blend.get("animations", []):
        assert anim["time"] >= 0


def test_broll_layout_split_no_old_divider():
    """Старые divider/feather-mask элементы не должны присутствовать."""
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout="split")
    dividers = [e for e in rs["elements"] if e.get("name", "").startswith("divider_")]
    assert dividers == []
    # Проверяем что нет mask_mode ни в каком элементе
    masked = [e for e in rs["elements"] if "mask_mode" in e]
    assert masked == [], "mask_mode не используется — alpha-маска делала B-roll невидимым"


def test_broll_layout_overlay_no_split_extras():
    """В overlay/pip режимах НЕ должно быть main_focus и blend gradient."""
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    for layout in ("overlay", "pip"):
        rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout=layout)
        main_focus = [e for e in rs["elements"] if e.get("name", "").startswith("main_focus_")]
        blends = [e for e in rs["elements"] if e.get("name", "").startswith("broll_mask_")]
        assert main_focus == [], f"main_focus не должен присутствовать в {layout}"
        assert blends == [], f"broll_mask не должен присутствовать в {layout}"


def test_broll_layout_overlay_default():
    """Overlay (default): B-roll и main — без изменения размеров (100%)."""
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout="overlay")
    main = next(e for e in rs["elements"] if e.get("name") == "main")
    broll = next(e for e in rs["elements"] if e.get("name", "").startswith("broll_"))
    assert "width" not in main  # полный кадр (нет явного width)
    assert "x" not in broll    # полный кадр (нет явного x)


def test_broll_layout_invalid_falls_back_to_overlay():
    """Невалидный layout должен вернуться к overlay."""
    clips = [{"source": "https://b.mp4", "time": 5, "duration": 4}]
    rs = build_render_script(video_url=VIDEO, broll_clips=clips, broll_layout="unknown_mode")
    broll = next(e for e in rs["elements"] if e.get("name", "").startswith("broll_"))
    assert "x" not in broll  # overlay — без позиционирования


def test_intro_outro_with_text():
    rs = build_render_script(
        video_url=VIDEO,
        duration_sec=45.0,
        intro_text="HELLO", intro_duration=2.0,
        outro_text="BYE",   outro_duration=2.5,
    )
    intros = [e for e in rs["elements"] if e.get("name", "").startswith("intro_")]
    outros = [e for e in rs["elements"] if e.get("name", "").startswith("outro_")]
    assert any(e.get("text") == "HELLO" for e in intros)
    assert any(e.get("text") == "BYE" for e in outros)
    # Outro должен иметь неотрицательный time
    for el in outros:
        assert el.get("time", 0) >= 0
    # Outro должен начинаться в конце видео
    outro_time = outros[0]["time"]
    assert outro_time == pytest.approx(45.0 - 2.5, abs=0.1)


def test_outro_skipped_without_duration():
    """Без duration_sec outro не добавляется (нельзя позиционировать)."""
    rs = build_render_script(
        video_url=VIDEO,
        outro_text="BYE", outro_duration=2.5,
        # duration_sec намеренно не передан
    )
    outros = [e for e in rs["elements"] if e.get("name", "").startswith("outro_")]
    assert outros == []


def test_watermark_position():
    rs = build_render_script(video_url=VIDEO, watermark_url="https://logo.png", watermark_position="bottom-left")
    wm = _find(rs["elements"], "image", "watermark")
    assert len(wm) == 1
    assert wm[0]["x"] == "8%" and wm[0]["y"] == "92%"


def test_color_filter_applied_to_main_video():
    rs = build_render_script(video_url=VIDEO, color_filter="contrast", color_filter_value="40%")
    main = _find(rs["elements"], "video", "main")[0]
    assert main["color_filter"] == "contrast"
    assert main["color_filter_value"] == "40%"


def test_duration_propagates():
    rs = build_render_script(video_url=VIDEO, duration_sec=42.5)
    assert rs["duration"] == 42.5
    main = _find(rs["elements"], "video", "main")[0]
    assert main["duration"] == 42.5
