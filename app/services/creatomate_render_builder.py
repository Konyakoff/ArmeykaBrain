"""
Creatomate RenderScript builder.

Собирает JSON-сценарий монтажа: основное видео + karaoke-субтитры (через
встроенный auto-transcript Creatomate) + опциональная фоновая музыка + B-roll.

Reference: https://creatomate.com/docs/api/render-script/json-structure
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger("creatomate_render_builder")

# ── Форматы видео ────────────────────────────────────────────────────────────

FORMAT_PRESETS: dict[str, dict] = {
    "9:16":  {"width": 1080, "height": 1920},   # Reels / Shorts / TikTok
    "16:9":  {"width": 1920, "height": 1080},   # YouTube
    "1:1":   {"width": 1080, "height": 1080},   # Instagram square
    "4:5":   {"width": 1080, "height": 1350},   # Instagram portrait
}

ALLOWED_FPS = (24, 25, 30, 60)

# ── Пресеты стилей субтитров ─────────────────────────────────────────────────
# Каждый пресет — это переопределения для text-элемента с transcript_source.
# Базовая позиция вертикальная (нижняя треть экрана), горизонтальная по центру.

SUBTITLE_PRESETS: dict[str, dict] = {
    "hormozi_white": {
        "label": "Hormozi (белый, обводка)",
        "font_family": "Montserrat",
        "font_weight": 800,
        "fill_color": "#ffffff",
        "stroke_color": "#000000",
        "stroke_width": "1.2 vmin",
        "background_color": None,
        "transcript_color": "#ffd700",     # подсветка текущего слова
    },
    "hormozi_yellow": {
        "label": "Hormozi (жёлтый акцент)",
        "font_family": "Montserrat",
        "font_weight": 900,
        "fill_color": "#ffffff",
        "stroke_color": "#000000",
        "stroke_width": "1.5 vmin",
        "background_color": None,
        "transcript_color": "#fbbf24",
    },
    "army_green": {
        "label": "Армейский (зелёный фон)",
        "font_family": "Inter",
        "font_weight": 700,
        "fill_color": "#ffffff",
        "stroke_color": None,
        "background_color": "rgba(34,79,42,0.85)",
        "background_x_padding": "60%",
        "background_y_padding": "40%",
        "background_border_radius": "12%",
        "transcript_color": "#ffd700",
    },
    "minimal_dark": {
        "label": "Минимал (тёмный фон)",
        "font_family": "Inter",
        "font_weight": 600,
        "fill_color": "#ffffff",
        "stroke_color": None,
        "background_color": "rgba(0,0,0,0.6)",
        "background_x_padding": "50%",
        "background_y_padding": "30%",
        "background_border_radius": "8%",
        "transcript_color": "#22d3ee",
    },
    "tiktok_white": {
        "label": "TikTok (белый, без обводки)",
        "font_family": "Inter",
        "font_weight": 700,
        "fill_color": "#ffffff",
        "stroke_color": "#000000",
        "stroke_width": "0.6 vmin",
        "background_color": None,
        "transcript_color": "#ff2d55",
    },
}

DEFAULT_PRESET = "hormozi_white"

ALLOWED_TRANSCRIPT_EFFECTS = ("color", "karaoke", "highlight", "bounce")
ALLOWED_TRANSCRIPT_SPLITS  = ("word", "line", "none")


# ── Утилиты ──────────────────────────────────────────────────────────────────

def _resolve_format(video_format: str) -> tuple[int, int]:
    preset = FORMAT_PRESETS.get(video_format)
    if not preset:
        preset = FORMAT_PRESETS["9:16"]
    return preset["width"], preset["height"]


def _normalize_fps(fps: int) -> int:
    fps = int(fps or 30)
    return fps if fps in ALLOWED_FPS else 30


def _build_subtitle_element(
    *,
    preset_key: str,
    transcript_effect: str,
    transcript_split: str,
    main_video_name: str,
    subtitle_y: str,
    max_chars_per_line: Optional[int],
) -> dict:
    preset = SUBTITLE_PRESETS.get(preset_key) or SUBTITLE_PRESETS[DEFAULT_PRESET]

    if transcript_effect not in ALLOWED_TRANSCRIPT_EFFECTS:
        transcript_effect = "karaoke"
    if transcript_split not in ALLOWED_TRANSCRIPT_SPLITS:
        transcript_split = "word"

    el: dict = {
        "type": "text",
        "name": "subtitles",
        "track": 5,
        "y": subtitle_y,
        "y_alignment": "100%",
        "width": "88%",
        "x_alignment": "50%",
        "font_family": preset.get("font_family", "Montserrat"),
        "font_weight": preset.get("font_weight", 700),
        "font_size": "5.5 vmin",
        "fill_color": preset.get("fill_color", "#ffffff"),
        "transcript_source": main_video_name,
        "transcript_effect": transcript_effect,
        "transcript_split": transcript_split,
        "transcript_color": preset.get("transcript_color", "#ffd700"),
    }
    if preset.get("stroke_color"):
        el["stroke_color"] = preset["stroke_color"]
        el["stroke_width"] = preset.get("stroke_width", "1 vmin")
    if preset.get("background_color"):
        el["background_color"] = preset["background_color"]
        el["background_x_padding"] = preset.get("background_x_padding", "50%")
        el["background_y_padding"] = preset.get("background_y_padding", "30%")
        el["background_border_radius"] = preset.get("background_border_radius", "8%")
    if max_chars_per_line and max_chars_per_line > 0:
        el["transcript_maximum_length"] = int(max_chars_per_line)

    return el


def _build_music_element(music_url: str, *, volume_pct: int = 25, fade_sec: float = 1.5) -> dict:
    vol = max(0, min(100, int(volume_pct)))
    return {
        "type": "audio",
        "name": "background_music",
        "track": 9,
        "source": music_url,
        "loop": True,
        "audio_volume": f"{vol}%",
        "audio_fade_in": fade_sec,
        "audio_fade_out": fade_sec,
    }


BROLL_LAYOUTS = ("overlay", "pip", "split")
"""
Режимы размещения B-roll:
  overlay — B-roll на весь кадр поверх основного видео (track 3, 100%)
  pip     — B-roll маленьким окном в правом нижнем углу; спикер остаётся виден
  split   — динамический split:
            • main video (track 1) — полный кадр всегда (audio 100%)
            • main_focus (track 2) — дубликат main, обрезанный до левых 50%
              (fit:cover auto-центрирует спикера в левой половине),
              виден только во время B-roll, fade-in/out 0.5 с
            • B-roll (track 3) — правая половина с fade-in/out 0.5 с
            • blend gradient (track 4) — тёмный градиент-оверлей у границы
              x=50% для визуального смягчения шва (НЕ маска, просто shape)

