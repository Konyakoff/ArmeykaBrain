"""Меta-эндпоинты: /api/config, /api/cache/*, /api/avatars-html, /api/avatar-preview/{id},
/api/db/download, /api/video_status, /api/update_video_result."""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
import datetime
import html as _html
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.core.exceptions import NotFoundError
from app.core.state import background_tasks
from app.core.prompt_manager import PromptManager
from app.db.database import get_db_path, get_result_by_slug
from app.services.data_loader import ALL_MODELS
from app.services.elevenlabs_service import (
    get_elevenlabs_voices,
    _fetch_elevenlabs_voices_from_api,
)
from app.services.heygen_service import (
    get_heygen_avatars,
    get_heygen_private_avatars,
    check_video_status,
    _fetch_heygen_avatars_from_api,
    _fetch_heygen_private_avatars_from_api,
)

logger = logging.getLogger("api")
router = APIRouter(tags=["meta"])

_AVATAR_PREVIEW_DIR = os.path.join("static", "img", "avatars")
_AVATAR_ID_SAFE = re.compile(r"^[a-zA-Z0-9_-]+$")

_AVATAR_FMT = {
    "16:9": {"key": "is_horizontal_friendly", "label": "16:9", "color": "#4f46e5"},
    "9:16": {"key": "is_vertical_friendly",   "label": "9:16", "color": "#059669"},
    "1:1":  {"key": "is_square_friendly",     "label": "1:1",  "color": "#d97706"},
}


# ─────────────────────────── /api/avatars-html ────────────────────────────────

@router.get("/api/avatars-html")
async def get_avatars_html(format: str = "16:9", tab: str = "public", show_all: str = "0"):
    """Публичные аватары → текстовый список; приватные → карточки с фото."""
    fmt = _AVATAR_FMT.get(format, _AVATAR_FMT["16:9"])

    if tab == "private":
        avatars = await get_heygen_private_avatars()
        if not avatars:
            return HTMLResponse(
                '<div style="padding:60px 20px;text-align:center;color:#9ca3af;font-size:14px;">'
                'Личные аватары не найдены</div>'
            )
        parts = []
        for a in avatars:
            aid      = a["avatar_id"]
            name     = _html.escape(a.get("avatar_name", aid))
            is_good  = bool(a.get(fmt["key"]))
            badge_bg = fmt["color"] if is_good else "#6b7280"
            badge_sym = "✓" if is_good else "~"
            img_url  = f"/static/img/avatars/{aid}.webp"
            parts.append(
                f'<div data-avatar-id="{_html.escape(aid)}" role="button" tabindex="0" '
                f'style="display:flex;flex-direction:column;border-radius:12px;cursor:pointer;'
                f'overflow:hidden;background:#fff;border:2px solid #e5e7eb;'
                f'box-shadow:0 1px 3px rgba(0,0,0,.06);">'
                f'<div style="height:140px;min-height:140px;background-color:#e5e7eb;'
                f"background-image:url('{img_url}');"
                f'background-size:cover;background-position:top center;position:relative;">'
                f'<div style="position:absolute;top:4px;right:4px;font-size:9px;font-weight:700;'
                f'padding:2px 5px;border-radius:4px;background:{badge_bg};color:#fff;">'
                f'{badge_sym}&nbsp;{fmt["label"]}</div></div>'
                f'<div style="padding:8px 6px;font-size:11px;font-weight:600;color:#374151;'
                f'text-align:center;min-height:2.75em;display:flex;align-items:center;'
                f'justify-content:center;">{name}</div>'
                f'</div>'
            )
        return HTMLResponse('\n'.join(parts))

    all_av = await get_heygen_avatars()
    if show_all != "1":
        filtered = [a for a in all_av if a.get(fmt["key"])]
        avatars  = filtered if filtered else all_av
    else:
        avatars  = all_av

    if not avatars:
        return HTMLResponse(
            '<div style="padding:60px 20px;text-align:center;color:#9ca3af;font-size:14px;">'
            'Аватары не найдены</div>'
        )

    _GENDER_ICON = {"female": "♀", "male": "♂"}
    parts = []
    for a in avatars:
        aid       = a["avatar_id"]
        name      = _html.escape(a.get("avatar_name", aid))
        is_good   = bool(a.get(fmt["key"]))
        badge_bg  = fmt["color"] if is_good else "#9ca3af"
        badge_sym = "✓" if is_good else "~"
        gender    = (a.get("gender") or "unknown").lower()
        g_icon    = _GENDER_ICON.get(gender, "")
        g_color   = "#ec4899" if gender == "female" else ("#3b82f6" if gender == "male" else "#9ca3af")

        parts.append(
            f'<div data-avatar-id="{_html.escape(aid)}" data-gender="{gender}" '
            f'role="button" tabindex="0" '
            f'style="display:flex;align-items:center;gap:10px;padding:9px 14px;'
            f'border-bottom:1px solid #f3f4f6;cursor:pointer;background:#fff;"'
            f' onmouseover="if(!this.dataset.sel)this.style.background=\'#f9fafb\'"'
            f' onmouseout="if(!this.dataset.sel)this.style.background=\'#fff\'">'

            f'<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;'
            f'background:{badge_bg};color:#fff;white-space:nowrap;flex-shrink:0;">'
            f'{badge_sym}&nbsp;{fmt["label"]}</span>'

            f'<span style="font-size:13px;color:{g_color};flex-shrink:0;width:14px;'
            f'text-align:center;">{g_icon}</span>'

            f'<span style="font-size:13px;color:#374151;font-weight:500;flex:1;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{name}</span>'

            f'<span data-preview-id="{_html.escape(aid)}" '
            f'style="flex-shrink:0;color:#94a3b8;cursor:pointer;padding:4px 6px;'
            f'border-radius:6px;line-height:1;"'
            f' onmouseover="this.style.color=\'#F47920\';this.style.background=\'#fff7ed\'"'
            f' onmouseout="this.style.color=\'#94a3b8\';this.style.background=\'transparent\'"'
            f' title="Предпросмотр аватара">'
            f'<i class="fas fa-eye" style="pointer-events:none;font-size:12px;"></i></span>'
            f'</div>'
        )

    return HTMLResponse('\n'.join(parts))


