"""
Submagic API service — видео-монтаж через AI-powered captions и эффекты.

API Reference: https://docs.submagic.co/api-reference/create-project
Workflow: create project → wait for transcription → auto-export → poll for result.
"""
import logging
import aiohttp

from app.core.config import settings

logger = logging.getLogger("submagic_service")

BASE_URL = "https://api.submagic.co/v1"


def _headers() -> dict:
    return {
        "x-api-key": settings.submagic_api_key,
        "Content-Type": "application/json",
    }


async def create_project(
    video_url: str,
    title: str = "ArmeykaBrain montage",
    language: str = "ru",
    template_name: str = "Hormozi 2",
    magic_zooms: bool = True,
    magic_brolls: bool = False,
    magic_brolls_pct: int = 50,
    remove_silence_pace: str | None = None,
    remove_bad_takes: bool = False,
    clean_audio: bool = False,
    webhook_url: str | None = None,
    dictionary: list[str] | None = None,
    items: list[dict] | None = None,
) -> dict:
    """Create a Submagic project. Returns full project JSON with id and status.

    When `items` is provided, Submagic uses our custom B-roll segments instead of
    its automatic magicBrolls — we force `magicBrolls=False` to avoid mixing.
    See: https://docs.submagic.co/api-reference/create-project
    """
    effective_magic_brolls = False if items else magic_brolls
    payload: dict = {
        "title": title,
        "language": language,
        "videoUrl": video_url,
        "templateName": template_name,
        "magicZooms": magic_zooms,
        "magicBrolls": effective_magic_brolls,
        "magicBrollsPercentage": magic_brolls_pct,
        "removeBadTakes": remove_bad_takes,
        "cleanAudio": clean_audio,
        # hideCaptions omitted — not yet supported by Submagic API (returns 400)
    }
    if remove_silence_pace:
        payload["removeSilencePace"] = remove_silence_pace
    if webhook_url:
        payload["webhookUrl"] = webhook_url
    if dictionary:
        payload["dictionary"] = dictionary[:100]
    if items:
        payload["items"] = items

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/projects", headers=_headers(), json=payload
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                error_msg = data.get("message") or data.get("error") or str(data)
                raise Exception(f"Submagic create_project error ({resp.status}): {error_msg}")
            logger.info(f"Submagic project created: id={data.get('id')}, status={data.get('status')}")
            return data


async def get_project(project_id: str) -> dict:
    """Get project details including status, downloadUrl, directUrl."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/projects/{project_id}", headers=_headers()
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                error_msg = data.get("message") or data.get("error") or str(data)
                raise Exception(f"Submagic get_project error ({resp.status}): {error_msg}")
            return data


async def export_project(
    project_id: str,
    fps: int | None = None,
    width: int | None = None,
    height: int | None = None,
    webhook_url: str | None = None,
) -> dict:
    """Trigger export/rendering for a completed project."""
    payload: dict = {}
    if fps:
        payload["fps"] = fps
    if width:
        payload["width"] = width
    if height:
        payload["height"] = height
    if webhook_url:
        payload["webhookUrl"] = webhook_url

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/projects/{project_id}/export",
            headers=_headers(),
            json=payload if payload else None,
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                error_msg = data.get("message") or data.get("error") or str(data)
                raise Exception(f"Submagic export error ({resp.status}): {error_msg}")
            logger.info(f"Submagic export started: project_id={project_id}")
            return data


async def get_templates() -> list[str]:
    """Fetch available caption templates."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/templates", headers=_headers()
        ) as resp:
            data = await resp.json()
            return data.get("templates", [])