Структура треков (z-order: больше = выше):
  1: main video      |  5: subtitles
  2: main_focus      |  6: intro
  3: B-roll          |  7: outro
  4: blend gradient  |  8: watermark
                     |  9: music

ВАЖНО: alpha-маска (mask_mode) не используется — при gradient fill_color с
rgba(0) Creatomate делает весь masked элемент невидимым.
"""

_BROLL_TRACK = 3
_MAIN_FOCUS_TRACK = 2
_BROLL_MASK_TRACK = 4


def _build_broll_element(
    *,
    source: str,
    time: float,
    duration: float,
    name: str,
    layout: str = "overlay",
    video_format: str = "9:16",
) -> dict:
    """B-roll вставка: видео на track 3 без звука, поверх основного.

    Creatomate НЕ поддерживает отрицательный time ни для элементов, ни для
    анимаций — отрицательное значение молча блокирует весь элемент.
    Fade-out позиционируем как абсолютный offset от начала клипа.

    layout:
      overlay — полноэкранный B-roll (закрывает спикера)
      pip     — маленькое окно в правом нижнем углу (спикер виден)
      split   — правая половина кадра (main_focus покажет спикера слева,
                feather mask размоет левый край B-roll)
    """
    if layout not in BROLL_LAYOUTS:
        layout = "overlay"

    dur = round(float(duration), 3)
    fade_dur = 0.3
    fadeout_time = round(max(0.0, dur - fade_dur), 3)

    is_portrait = video_format in ("9:16", "4:5")

    base: dict = {
        "type": "video",
        "name": name,
        "track": _BROLL_TRACK,
        "time": round(float(time), 3),
        "duration": dur,
        "source": source,
        "fit": "cover",
        "audio_volume": "0%",
        "animations": [
            {"time": 0,            "duration": fade_dur, "easing": "quadratic-out", "type": "fade"},
            {"time": fadeout_time, "duration": fade_dur, "easing": "quadratic-out", "type": "fade", "reversed": True},
        ],
    }

    if layout == "pip":
        # Небольшое окно в правом нижнем углу (~38% ширины), с скруглением и тенью
        if is_portrait:
            pip_w, pip_h = "40%", "22%"
            pip_x, pip_y = "94%", "88%"
        else:
            pip_w, pip_h = "36%", "38%"
            pip_x, pip_y = "92%", "82%"
        base.update({
            "x": pip_x, "y": pip_y,
            "x_anchor": "100%", "y_anchor": "100%",
            "width": pip_w, "height": pip_h,
            "border_radius": "2vmin",
            "shadow_color": "#000000",
            "shadow_blur": "3vmin",
        })

    elif layout == "split":
        # Правая половина кадра. Левый край размывается feather-маской на track 4.
        base.update({
            "x": "75%", "y": "50%",
            "x_anchor": "50%", "y_anchor": "50%",
            "width": "50%", "height": "100%",
        })
        # Увеличиваем fade-in/out до 0.5 с для более плавного перехода
        fade_soft = 0.5
        fadeout_soft = round(max(0.0, dur - fade_soft), 3)
        base["animations"] = [
            {"time": 0,            "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade"},
            {"time": fadeout_soft, "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade", "reversed": True},
        ]

    return base


def _build_main_focus_overlay(
    *,
    video_url: str,
    time: float,
    duration: float,
    name: str,
) -> dict:
    """Дубликат main video, смещённый влево; виден поверх main только во время B-roll.

    Делает спикера (центрированного в исходнике) центрированным в левой половине
    канваса. Использует trim_start для воспроизведения того же фрагмента, что
    идёт в main video на этой временной отметке.

    Размещается на track 2 (выше main, ниже B-roll). Звук отключён —
    идёт из основного main video на track 1.
    """
    dur = round(float(duration), 3)
    fade_soft = 0.5
    fadeout_time = round(max(0.0, dur - fade_soft), 3)
    start = round(float(time), 3)
    return {
        "type": "video",
        "name": name,
        "track": _MAIN_FOCUS_TRACK,
        "time": start,
        "duration": dur,
        "source": video_url,
        "trim_start": start,        # синхронизация с положением main на timeline
        "trim_duration": dur,
        "audio_volume": "0%",       # звук берём из основного main
        "fit": "cover",
        # Занимаем ТОЛЬКО левые 50% канваса.
        # fit:cover auto-центрирует спикера (из центра исходника) внутри 50%-контейнера.
        # Правая половина (50%-100%) не перекрывается — там виден B-roll (track 3).
        "x": "0%", "y": "0%",
        "x_anchor": "0%", "y_anchor": "0%",
        "width": "50%", "height": "100%",
        "animations": [
            {"time": 0,            "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade"},
            {"time": fadeout_time, "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade", "reversed": True},
        ],
    }


def _build_split_blend(
    *,
    time: float,
    duration: float,
    name: str,
) -> dict:
    """Мягкий градиентный оверлей у границы split (x=50%).

    НЕ маска (mask_mode не используется — Creatomate не корректно применяет
    alpha-маску с gradient fill_color, делая B-roll полностью невидимым).

    Это просто тёмный shape на track 4 поверх B-roll: тёмный на x=50% и
    прозрачный чуть правее. Создаёт визуальный «шов» между main_focus и B-roll.
    Появляется и исчезает синхронно с B-roll через fade-анимацию.
    """
    dur = round(float(duration), 3)
    fade_soft = 0.5
    fadeout_time = round(max(0.0, dur - fade_soft), 3)
    return {
        "type": "shape",
        "name": name,
        "track": _BROLL_MASK_TRACK,   # 4: выше B-roll, ниже субтитров
        "time": round(float(time), 3),
        "duration": dur,
        # Левый край у шва (x=50%), уходит вправо на 8% ширины канваса
        "x": "50%", "y": "0%",
        "x_anchor": "0%", "y_anchor": "0%",
        "width": "8%", "height": "100%",
        "fill_color": [
            {"offset": "0%",   "color": "rgba(0,0,0,0.4)"},
            {"offset": "100%", "color": "rgba(0,0,0,0)"},
        ],
        "fill_mode": "linear",
        "fill_x0": "0%", "fill_y0": "50%",
        "fill_x1": "100%", "fill_y1": "50%",
        "animations": [
            {"time": 0,            "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade"},
            {"time": fadeout_time, "duration": fade_soft, "easing": "quadratic-in-out", "type": "fade", "reversed": True},
        ],
    }


def _build_watermark_element(image_url: str, *, position: str = "top-right") -> dict:
    pos = {
        "top-right":    {"x": "92%", "y": "8%",  "x_anchor": "100%", "y_anchor": "0%"},
        "top-left":     {"x": "8%",  "y": "8%",  "x_anchor": "0%",   "y_anchor": "0%"},
        "bottom-right": {"x": "92%", "y": "92%", "x_anchor": "100%", "y_anchor": "100%"},
        "bottom-left":  {"x": "8%",  "y": "92%", "x_anchor": "0%",   "y_anchor": "100%"},
    }.get(position, {"x": "92%", "y": "8%", "x_anchor": "100%", "y_anchor": "0%"})
    return {
        "type": "image",
        "name": "watermark",
        "track": 8,
        "source": image_url,
        "width": "12%",
        "opacity": "75%",
        **pos,
    }


def _build_intro_outro(
    *,
    kind: str,         # 'intro' | 'outro'
    image_url: Optional[str],
    text: Optional[str],
    duration: float,
    total_duration_sec: Optional[float] = None,   # длина основного видео (для outro)
    width: int = 1080,
    height: int = 1920,
) -> list[dict]:
    """Возвращает элементы intro/outro (картинка + текст с fade).

    Creatomate НЕ поддерживает отрицательный time. Для outro используем
    абсолютное смещение: total_duration_sec - outro_duration. Если длина
    видео неизвестна — outro не добавляем (элементы будут пустыми).
    """
    elems: list[dict] = []

    if kind == "outro":
        if not total_duration_sec or total_duration_sec <= 0:
            # Без длины видео невозможно корректно позиционировать outro — пропускаем
            return []
        time_val: float = max(0.0, round(total_duration_sec - duration, 3))
    else:
        time_val = 0.0

    # Creatomate не поддерживает отрицательный animation.time — позиционируем абсолютно
    fade_dur = 0.6
    fadeout_time = round(max(0.0, duration - fade_dur), 3)
    base_anim = [
        {"time": 0, "duration": fade_dur, "easing": "quadratic-out", "type": "fade"},
        {"time": fadeout_time, "duration": fade_dur, "easing": "quadratic-in", "type": "fade", "reversed": True},
    ]
    track = 6 if kind == "intro" else 7
    if image_url:
        elems.append({
            "type": "image",
            "name": f"{kind}_image",
            "track": track,
            "time": time_val,
            "duration": duration,
            "source": image_url,
            "fit": "contain",
            "fill_color": "#0f172a",
            "animations": base_anim,
        })
    if text:
        elems.append({
            "type": "text",
            "name": f"{kind}_text",
            "track": track + 0.5 if False else track,  # тот же track, поверх
            "time": time_val,
            "duration": duration,
            "y": "75%",
            "width": "80%",
            "x_alignment": "50%",
            "y_alignment": "100%",
            "fill_color": "#ffffff",
            "stroke_color": "#000000",
            "stroke_width": "0.8 vmin",
            "font_family": "Montserrat",
            "font_weight": 800,
            "font_size": "6 vmin",
            "text": text,
            "animations": base_anim,
        })
    return elems


# ── Главный билдер ───────────────────────────────────────────────────────────

def build_render_script(
    *,
    video_url: str,
    duration_sec: Optional[float] = None,
    video_format: str = "9:16",
    fps: int = 30,
    subtitle_preset: str = DEFAULT_PRESET,
    transcript_effect: str = "karaoke",
    transcript_split: str = "word",
    subtitle_y: str = "82%",
    max_chars_per_line: Optional[int] = 32,
    music_url: Optional[str] = None,
    music_volume_pct: int = 25,
    broll_clips: Optional[Iterable[dict]] = None,
    broll_layout: str = "overlay",
    intro_image: Optional[str] = None,
    intro_text: Optional[str] = None,
    intro_duration: float = 2.0,
    outro_image: Optional[str] = None,
    outro_text: Optional[str] = None,
    outro_duration: float = 2.5,
    watermark_url: Optional[str] = None,
    watermark_position: str = "top-right",
    color_filter: Optional[str] = None,        # 'brighten'/'contrast'/...
    color_filter_value: Optional[str] = None,  # '20%', '40%', ...
    main_video_name: str = "main",
) -> dict:
    """
    Главная функция сборки RenderScript.

    `broll_clips`:  iterable of {source: str, time: float, duration: float}.
    `broll_layout`: 'overlay' | 'pip' | 'split'
                    split — main video полноэкранный всегда; во время B-roll
                    появляется main_focus (track 2, спикер сдвигается в левую
                    половину); B-roll справа (track 3); feather alpha-маска
                    (track 4) даёт плавный переход между видео.
    `duration_sec`: если задано — использовать как duration основного видео и
                    общую длину рендера. Если None — Creatomate определит по
                    видео-источнику.
    """
    if broll_layout not in BROLL_LAYOUTS:
        broll_layout = "overlay"

    width, height = _resolve_format(video_format)
    fps = _normalize_fps(fps)

    elements: list[dict] = []

    # 1. Основное видео (track 1)
    main_el: dict = {
        "type": "video",
        "name": main_video_name,
        "track": 1,
        "time": 0,
        "source": video_url,
        "audio_volume": "100%",
        "fit": "cover",
    }
    if duration_sec:
        main_el["duration"] = round(float(duration_sec), 3)
    if color_filter:
        main_el["color_filter"] = color_filter
        if color_filter_value:
            main_el["color_filter_value"] = color_filter_value

    elements.append(main_el)

    # 2. B-roll (track 3) + для split: main_focus (track 2) и feather mask (track 4)
    if broll_clips:
        for i, clip in enumerate(broll_clips, start=1):
            src = clip.get("source") or clip.get("url")
            if not src:
                continue
            clip_time = clip.get("time", 0)
            clip_dur  = clip.get("duration", 5)

            # Для split: main_focus — смещённый дубликат main, под B-roll.
            # Добавляем ПЕРВЫМ (хотя track определяет z-order, это для
            # читаемости элементов в JSON).
            if broll_layout == "split":
                elements.append(_build_main_focus_overlay(
                    video_url=video_url,
                    time=clip_time,
                    duration=clip_dur,
                    name=f"main_focus_{i}",
                ))

            # B-roll на track 3 (правая половина для split)
            elements.append(_build_broll_element(
                source=src,
                time=clip_time,
                duration=clip_dur,
                name=f"broll_{i}",
                layout=broll_layout,
                video_format=video_format,
            ))

            # Для split: градиентный оверлей у шва x=50% (без mask_mode)
            if broll_layout == "split":
                elements.append(_build_split_blend(
                    time=clip_time,
                    duration=clip_dur,
                    name=f"broll_mask_{i}",
                ))

    # 3. Субтитры (track 5) — auto-transcript из основного видео
    elements.append(_build_subtitle_element(
        preset_key=subtitle_preset,
        transcript_effect=transcript_effect,
        transcript_split=transcript_split,
        main_video_name=main_video_name,
        subtitle_y=subtitle_y,
        max_chars_per_line=max_chars_per_line,
    ))

    # 4. Intro/outro
    if intro_image or intro_text:
        elements.extend(_build_intro_outro(
            kind="intro", image_url=intro_image, text=intro_text,
            duration=intro_duration, width=width, height=height,
        ))
    if outro_image or outro_text:
        elements.extend(_build_intro_outro(
            kind="outro", image_url=outro_image, text=outro_text,
            duration=outro_duration, total_duration_sec=duration_sec,
            width=width, height=height,
        ))

    # 5. Watermark
    if watermark_url:
        elements.append(_build_watermark_element(watermark_url, position=watermark_position))

    # 6. Background music
    if music_url:
        elements.append(_build_music_element(music_url, volume_pct=music_volume_pct))

    script: dict = {
        "output_format": "mp4",
        "width": width,
        "height": height,
        "frame_rate": fps,
        "elements": elements,
    }
    if duration_sec:
        script["duration"] = round(float(duration_sec), 3)
    return script
