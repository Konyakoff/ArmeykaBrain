"""Ядро доступа к БД: engine, init_db, get_db_path и общие helpers.

После PR4 все CRUD-операции вынесены в app/db/repos/{messages,saved_result,tree}_repo.py.
Этот модуль реэкспортирует все функции для обратной совместимости со старыми
импортами вида `from app.db.database import save_result`.
"""

from __future__ import annotations

import os
import json

from sqlmodel import SQLModel, create_engine
from sqlalchemy import text

from app.db.models import ResultNode  # noqa: F401  (нужно для metadata.create_all)

DB_DIR = "db"
DB_PATH = os.path.join(DB_DIR, "dialogs.db")
sqlite_url = f"sqlite:///{DB_PATH}"

engine = create_engine(sqlite_url, echo=False)


def get_db_path() -> str:
    return DB_PATH


def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)

    SQLModel.metadata.create_all(engine)

    # WAL + busy_timeout — критично для конкурентных фоновых задач (Deepgram, HeyGen).
    with engine.begin() as conn:
        try:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=5000"))
        except Exception as _e:
            print(f"PRAGMA setup skipped: {_e}")

    with engine.begin() as conn:
        for col_sql in (
            "ALTER TABLE saved_results ADD COLUMN tab_type TEXT DEFAULT 'text'",
            "ALTER TABLE saved_results ADD COLUMN step3_audio TEXT",
            "ALTER TABLE saved_results ADD COLUMN step4_audio_url TEXT",
            "ALTER TABLE saved_results ADD COLUMN step4_audio_url_original TEXT",
            "ALTER TABLE saved_results ADD COLUMN additional_audios TEXT DEFAULT '[]'",
            "ALTER TABLE saved_results ADD COLUMN evaluation_main TEXT",
            "ALTER TABLE saved_results ADD COLUMN step1_stats TEXT",
            "ALTER TABLE saved_results ADD COLUMN step2_stats TEXT",
            "ALTER TABLE saved_results ADD COLUMN step3_stats TEXT",
            "ALTER TABLE saved_results ADD COLUMN step4_stats TEXT",
            "ALTER TABLE saved_results ADD COLUMN step5_video_url TEXT",
            "ALTER TABLE saved_results ADD COLUMN step5_video_id TEXT",
            "ALTER TABLE saved_results ADD COLUMN step5_stats TEXT",
            "ALTER TABLE saved_results ADD COLUMN total_stats TEXT",
        ):
            try: conn.execute(text(col_sql))
            except Exception: pass

    ResultNode.__table__.create(engine, checkfirst=True)


# ──────────────────────────────────────────────────────────────────────────────
# Patch-семантика для JSON-полей (используется repos/saved_result_repo.py).
# Оставлена здесь, потому что является частью «фундамента» уровня engine/init_db.
# ──────────────────────────────────────────────────────────────────────────────
def _merge_json_field(existing: str | None, patch_json: str | None,
                      preserve_keys: tuple) -> str | None:
    """Сливает existing-JSON и patch-JSON, гарантируя что preserve_keys из existing
    не будут потеряны (если их нет в patch). Возвращает строку JSON или None.
    """
    if not patch_json:
        return existing
    try:
        merged = json.loads(patch_json) if isinstance(patch_json, str) else dict(patch_json)
    except Exception:
        return patch_json
    if existing and not any(merged.get(k) for k in preserve_keys):
        try:
            ex = json.loads(existing)
            for k in preserve_keys:
                if ex.get(k):
                    merged[k] = ex[k]
        except Exception:
            pass
    return json.dumps(merged, ensure_ascii=False)


_TC_KEYS = ("timecodes_json_url", "timecodes_vtt_url", "timecodes_cost")


# ──────────────────────────────────────────────────────────────────────────────
# Реэкспорт CRUD-функций из репозиториев — обратная совместимость.
# Все существующие вызовы `from app.db.database import save_result` продолжают работать.
# Импорт repos происходит после определения engine/init_db/_merge_json_field,
# чтобы избежать циклов.
# ──────────────────────────────────────────────────────────────────────────────
from app.db.repos import (  # noqa: E402,F401
    log_message,
    reserve_slug,
    finalize_result,
    save_result,
    get_result_by_slug,
    get_recent_results,
    add_additional_audio,
    save_main_evaluation,
    save_additional_evaluation,
    update_result_with_audio,
    update_result_with_timecodes,
    update_result_with_video,
    update_result_with_video_status,
    save_additional_video_stats,
    update_additional_video_url,
    get_tree_nodes,
    save_tree_node,
    get_tree_node,
    update_tree_node_status,
    update_tree_node_title,
    delete_tree_node_cascade,
    count_siblings,
    migrate_saved_result_to_tree,
    update_tree_node_stats,
    update_tree_node_evaluation,
    upsert_video_result_node,
    create_processing_video_node,
)
