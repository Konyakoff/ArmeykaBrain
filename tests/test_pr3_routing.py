"""PR3: Проверка, что после раскола main.py на роутеры все URL сохранены.

Snapshot URL/methods зафиксирован вручную из исходного monolithic main.py,
чтобы любой будущий случайный «потерянный» эндпоинт обнаруживался немедленно.
"""

import pytest


# (path, method) — все эндпоинты до рефакторинга
EXPECTED_ENDPOINTS = {
    # pages
    ("/",                   "GET"),
    ("/text",               "GET"),
    ("/audio",              "GET"),
    ("/video",              "GET"),
    ("/text/{slug}",        "GET"),

    # meta / config / cache / video / db
    ("/api/avatars-html",                  "GET"),
    ("/api/avatar-preview/{avatar_id}",    "GET"),
    ("/api/config",                        "GET"),
    ("/api/video_status",                  "GET"),
    ("/api/update_video_result",           "POST"),
    ("/api/db/download",                   "GET"),
    ("/api/cache/status",                  "GET"),
    ("/api/cache/refresh",                 "POST"),

    # prompts
    ("/api/prompts",         "GET"),
    ("/api/prompts/save",    "POST"),
    ("/api/prompts/create",  "POST"),
    ("/api/prompts/delete",  "POST"),

    # history
    ("/api/history",         "GET"),
    ("/api/text/{slug}",     "GET"),

    # query / pipeline
    ("/api/query",                "POST"),
    ("/api/stream_query",         "GET"),
    ("/api/upgrade_to_audio",     "POST"),
    ("/api/generate_audio_only",  "POST"),
    ("/api/generate_video_only",  "POST"),
    ("/api/evaluate_audio",       "POST"),

    # tree
    ("/api/tree/{slug}",                                  "GET"),
    ("/api/tree/node/{node_id}",                          "GET"),
    ("/api/tree/node/{node_id}/title",                    "PATCH"),
    ("/api/tree/node/{node_id}",                          "DELETE"),
    ("/api/tree/node/{node_id}/evaluation",               "PATCH"),
    ("/api/tree/node/{node_id}/timecodes",                "POST"),
    ("/api/tree/{slug}/node/{parent_node_id}/generate",   "POST"),
    ("/api/tree/node/{node_id}/stream",                   "GET"),
}


def test_all_expected_endpoints_present(app_client):
    from app.main import app
    actual = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path:
            continue
        for m in methods:
            actual.add((path, m))

    missing = EXPECTED_ENDPOINTS - actual
    assert not missing, f"Эндпоинты исчезли после рефакторинга: {sorted(missing)}"


def test_no_duplicate_endpoints(app_client):
    """Каждая (path, method) пара должна быть зарегистрирована ровно один раз."""
    from app.main import app
    seen = {}
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path:
            continue
        for m in methods:
            key = (path, m)
            seen[key] = seen.get(key, 0) + 1
    duplicates = {k: v for k, v in seen.items() if v > 1}
    assert not duplicates, f"Дубликаты роутов: {duplicates}"
