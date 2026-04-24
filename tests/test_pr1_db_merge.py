"""PR1: SQLite WAL + merge-семантика для finalize_result/update_result_with_audio.

Тесты используют in-memory SQLite через monkey-patch engine модуля database.
Не требуют полной CI-инфраструктуры из PR2.
"""

import json
import pytest
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import text

from app.db import database as db
from app.db.models import SavedResult


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Подменяет engine на файловый SQLite в tmp_path и инициализирует схему.

    Файловый engine (а не :memory:) нужен, чтобы PRAGMA journal_mode=WAL
    действительно мог переключиться (in-memory всегда возвращает 'memory').
    """
    db_file = tmp_path / "test_pr1.db"
    test_engine = create_engine(f"sqlite:///{db_file}", echo=False)
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    monkeypatch.setattr(db, "DB_DIR", str(tmp_path))
    db.init_db()
    return test_engine


def _insert_pending(engine, slug: str = "260101-00001",
                    step4_stats: dict | None = None,
                    step5_video_url: str | None = None) -> str:
    with Session(engine) as s:
        rec = SavedResult(
            slug=slug,
            question="",
            step1_info="",
            answer="",
            timestamp="2026-01-01 00:00:00",
            char_count=0,
            tab_type="video",
            step4_stats=json.dumps(step4_stats, ensure_ascii=False) if step4_stats else None,
            step5_video_url=step5_video_url,
            additional_audios="[]",
        )
        s.add(rec)
        s.commit()
    return slug


def test_wal_enabled(isolated_db):
    """После init_db() база должна работать в режиме WAL."""
    with isolated_db.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert (mode or "").lower() == "wal", f"expected wal, got {mode!r}"


def test_busy_timeout_set(isolated_db):
    """busy_timeout должен быть >=5000."""
    with isolated_db.connect() as conn:
        bt = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert int(bt) >= 5000


def test_finalize_preserves_timecodes(isolated_db):
    """finalize_result не должен затирать timecodes_*, если они уже записаны."""
    slug = _insert_pending(
        isolated_db,
        step4_stats={
            "timecodes_json_url": "/static/audio/tc_abc.json",
            "timecodes_vtt_url": "/static/audio/tc_abc.vtt",
            "timecodes_cost": 0.0042,
        },
    )
    new_step4 = json.dumps({"voice": "Sergey", "duration": 30}, ensure_ascii=False)
    db.finalize_result(
        slug=slug,
        step1_info="",
        answer="answer text",
        tab_type="video",
        step4_stats=new_step4,
    )
    with Session(isolated_db) as s:
        rec = s.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
    stats = json.loads(rec.step4_stats)
    assert stats.get("timecodes_json_url") == "/static/audio/tc_abc.json"
    assert stats.get("timecodes_vtt_url") == "/static/audio/tc_abc.vtt"
    assert stats.get("timecodes_cost") == 0.0042
    assert stats.get("voice") == "Sergey"
    assert stats.get("duration") == 30


def test_finalize_does_not_overwrite_timecodes_with_explicit_value(isolated_db):
    """Если в новом step4_stats явно переданы таймкоды — они побеждают."""
    slug = _insert_pending(
        isolated_db,
        step4_stats={"timecodes_json_url": "/old.json"},
    )
    new_step4 = json.dumps({
        "timecodes_json_url": "/new.json",
        "timecodes_vtt_url": "/new.vtt",
    }, ensure_ascii=False)
    db.finalize_result(slug=slug, step1_info="", answer="x",
                       tab_type="video", step4_stats=new_step4)
    with Session(isolated_db) as s:
        rec = s.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
    stats = json.loads(rec.step4_stats)
    assert stats["timecodes_json_url"] == "/new.json"
    assert stats["timecodes_vtt_url"] == "/new.vtt"


def test_finalize_preserves_video_url_when_already_set(isolated_db):
    """finalize_result(..., step5_video_url=None) НЕ должен затирать URL,
    если он уже пришёл от _poll_heygen_video_background."""
    slug = _insert_pending(
        isolated_db,
        step5_video_url="https://heygen.com/video/abc.mp4",
    )
    db.finalize_result(slug=slug, step1_info="", answer="x",
                       tab_type="video", step5_video_url=None)
    with Session(isolated_db) as s:
        rec = s.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
    assert rec.step5_video_url == "https://heygen.com/video/abc.mp4"


def test_finalize_writes_video_url_when_provided(isolated_db):
    """Если URL передан явно — он должен записаться (даже если уже что-то было)."""
    slug = _insert_pending(isolated_db, step5_video_url="https://old.mp4")
    db.finalize_result(slug=slug, step1_info="", answer="x",
                       tab_type="video", step5_video_url="https://new.mp4")
    with Session(isolated_db) as s:
        rec = s.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
    assert rec.step5_video_url == "https://new.mp4"


def test_update_result_with_audio_preserves_timecodes(isolated_db):
    """Аналогичная защита в update_result_with_audio."""
    slug = _insert_pending(
        isolated_db,
        step4_stats={"timecodes_json_url": "/tc.json", "timecodes_vtt_url": "/tc.vtt"},
    )
    db.update_result_with_audio(
        slug=slug,
        step3_audio="script",
        step4_audio_url="/static/audio/x.mp3",
        step4_audio_url_original="/static/audio/x_orig.mp3",
        step4_stats=json.dumps({"voice": "Voice1"}, ensure_ascii=False),
    )
    with Session(isolated_db) as s:
        rec = s.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
    stats = json.loads(rec.step4_stats)
    assert stats.get("timecodes_json_url") == "/tc.json"
    assert stats.get("timecodes_vtt_url") == "/tc.vtt"
    assert stats.get("voice") == "Voice1"


def test_merge_json_field_helper():
    """Прямой unit-тест на helper."""
    existing = json.dumps({"timecodes_json_url": "/a", "x": 1})
    patch = json.dumps({"y": 2})
    out = db._merge_json_field(existing, patch, ("timecodes_json_url",))
    parsed = json.loads(out)
    assert parsed["timecodes_json_url"] == "/a"
    assert parsed["y"] == 2
    assert "x" not in parsed  # не из preserve_keys

    # Пустой patch — возвращаем existing as-is
    assert db._merge_json_field(existing, None, ("k",)) == existing
    # Пустой existing — возвращаем patch
    assert json.loads(db._merge_json_field(None, patch, ("k",))) == {"y": 2}
