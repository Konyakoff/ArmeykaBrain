"""PR4: Проверка раскола database.py на репозитории.

- Все функции должны быть импортируемы как из репо, так и из app.db.database
  (обратная совместимость).
- Один сквозной CRUD-цикл проверяет, что миграция/чтение/обновление работают.
"""

import json
import pytest


# ────────────────────────── re-export sanity ───────────────────────────────────

def test_messages_repo_exports():
    from app.db.repos import messages_repo
    assert callable(messages_repo.log_message)


def test_saved_result_repo_exports():
    from app.db.repos import saved_result_repo as sr
    for name in (
        "reserve_slug", "finalize_result", "save_result",
        "get_result_by_slug", "get_recent_results",
        "add_additional_audio", "save_main_evaluation", "save_additional_evaluation",
        "update_result_with_audio", "update_result_with_timecodes",
        "update_result_with_video", "update_result_with_video_status",
        "save_additional_video_stats", "update_additional_video_url",
    ):
        assert callable(getattr(sr, name)), f"Missing {name}"


def test_tree_repo_exports():
    from app.db.repos import tree_repo as tr
    for name in (
        "get_tree_nodes", "save_tree_node", "get_tree_node",
        "update_tree_node_status", "update_tree_node_title",
        "delete_tree_node_cascade", "count_siblings",
        "migrate_saved_result_to_tree", "update_tree_node_stats",
        "update_tree_node_evaluation",
        "upsert_video_result_node", "create_processing_video_node",
    ):
        assert callable(getattr(tr, name)), f"Missing {name}"


def test_database_module_backward_compat():
    """Старые импорты `from app.db.database import save_result` должны работать."""
    from app.db import database as db
    for name in (
        "log_message", "reserve_slug", "finalize_result", "save_result",
        "get_result_by_slug", "get_recent_results", "add_additional_audio",
        "save_main_evaluation", "save_additional_evaluation",
        "update_result_with_audio", "update_result_with_timecodes",
        "update_result_with_video", "update_result_with_video_status",
        "save_additional_video_stats", "update_additional_video_url",
        "get_tree_nodes", "save_tree_node", "get_tree_node",
        "update_tree_node_status", "update_tree_node_title",
        "delete_tree_node_cascade", "count_siblings",
        "migrate_saved_result_to_tree", "update_tree_node_stats",
        "update_tree_node_evaluation",
        "upsert_video_result_node", "create_processing_video_node",
    ):
        assert hasattr(db, name), f"app.db.database.{name} отсутствует — сломан реэкспорт"


# ───────────────────────── functional CRUD cycle ───────────────────────────────

def test_crud_cycle(tmp_db):
    """Один сквозной цикл: reserve → finalize → read → update timecodes → tree migration."""
    from app.db import database as db

    slug = db.reserve_slug("Тестовый вопрос?", "audio")
    assert slug, "reserve_slug должен вернуть непустой slug"

    pending = db.get_result_by_slug(slug)
    assert pending is not None
    assert pending["answer"].startswith("⏳")

    db.finalize_result(
        slug=slug,
        step1_info="info",
        answer="Полный ответ.",
        tab_type="audio",
        step3_audio="Сценарий",
        step4_audio_url="/static/audio/x.mp3",
        step4_audio_url_original="/static/audio/x_orig.mp3",
        step4_stats=json.dumps({"voice": "v1"}, ensure_ascii=False),
    )

    final = db.get_result_by_slug(slug)
    assert final["answer"] == "Полный ответ."
    assert final["step3_audio"] == "Сценарий"

    # таймкоды через прямой апдейт
    ok = db.update_result_with_timecodes(slug, "/tc.json", "/tc.vtt", 0.005)
    assert ok
    final2 = db.get_result_by_slug(slug)
    s4 = final2["step4_stats"]
    assert s4["timecodes_json_url"] == "/tc.json"

    # миграция в дерево
    db.migrate_saved_result_to_tree(slug, final2)
    nodes = db.get_tree_nodes(slug)
    assert any(n["node_type"] == "article" for n in nodes)
    assert any(n["node_type"] == "script" for n in nodes)
    assert any(n["node_type"] == "audio" for n in nodes)


def test_history_lists_recent(tmp_db):
    from app.db import database as db
    db.save_result(question="q1", step1_info="", answer="a1", tab_type="text")
    db.save_result(question="q2", step1_info="", answer="a2", tab_type="text")
    rows = db.get_recent_results(limit=10, tab_type="text")
    assert len(rows) >= 2
    assert all(r["tab_type"] == "text" for r in rows)
