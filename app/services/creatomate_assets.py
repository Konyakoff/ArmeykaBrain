"""
Creatomate-assets — пресеты intro/outro/watermark/музыки/LUT для Creatomate-монтажа.

Каждый пресет — это просто пара ключ → URL/значение. URL должен быть публично
доступен (Creatomate скачивает ассеты по URL). Для собственных файлов используем
хост armeykabrain.net/static/...
"""
from __future__ import annotations

HOST = "https://armeykabrain.net"

# Watermark / лого
WATERMARK_PRESETS: dict[str, dict] = {
    "off":        {"label": "Без логотипа", "url": ""},
    "star":       {"label": "Звезда (брендинг)", "url": f"{HOST}/static/img/star_rounded.png"},
}

# Intro/outro: фоновое изображение + дефолтный текст
INTRO_PRESETS: dict[str, dict] = {
    "off":   {"label": "Без intro", "image": "", "text": ""},
    "brand": {"label": "АРМЕЙКА НЭТ (брендинг)", "image": f"{HOST}/static/img/star_rounded.png", "text": "АРМЕЙКА НЭТ"},
}
OUTRO_PRESETS: dict[str, dict] = {
    "off":     {"label": "Без outro", "image": "", "text": ""},
    "cta":     {"label": "Подписаться (CTA)", "image": "", "text": "Подписывайтесь и будьте свободны с Армейка Нэт"},
    "brand":   {"label": "Брендинг + CTA",   "image": f"{HOST}/static/img/star_rounded.png", "text": "АРМЕЙКА НЭТ — будьте свободны"},
}

# Background music — добавьте файлы в static/audio/music/
MUSIC_PRESETS: dict[str, dict] = {
    "off":      {"label": "Без музыки", "url": ""},
    # Примеры (нужно положить файлы):
    # "uplift":   {"label": "Uplifting", "url": f"{HOST}/static/audio/music/uplifting.mp3"},
    # "calm":     {"label": "Calm Cinematic", "url": f"{HOST}/static/audio/music/calm.mp3"},
}

# Цветокор (LUT) — у Creatomate базовые color_filter без LUT-загрузки
COLOR_FILTER_PRESETS: dict[str, dict] = {
    "off":       {"label": "Без фильтра", "filter": "", "value": ""},
    "brighten":  {"label": "Brighten",    "filter": "brighten", "value": "20%"},
    "contrast":  {"label": "Contrast",    "filter": "contrast", "value": "30%"},
    "sepia":     {"label": "Sepia",       "filter": "sepia",    "value": "50%"},
    "grayscale": {"label": "Ч/Б",         "filter": "grayscale","value": "100%"},
}


def resolve_watermark(key: str | None) -> str:
    if not key or key == "off":
        return ""
    return (WATERMARK_PRESETS.get(key) or {}).get("url", "")


def resolve_intro(key: str | None) -> tuple[str, str]:
    if not key or key == "off":
        return "", ""
    p = INTRO_PRESETS.get(key) or {}
    return p.get("image", ""), p.get("text", "")


def resolve_outro(key: str | None) -> tuple[str, str]:
    if not key or key == "off":
        return "", ""
    p = OUTRO_PRESETS.get(key) or {}
    return p.get("image", ""), p.get("text", "")


def resolve_music(key: str | None) -> str:
    if not key or key == "off":
        return ""
    return (MUSIC_PRESETS.get(key) or {}).get("url", "")


def resolve_color(key: str | None) -> tuple[str, str]:
    if not key or key == "off":
        return "", ""
    p = COLOR_FILTER_PRESETS.get(key) or {}
    return p.get("filter", ""), p.get("value", "")