@router.get("/api/avatar-preview/{avatar_id}")
async def get_avatar_preview(avatar_id: str):
    if not _AVATAR_ID_SAFE.match(avatar_id):
        raise NotFoundError(message="Некорректный идентификатор аватара")
    path = os.path.join(_AVATAR_PREVIEW_DIR, f"{avatar_id}.webp")
    if not os.path.isfile(path):
        raise NotFoundError(message="Превью аватара не найдено")
    return FileResponse(path, media_type="image/webp")


# ─────────────────────────────── /api/config ──────────────────────────────────

@router.get("/api/config")
async def get_config():
    """Доступные модели/стили/голоса/аватары для фронтенда."""
    styles_data = PromptManager.get_styles()
    models = [
        {"id": m["model_name"],
         "name": m.get("display_name", m["model_name"]),
         "provider": m.get("provider", "gemini")}
        for m in ALL_MODELS
    ]
    styles = [{"id": s, "name": s} for s in styles_data.keys()]

    voices, avatars_raw, private_raw = await asyncio.gather(
        get_elevenlabs_voices(),
        get_heygen_avatars(),
        get_heygen_private_avatars(),
    )

    avatars = [{k: v for k, v in a.items() if not k.startswith("_")} for a in avatars_raw]
    private_avatars = [{k: v for k, v in a.items() if not k.startswith("_")} for a in private_raw]

    return {
        "models": models,
        "styles": styles,
        "voices": voices,
        "avatars": avatars,
        "private_avatars": private_avatars,
        "default_model": "gemini-3.1-pro-preview",
        "default_style": "telegram_yur",
        "default_voice": "FGY2WhTYpPnroxEErjIq",
        "default_avatar": "ef720fad85884cc3b9d3352828f1f7e7",
    }


# ─────────────────────────── /api/video_status ────────────────────────────────

@router.get("/api/video_status")
async def check_heygen_video(video_id: str):
    try:
        return await check_video_status(video_id)
    except Exception as e:
        logger.error(f"Error checking video status: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/api/update_video_result")
