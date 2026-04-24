"""Tree API: /api/tree/*."""

from __future__ import annotations

import json
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.core.exceptions import NotFoundError, ValidationError
from app.core.state import background_tasks, active_streams
from app.db.database import (
    get_result_by_slug,
    get_tree_nodes,
    get_tree_node,
    update_tree_node_title,
    delete_tree_node_cascade,
    migrate_saved_result_to_tree,
    update_tree_node_evaluation,
)
from app.models.requests import GenerateNodeRequest, RenamNodeRequest
from app.services.tree_service import dispatch_generate, _generate_timecodes_background

logger = logging.getLogger("api")
router = APIRouter(prefix="/api/tree", tags=["tree"])


@router.get("/{slug}")
async def get_tree(slug: str):
    """Возвращает все узлы дерева. Первый раз — мигрирует из SavedResult."""
    result_data = get_result_by_slug(slug)
    if not result_data:
        raise NotFoundError("Результат не найден")

    if result_data.get("answer", "").startswith("⏳"):
        return {
            "slug": slug,
            "question": result_data["question"],
            "tab_type": result_data.get("tab_type") or "text",
            "timestamp": result_data["timestamp"],
            "status": "pending",
            "is_streaming": slug in active_streams,
            "nodes": [],
        }

    nodes = get_tree_nodes(slug)
    if not nodes:
        migrate_saved_result_to_tree(slug, result_data)
        nodes = get_tree_nodes(slug)

    return {
        "slug": slug,
        "question": result_data["question"],
        "tab_type": result_data.get("tab_type") or "text",
        "timestamp": result_data["timestamp"],
        "status": "ready",
        "nodes": nodes,
    }


@router.get("/node/{node_id}")
async def get_tree_node_api(node_id: str):
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    return node


@router.patch("/node/{node_id}/title")
async def rename_node(node_id: str, req: RenamNodeRequest):
    ok = update_tree_node_title(node_id, req.title)
    if not ok:
        raise NotFoundError("Узел не найден")
    return {"ok": True}


@router.delete("/node/{node_id}")
async def delete_node(node_id: str):
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    if node["node_type"] == "article":
        raise ValidationError("Корневой узел нельзя удалить")
    ok = delete_tree_node_cascade(node_id)
    return {"ok": ok}


@router.patch("/node/{node_id}/evaluation")
async def save_node_evaluation(node_id: str, req: dict):
    ok = update_tree_node_evaluation(node_id, req)
    return {"ok": ok}


@router.post("/node/{node_id}/timecodes")
async def generate_node_timecodes(node_id: str):
    """Ручной запуск генерации таймкодов Deepgram для аудио-узла."""
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    if node.get("node_type") != "audio":
        raise ValidationError("Таймкоды поддерживаются только для аудио-узлов")
    st = node.get("stats_json") or {}
    if st.get("timecodes_json_url"):
        return {"ok": False, "message": "Таймкоды уже сгенерированы"}
    audio_url = node.get("content_url_original") or node.get("content_url")
    if not audio_url:
        raise ValidationError("Аудио-файл не найден в узле")

    task = asyncio.create_task(_generate_timecodes_background(node_id, audio_url))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return {"ok": True, "message": "Генерация таймкодов запущена"}


@router.post("/{slug}/node/{parent_node_id}/generate")
async def generate_node(slug: str, parent_node_id: str, req: GenerateNodeRequest):
    """Запускает генерацию нового дочернего узла; возвращает первое событие синхронно."""
    queue = asyncio.Queue()

    task = asyncio.create_task(
        dispatch_generate(queue, slug, parent_node_id, req.target_type, req.params)
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    try:
        first_event = await asyncio.wait_for(queue.get(), timeout=10.0)
    except asyncio.TimeoutError:
        return JSONResponse({"step": "error", "message": "Таймаут создания узла"}, status_code=500)

    if first_event.get("step") == "error":
        return JSONResponse(
            {"step": "error", "message": first_event.get("message", "Ошибка генерации")},
            status_code=400,
        )

    node_id = (first_event.get("node") or {}).get("node_id")
    if node_id:
        active_streams[node_id] = queue

    return JSONResponse(first_event)


@router.get("/node/{node_id}/stream")
async def stream_tree_node(node_id: str):
    """SSE-стрим прогресса для уже созданного узла."""
    queue = active_streams.get(node_id)
    if not queue:
        return EventSourceResponse(iter([]))

    async def generator():
        try:
            while True:
                chunk = await queue.get()
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
                if chunk.get("step") in ("done", "error"):
                    break
        except asyncio.CancelledError:
            logger.info(f"Tree node {node_id} stream client disconnected, background continues")
        finally:
            active_streams.pop(node_id, None)

    return EventSourceResponse(generator())
