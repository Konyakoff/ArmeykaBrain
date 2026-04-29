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


async def upload_user_media(url: str) -> str:
    """Upload a public video/image URL to the Submagic media library.

    Returns userMediaId (UUID) to reference in project items.
    Submagic fetches and processes the URL asynchronously — call
    wait_for_user_media() before using the ID in a project.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/user-media", headers=_headers(), json={"url": url}
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                error_msg = data.get("message") or data.get("error") or str(data)
                raise Exception(f"Submagic upload_user_media error ({resp.status}): {error_msg}")
            media_id = data.get("userMediaId")
            if not media_id:
                raise Exception(f"Submagic upload_user_media: нет userMediaId в ответе: {data}")
            logger.info(f"Submagic user media uploaded: id={media_id}")
            return media_id


async def list_user_media(media_type: str = "VIDEO", limit: int = 50) -> list[dict]:
    """Fetch user media list (single page). Returns array of media items.

    Submagic response shape: {"data": [{"id": "...", "type": "VIDEO", ...}, ...]}
    Each item exposes "id" (== userMediaId returned by upload_user_media).
    """
    params = {"type": media_type, "limit": limit}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/user-media", headers=_headers(), params=params
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                error_msg = data.get("message") or data.get("error") or str(data)
                raise Exception(f"Submagic list_user_media error ({resp.status}): {error_msg}")
            return data.get("data") or data.get("items") or []


async def wait_for_user_media(
    media_id: str,
    max_wait_sec: int = 120,
    poll_interval: int = 3,
) -> bool:
    """Poll until the uploaded media appears in the library (ready to use).

    Returns True if ready, False if timeout reached.
    Submagic downloads and processes the URL asynchronously — we need to wait
    until the media ID appears in the list before referencing it in a project.

    Match attempts use both "id" and "userMediaId" for forward-compatibility
    with possible Submagic API variations.
    """
    import asyncio
    elapsed = 0
    while elapsed < max_wait_sec:
        try:
            items = await list_user_media(limit=100)
            if any(
                (it.get("id") == media_id) or (it.get("userMediaId") == media_id)
                for it in items
            ):
                logger.info(f"Submagic user media ready: id={media_id} (после {elapsed}с)")
                return True
        except Exception as e:
            logger.warning(f"Submagic wait_for_user_media poll error: {e}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    logger.warning(f"Submagic user media timeout: id={media_id} не появился за {max_wait_sec}с")
    return False


async def wait_for_user_media_batch(
    media_ids: list[str],
    max_wait_sec: int = 120,
    poll_interval: int = 3,
) -> set[str]:
    """Wait for several user-media IDs at once. Returns set of IDs that became ready.

    Single shared list_user_media() call per polling tick — much more efficient
    than waiting for IDs sequentially.
    """
    import asyncio
    pending = set(media_ids)
    ready: set[str] = set()
    elapsed = 0
    while pending and elapsed < max_wait_sec:
        try:
            items = await list_user_media(limit=100)
            present = {
                it.get("id") for it in items if it.get("id")
            } | {
                it.get("userMediaId") for it in items if it.get("userMediaId")
            }
            newly_ready = pending & present
            if newly_ready:
                ready |= newly_ready
                pending -= newly_ready
                logger.info(
                    f"Submagic user media ready: {len(newly_ready)} of {len(media_ids)} "
                    f"(всего {len(ready)}, осталось {len(pending)}, t={elapsed}с)"
                )
        except Exception as e:
            logger.warning(f"Submagic wait_for_user_media_batch poll error: {e}")
        if not pending:
            break
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    if pending:
        logger.warning(
            f"Submagic user media batch timeout: {len(pending)} ID не появились "
            f"за {max_wait_sec}с: {list(pending)[:3]}..."
        )
    return ready