async def update_video_result(req: dict):
    from app.db.database import (
        update_result_with_video_status,
        update_additional_video_url,
        upsert_video_result_node,
    )
    if "slug" in req and "video_url" in req:
        slug = req["slug"]
        video_url = req["video_url"]
        is_main = req.get("is_main", True)
        if is_main:
            update_result_with_video_status(slug, video_url)
            try:
                result = get_result_by_slug(slug)
                s5 = result.get("step5_stats") or {} if result else {}
                if isinstance(s5, str):
                    try: s5 = json.loads(s5)
                    except Exception: s5 = {}
                upsert_video_result_node(
                    slug=slug,
                    video_url=video_url,
                    video_stats=s5,
                    video_format=s5.get("video_format", "16:9"),
                    avatar_style=s5.get("avatar_style", "normal"),
                    avatar_id=s5.get("avatar_id", ""),
                    heygen_engine=s5.get("heygen_engine", "avatar_iv"),
                )
            except Exception as e:
                print(f"update_video_result: upsert_video_result_node error: {e}")
        else:
            video_id = req.get("video_id")
            if video_id:
                update_additional_video_url(slug, video_id, video_url)
        return {"success": True}
    return {"success": False}


# ─────────────────────────── /api/db/download ─────────────────────────────────

@router.get("/api/db/download")
async def download_db():
    db_path = get_db_path()
    if os.path.exists(db_path):
        return FileResponse(
            path=db_path,
            filename="dialogs.db",
            media_type="application/octet-stream",
        )
    raise NotFoundError("База данных не найдена")


# ─────────────────────────── /api/cache/* ─────────────────────────────────────

_cache_update_status = {
    "running": False,
    "last_updated_at": None,
    "error": None,
}


def _get_cache_last_updated() -> Optional[str]:
    files = [
        "db/heygen_avatars_cache.json",
        "db/heygen_private_avatars_cache.json",
        "db/elevenlabs_voices_cache.json",
    ]
    mtimes = [os.path.getmtime(f) for f in files if os.path.exists(f)]
    if not mtimes:
        return None
    ts = min(mtimes)
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


@router.get("/api/cache/status")
async def get_cache_status():
    return {
        "running": _cache_update_status["running"],
        "last_updated_at": _cache_update_status["last_updated_at"] or _get_cache_last_updated(),
        "error": _cache_update_status["error"],
    }


@router.post("/api/cache/refresh")
async def refresh_cache():
    if _cache_update_status["running"]:
        return {"ok": False, "message": "Обновление уже выполняется"}

    async def _do_refresh():
        _cache_update_status["running"] = True
        _cache_update_status["error"] = None
        errors = []
        try:
            results = await asyncio.gather(
                _fetch_heygen_avatars_from_api(),
                _fetch_heygen_private_avatars_from_api(),
                _fetch_elevenlabs_voices_from_api(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    errors.append(str(r))
        except Exception as e:
            errors.append(str(e))
        finally:
            _cache_update_status["running"] = False
            _cache_update_status["last_updated_at"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            if errors:
                _cache_update_status["error"] = "; ".join(errors)

    task = asyncio.create_task(_do_refresh())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return {"ok": True, "message": "Обновление запущено"}


# ──────────────────────── /api/submagic/templates ─────────────────────────────

_submagic_templates_cache: list[str] | None = None


@router.get("/api/submagic/templates")
async def get_submagic_templates():
    """Returns cached list of Submagic caption templates."""
    global _submagic_templates_cache
    if _submagic_templates_cache is None:
        try:
            from app.services.submagic_service import get_templates
            _submagic_templates_cache = await get_templates()
        except Exception as e:
            logger.error(f"Failed to fetch Submagic templates: {e}")
            _submagic_templates_cache = [
                "Hormozi 2", "Hormozi 1", "Hormozi 3", "Hormozi 4", "Hormozi 5",
                "Sara", "Matt", "Jess", "Jack", "Nick", "Laura", "Kelly 2",
                "Beast", "Karl", "Ella", "Dan", "Dan 2", "Devin",
            ]
    return {"templates": _submagic_templates_cache}
