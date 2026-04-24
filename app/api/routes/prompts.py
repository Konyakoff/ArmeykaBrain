"""Промпты: /api/prompts, /api/prompts/save, /api/prompts/create, /api/prompts/delete."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.prompt_manager import PromptManager
from app.models.requests import SavePromptRequest, CreatePromptRequest, DeletePromptRequest

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _check_admin_password(password: Optional[str]) -> bool:
    return password == settings.admin_password


@router.get("")
async def get_prompts():
    """Возвращает текущие шаблоны промптов для редактора."""
    styles = PromptManager.get_styles()
    audio = PromptManager.get_audio_prompts()
    step3_keys = {k: v for k, v in audio.items() if k != "evaluation"}
    prompts = {
        "step2_style": dict(styles),
        "step3": step3_keys,
    }
    return JSONResponse(content={"prompts": prompts})


@router.post("/save")
async def save_prompt(req: SavePromptRequest):
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    try:
        PromptManager.save_prompt(req.target, req.content, req.style_key)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)


@router.post("/create")
async def create_prompt(req: CreatePromptRequest):
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    try:
        PromptManager.create_prompt(req.target, req.name, req.content)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)


@router.post("/delete")
async def delete_prompt(req: DeletePromptRequest):
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    try:
        PromptManager.delete_prompt(req.target, req.name)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)
