import os
import json
from datetime import datetime
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import text
from app.db.models import Message, SavedResult, ResultNode

DB_DIR = "db"
DB_PATH = os.path.join(DB_DIR, "dialogs.db")
sqlite_url = f"sqlite:///{DB_PATH}"

engine = create_engine(sqlite_url, echo=False)

def get_db_path():
    return DB_PATH

def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        
    SQLModel.metadata.create_all(engine)
    
    with engine.begin() as conn:
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN tab_type TEXT DEFAULT 'text'"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step3_audio TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step4_audio_url TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step4_audio_url_original TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN additional_audios TEXT DEFAULT '[]'"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN evaluation_main TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step1_stats TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step2_stats TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step3_stats TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step4_stats TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step5_video_url TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step5_video_id TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN step5_stats TEXT"))
        except Exception: pass
        try: conn.execute(text("ALTER TABLE saved_results ADD COLUMN total_stats TEXT"))
        except Exception: pass

    # Создаём таблицу result_nodes если её нет (через SQLModel metadata)
    ResultNode.__table__.create(engine, checkfirst=True)

def log_message(user_id: int, username: str, direction: str, text_msg: str):
    if not text_msg:
        return
    try:
        with Session(engine) as session:
            msg = Message(
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_id=user_id,
                username=username or "",
                direction=direction,
                text=text_msg
            )
            session.add(msg)
            session.commit()
    except Exception as e:
        print(f"Error logging message: {e}")

def _generate_slug(session: Session) -> str:
    """Генерирует уникальный slug вида YYMMDD-NNNNN."""
    date_prefix = datetime.now().strftime("%y%m%d")
    statement = select(SavedResult).where(SavedResult.slug.like(f"{date_prefix}-%"))
    count_today = len(session.exec(statement).all())
    return f"{date_prefix}-{(count_today + 1):05d}"


def reserve_slug(question: str, tab_type: str = 'text') -> str:
    """Создаёт «pending» запись в БД сразу при старте запроса и возвращает slug."""
    try:
        now = datetime.now()
        with Session(engine) as session:
            slug = _generate_slug(session)
            new_result = SavedResult(
                slug=slug,
                question=question,
                step1_info="",
                answer="⏳ Генерация в процессе...",
                timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
                char_count=0,
                tab_type=tab_type,
                additional_audios="[]"
            )
            session.add(new_result)
            session.commit()
            return slug
    except Exception as e:
        print(f"Error reserving slug: {e}")
        return ""


def finalize_result(slug: str, step1_info: str, answer: str, tab_type: str = 'text',
                    step3_audio: str = None, step4_audio_url: str = None, step4_audio_url_original: str = None,
                    step1_stats: str = None, step2_stats: str = None, step3_stats: str = None,
                    step4_stats: str = None, step5_video_url: str = None, step5_video_id: str = None,
                    step5_stats: str = None, total_stats: str = None) -> str:
    """Обновляет pending-запись финальными данными. Возвращает slug."""
    try:
        with Session(engine) as session:
            result = session.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
            if not result:
                return save_result(
                    question="", step1_info=step1_info, answer=answer, tab_type=tab_type,
                    step3_audio=step3_audio, step4_audio_url=step4_audio_url,
                    step4_audio_url_original=step4_audio_url_original,
                    step1_stats=step1_stats, step2_stats=step2_stats, step3_stats=step3_stats,
                    step4_stats=step4_stats, step5_video_url=step5_video_url,
                    step5_video_id=step5_video_id, step5_stats=step5_stats, total_stats=total_stats
                )
            result.step1_info = step1_info
            result.answer = answer
            result.char_count = len(answer)
            result.tab_type = tab_type
            result.step3_audio = step3_audio
            result.step4_audio_url = step4_audio_url
            result.step4_audio_url_original = step4_audio_url_original
            result.step1_stats = step1_stats
            result.step2_stats = step2_stats
            result.step3_stats = step3_stats
            result.step4_stats = step4_stats
            result.step5_video_url = step5_video_url
            result.step5_video_id = step5_video_id
            result.step5_stats = step5_stats
            result.total_stats = total_stats
            session.add(result)
            session.commit()
            return slug
    except Exception as e:
        print(f"Error finalizing result: {e}")
        return slug


def save_result(question: str, step1_info: str, answer: str, tab_type: str = 'text', step3_audio: str = None, step4_audio_url: str = None, step4_audio_url_original: str = None, step1_stats: str = None, step2_stats: str = None, step3_stats: str = None, step4_stats: str = None, step5_video_url: str = None, step5_video_id: str = None, step5_stats: str = None, total_stats: str = None) -> str:
    try:
        now = datetime.now()
        date_prefix = now.strftime("%y%m%d")
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        char_count = len(answer)
        
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug.like(f"{date_prefix}-%"))
            results_today = session.exec(statement).all()
            count_today = len(results_today)
            
            slug = f"{date_prefix}-{(count_today + 1):05d}"
            
            new_result = SavedResult(
                slug=slug,
                question=question,
                step1_info=step1_info,
                answer=answer,
                timestamp=timestamp_str,
                char_count=char_count,
                tab_type=tab_type,
                step3_audio=step3_audio,
                step4_audio_url=step4_audio_url,
                step4_audio_url_original=step4_audio_url_original,
                step1_stats=step1_stats,
                step2_stats=step2_stats,
                step3_stats=step3_stats,
                step4_stats=step4_stats,
                step5_video_url=step5_video_url,
                step5_video_id=step5_video_id,
                step5_stats=step5_stats,
                total_stats=total_stats,
                additional_audios="[]"
            )
            session.add(new_result)
            session.commit()
            return slug
    except Exception as e:
        print(f"Error saving result: {e}")
        return ""

def get_result_by_slug(slug: str) -> dict:
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            
            if result:
                res_dict = result.model_dump()
                if res_dict.get("additional_audios"):
                    try:
                        res_dict["additional_audios_list"] = json.loads(res_dict["additional_audios"])
                    except:
                        res_dict["additional_audios_list"] = []
                else:
                    res_dict["additional_audios_list"] = []
                    
                if res_dict.get("evaluation_main"):
                    try:
                        res_dict["evaluation_main"] = json.loads(res_dict["evaluation_main"])
                    except:
                        pass
                
                # Parse new stats columns
                for stat_field in ["step1_stats", "step2_stats", "step3_stats", "step4_stats", "step5_stats", "total_stats"]:
                    if res_dict.get(stat_field):
                        try:
                            res_dict[stat_field] = json.loads(res_dict[stat_field])
                        except:
                            res_dict[stat_field] = None
                        
                return res_dict
        return None
    except Exception as e:
        print(f"Error getting result: {e}")
        return None

def get_recent_results(limit: int = 50, tab_type: str = 'text') -> list:
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.tab_type == tab_type).order_by(SavedResult.id.desc()).limit(limit)
            results = session.exec(statement).all()
            return [result.model_dump() for result in results]
    except Exception as e:
        print(f"Error getting recent results: {e}")
        return []

def add_additional_audio(slug: str, audio_data: dict) -> bool:
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                try:
                    audios = json.loads(result.additional_audios) if result.additional_audios else []
                except:
                    audios = []
                audios.append(audio_data)
                result.additional_audios = json.dumps(audios, ensure_ascii=False)
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error adding additional audio: {e}")
        return False

def save_main_evaluation(slug: str, eval_data: dict) -> bool:
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                result.evaluation_main = json.dumps(eval_data, ensure_ascii=False)
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error saving main evaluation: {e}")
        return False

def save_additional_evaluation(slug: str, audio_url: str, eval_data: dict) -> bool:
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                try:
                    audios = json.loads(result.additional_audios) if result.additional_audios else []
                except:
                    audios = []
                    
                for audio in audios:
                    if audio.get("audio_url") == audio_url or audio.get("audio_url_original") == audio_url:
                        audio["evaluation"] = eval_data
                        break
                        
                result.additional_audios = json.dumps(audios, ensure_ascii=False)
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error saving additional evaluation: {e}")
        return False

def update_result_with_audio(slug: str, step3_audio: str, step4_audio_url: str, step4_audio_url_original: str, step3_stats: str = None, step4_stats: str = None, total_stats: str = None) -> bool:
    """Обновляет текстовый результат, добавляя к нему сгенерированные аудио-файлы и статистику"""
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                result.step3_audio = step3_audio
                result.step4_audio_url = step4_audio_url
                result.step4_audio_url_original = step4_audio_url_original
                if step3_stats:
                    result.step3_stats = step3_stats
                if step4_stats:
                    result.step4_stats = step4_stats
                if total_stats:
                    result.total_stats = total_stats
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error updating result with audio: {e}")
        return False


def update_result_with_timecodes(slug: str, json_url: str, vtt_url: str, cost: float) -> bool:
    """Сохраняет URLs таймкодов и стоимость Deepgram в step4_stats saved_result
    и синхронизирует с audio-узлом дерева (если он существует)."""
    try:
        with Session(engine) as session:
            result = session.exec(select(SavedResult).where(SavedResult.slug == slug)).first()
            if not result:
                return False
            stats = {}
            if result.step4_stats:
                try:
                    stats = json.loads(result.step4_stats)
                except Exception:
                    stats = {}
            stats["timecodes_json_url"] = json_url
            stats["timecodes_vtt_url"] = vtt_url
            stats["timecodes_cost"] = cost
            result.step4_stats = json.dumps(stats, ensure_ascii=False)
            session.add(result)

            # Также обновляем stats_json audio-узла дерева (если уже мигрирован)
            audio_node = session.exec(
                select(ResultNode).where(
                    ResultNode.slug == slug,
                    ResultNode.node_type == "audio",
                )
            ).first()
            if audio_node:
                node_stats = {}
                if audio_node.stats_json:
                    try:
                        node_stats = json.loads(audio_node.stats_json)
                    except Exception:
                        pass
                node_stats["timecodes_json_url"] = json_url
                node_stats["timecodes_vtt_url"] = vtt_url
                node_stats["timecodes_cost"] = cost
                audio_node.stats_json = json.dumps(node_stats, ensure_ascii=False)
                session.add(audio_node)

            session.commit()
            return True
    except Exception as e:
        print(f"Error updating timecodes for {slug}: {e}")
        return False

def update_result_with_video(slug: str, step5_video_id: str, step5_stats: str = None, total_stats: str = None) -> bool:
    """Обновляет результат, добавляя к нему ID генерируемого видео и статистику."""
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                result.step5_video_id = step5_video_id
                if step5_stats:
                    result.step5_stats = step5_stats
                if total_stats:
                    result.total_stats = total_stats
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error updating result with video: {e}")
        return False

def update_result_with_video_status(slug: str, step5_video_url: str) -> bool:
    """Обновляет URL готового видео и вычисляет время генерации."""
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                import json, time
                if result.step5_stats:
                    try:
                        stats = json.loads(result.step5_stats)
                        if "started_at" in stats:
                            stats["generation_time_sec"] = int(time.time()) - stats["started_at"]
                            stats["status"] = "completed"
                        result.step5_stats = json.dumps(stats, ensure_ascii=False)
                    except:
                        pass
                
                result.step5_video_url = step5_video_url
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error updating result with video url: {e}")
        return False

def save_additional_video_stats(slug: str, audio_url: str, video_id: str, stats_dict: dict) -> bool:
    """Сохраняет ID генерируемого видео для дополнительного аудио."""
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                import json
                audios = json.loads(result.additional_audios) if result.additional_audios else []
                for aud in audios:
                    if aud.get("audio_url") == audio_url or aud.get("audio_url_original") == audio_url:
                        aud["video_id"] = video_id
                        aud["video_stats"] = stats_dict
                        break
                result.additional_audios = json.dumps(audios, ensure_ascii=False)
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error saving additional video stats: {e}")
        return False

# ─────────────────────────────────────────────
# TREE FUNCTIONS
# ─────────────────────────────────────────────

def get_tree_nodes(slug: str) -> list:
    """Возвращает все узлы дерева для данного slug."""
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.slug == slug).order_by(ResultNode.position)
            nodes = session.exec(stmt).all()
            result = []
            for n in nodes:
                d = n.model_dump()
                for f in ("params_json", "stats_json", "evaluation_json"):
                    if d.get(f):
                        try: d[f] = json.loads(d[f])
                        except: pass
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
                result.append(d)
            return result
    except Exception as e:
        print(f"Error get_tree_nodes: {e}")
        return []


def save_tree_node(node: ResultNode) -> ResultNode:
    """Сохраняет новый узел или обновляет существующий."""
    try:
        with Session(engine) as session:
            session.add(node)
            session.commit()
            session.refresh(node)
            return node
    except Exception as e:
        print(f"Error save_tree_node: {e}")
        return node


def get_tree_node(node_id: str) -> dict:
    """Возвращает узел по его node_id."""
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.node_id == node_id)
            node = session.exec(stmt).first()
            if not node:
                return None
            d = node.model_dump()
            for f in ("params_json", "stats_json", "evaluation_json"):
                if d.get(f):
                    try: d[f] = json.loads(d[f])
                    except: pass
            d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
            return d
    except Exception as e:
        print(f"Error get_tree_node: {e}")
        return None


def update_tree_node_status(node_id: str, status: str, content_url: str = None,
                             stats_json: str = None, evaluation_json: str = None) -> bool:
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.node_id == node_id)
            node = session.exec(stmt).first()
            if node:
                node.status = status
                if content_url is not None:
                    node.content_url = content_url
                if stats_json is not None:
                    node.stats_json = stats_json
                if evaluation_json is not None:
                    node.evaluation_json = evaluation_json
                session.add(node)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error update_tree_node_status: {e}")
        return False


def update_tree_node_title(node_id: str, title: str) -> bool:
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.node_id == node_id)
            node = session.exec(stmt).first()
            if node:
                node.title = title
                session.add(node)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error update_tree_node_title: {e}")
        return False


def delete_tree_node_cascade(node_id: str) -> bool:
    """Удаляет узел и все его дочерние узлы (рекурсивно)."""
    try:
        with Session(engine) as session:
            def _collect_ids(nid):
                ids = [nid]
                children = session.exec(
                    select(ResultNode).where(ResultNode.parent_node_id == nid)
                ).all()
                for c in children:
                    ids.extend(_collect_ids(c.node_id))
                return ids

            all_ids = _collect_ids(node_id)
            for nid in all_ids:
                stmt = select(ResultNode).where(ResultNode.node_id == nid)
                node = session.exec(stmt).first()
                if node:
                    session.delete(node)
            session.commit()
            return True
    except Exception as e:
        print(f"Error delete_tree_node_cascade: {e}")
        return False


def count_siblings(parent_node_id: str, node_type: str) -> int:
    """Считает сколько уже есть узлов данного типа у родителя."""
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(
                ResultNode.parent_node_id == parent_node_id,
                ResultNode.node_type == node_type
            )
            return len(session.exec(stmt).all())
    except:
        return 0


def migrate_saved_result_to_tree(slug: str, result_data: dict) -> list:
    """
    Автоматически мигрирует SavedResult в дерево ResultNode.
    Вызывается только если узлов для данного slug ещё нет.
    """
    nodes = []
    now = datetime.utcnow()

    # 1. Корневой узел — статья
    article_stats = {}
    if result_data.get("step1_stats"):
        s1 = result_data["step1_stats"] if isinstance(result_data["step1_stats"], dict) else {}
        article_stats["step1"] = s1
    if result_data.get("step2_stats"):
        s2 = result_data["step2_stats"] if isinstance(result_data["step2_stats"], dict) else {}
        article_stats["step2"] = s2

    # raw_data — оригинальный JSON ответа нейросети на Шаг 1 (для скачивания)
    _s1_raw = None
    if isinstance(article_stats.get("step1"), dict):
        _s1_raw = article_stats["step1"].get("raw_data") or None

    article_node = ResultNode(
        slug=slug,
        node_type="article",
        title="Экспертная статья",
        status="completed",
        position=0,
        content_text=result_data.get("answer", ""),
        params_json=json.dumps({
            "step1_info": result_data.get("step1_info") or "",
            "step1_raw_data": _s1_raw,
        }, ensure_ascii=False),
        stats_json=json.dumps(article_stats, ensure_ascii=False),
        created_at=now,
    )
    nodes.append(article_node)

    # 2. Узел сценария (step3)
    script_node = None
    if result_data.get("step3_audio"):
        # Берём duration и wpm из step4_stats (аудио), если они там есть
        _s4 = result_data.get("step4_stats") or {}
        if isinstance(_s4, str):
            try: _s4 = json.loads(_s4)
            except: _s4 = {}
        _s3 = result_data.get("step3_stats") or {}
        if isinstance(_s3, str):
            try: _s3 = json.loads(_s3)
            except: _s3 = {}
        _script_params = {
            "audio_duration_sec": _s4.get("duration_sec") or _s4.get("audio_duration_sec"),
            "audio_wpm": _s4.get("wpm") or _s4.get("audio_wpm"),
            "step3_prompt_key": _s3.get("prompt_name") or "audio_yur",
        }
        script_node = ResultNode(
            slug=slug,
            parent_node_id=article_node.node_id,
            node_type="script",
            title="Сценарий #1",
            status="completed",
            position=0,
            content_text=result_data["step3_audio"],
            params_json=json.dumps(_script_params, ensure_ascii=False),
            stats_json=json.dumps(
                result_data["step3_stats"] if isinstance(result_data.get("step3_stats"), dict) else {},
                ensure_ascii=False
            ),
            created_at=now,
        )
        nodes.append(script_node)

    # 3. Основное аудио (step4)
    audio_node = None
    if script_node and result_data.get("step4_audio_url"):
        eval_data = result_data.get("evaluation_main")
        audio_node = ResultNode(
            slug=slug,
            parent_node_id=script_node.node_id,
            node_type="audio",
            title="Аудио #1",
            status="completed",
            position=0,
            content_url=result_data.get("step4_audio_url"),
            content_url_original=result_data.get("step4_audio_url_original"),
            stats_json=json.dumps(
                result_data["step4_stats"] if isinstance(result_data.get("step4_stats"), dict) else {},
                ensure_ascii=False
            ),
            evaluation_json=json.dumps(eval_data, ensure_ascii=False) if eval_data else None,
            created_at=now,
        )
        nodes.append(audio_node)

        # 3a. Дополнительные аудио
        for i, add_aud in enumerate(result_data.get("additional_audios_list") or []):
            add_node = ResultNode(
                slug=slug,
                parent_node_id=script_node.node_id,
                node_type="audio",
                title=f"Аудио #{i+2}",
                status="completed",
                position=i + 1,
                content_url=add_aud.get("audio_url"),
                content_url_original=add_aud.get("audio_url_original"),
                params_json=json.dumps({
                    "elevenlabs_model": add_aud.get("elevenlabs_model"),
                    "voice_id": add_aud.get("voice_id"),
                    "voice_name": add_aud.get("voice_name"),
                    "wpm": add_aud.get("wpm"),
                    "stability": add_aud.get("stability"),
                    "similarity_boost": add_aud.get("similarity_boost"),
                    "style": add_aud.get("style"),
                    "use_speaker_boost": add_aud.get("use_speaker_boost"),
                }, ensure_ascii=False),
                stats_json=json.dumps({
                    "char_count": add_aud.get("char_count"),
                    "total_cost": add_aud.get("cost"),
                    "generation_time_sec": add_aud.get("generation_time_sec"),
                }, ensure_ascii=False),
                evaluation_json=json.dumps(add_aud["evaluation"], ensure_ascii=False) if add_aud.get("evaluation") else None,
                created_at=now,
            )
            nodes.append(add_node)

            # Видео у дополнительного аудио
            if add_aud.get("video_url") and add_aud.get("video_id"):
                vs = add_aud.get("video_stats") or {}
                vid_node = ResultNode(
                    slug=slug,
                    parent_node_id=add_node.node_id,
                    node_type="video",
                    title="Видео #1",
                    status="completed",
                    position=0,
                    content_url=add_aud["video_url"],
                    params_json=json.dumps({
                        "heygen_engine": vs.get("engine", "avatar_iv"),
                        "avatar_id": vs.get("avatar_id", ""),
                        "video_format": vs.get("video_format", "16:9"),
                        "avatar_style": vs.get("avatar_style", "auto"),
                    }, ensure_ascii=False),
                    stats_json=json.dumps({
                        "total_cost": vs.get("total_cost"),
                        "generation_time_sec": vs.get("generation_time_sec"),
                        "model": "heygen_v2",
                    }, ensure_ascii=False),
                    created_at=now,
                )
                nodes.append(vid_node)

    # 4. Видео у основного аудио
    if audio_node and result_data.get("step5_video_url"):
        s5 = result_data.get("step5_stats") or {}
        if isinstance(s5, str):
            try: s5 = json.loads(s5)
            except: s5 = {}
        video_node = ResultNode(
            slug=slug,
            parent_node_id=audio_node.node_id,
            node_type="video",
            title="Видео #1",
            status="completed",
            position=0,
            content_url=result_data["step5_video_url"],
            params_json=json.dumps({
                "heygen_engine": s5.get("engine", "avatar_iv"),
                "avatar_id": s5.get("avatar_id", ""),
                "avatar_style": s5.get("avatar_style", "auto"),
                "video_format": s5.get("video_format", "16:9"),
            }, ensure_ascii=False),
            stats_json=json.dumps({
                "total_cost": s5.get("total_cost"),
                "generation_time_sec": s5.get("generation_time_sec"),
                "model": "heygen_v2",
            }, ensure_ascii=False),
            created_at=now,
        )
        nodes.append(video_node)
    elif audio_node and result_data.get("step5_video_id"):
        # HeyGen ещё генерирует — создаём placeholder со статусом processing
        s5 = result_data.get("step5_stats") or {}
        if isinstance(s5, str):
            try: s5 = json.loads(s5)
            except: s5 = {}
        video_node_pending = ResultNode(
            slug=slug,
            parent_node_id=audio_node.node_id,
            node_type="video",
            title="Видео #1",
            status="processing",
            position=0,
            content_url=None,
            params_json=json.dumps({
                "heygen_engine": s5.get("heygen_engine", s5.get("engine", "avatar_iv")),
                "avatar_id": s5.get("avatar_id", ""),
                "avatar_style": s5.get("avatar_style", "normal"),
                "video_format": s5.get("video_format", "16:9"),
            }, ensure_ascii=False),
            stats_json=json.dumps({
                "total_cost": s5.get("total_cost"),
                "video_id": result_data.get("step5_video_id"),
                "status": "pending",
                "model": "heygen_v2",
            }, ensure_ascii=False),
            created_at=now,
        )
        nodes.append(video_node_pending)

    # Сохраняем все узлы
    try:
        with Session(engine) as session:
            for node in nodes:
                session.add(node)
            session.commit()
    except Exception as e:
        print(f"Error migrate_saved_result_to_tree: {e}")

    return nodes


def update_tree_node_stats(node_id: str, extra_stats: dict) -> bool:
    """Мержит extra_stats в существующий stats_json узла."""
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.node_id == node_id)
            node = session.exec(stmt).first()
            if node:
                current = {}
                if node.stats_json:
                    try:
                        current = json.loads(node.stats_json)
                    except Exception:
                        pass
                current.update(extra_stats)
                node.stats_json = json.dumps(current, ensure_ascii=False)
                session.add(node)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error update_tree_node_stats: {e}")
        return False


def update_tree_node_evaluation(node_id: str, eval_data: dict) -> bool:
    try:
        with Session(engine) as session:
            stmt = select(ResultNode).where(ResultNode.node_id == node_id)
            node = session.exec(stmt).first()
            if node:
                node.evaluation_json = json.dumps(eval_data, ensure_ascii=False)
                session.add(node)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error update_tree_node_evaluation: {e}")
        return False


def update_additional_video_url(slug: str, video_id: str, video_url: str) -> bool:
    """Обновляет URL готового видео для дополнительного аудио и вычисляет время генерации."""
    try:
        with Session(engine) as session:
            statement = select(SavedResult).where(SavedResult.slug == slug)
            result = session.exec(statement).first()
            if result:
                import json, time
                audios = json.loads(result.additional_audios) if result.additional_audios else []
                for aud in audios:
                    if aud.get("video_id") == video_id:
                        aud["video_url"] = video_url
                        if "video_stats" in aud and isinstance(aud["video_stats"], dict):
                            aud["video_stats"]["status"] = "completed"
                            if "started_at" in aud["video_stats"]:
                                aud["video_stats"]["generation_time_sec"] = int(time.time()) - aud["video_stats"]["started_at"]
                        break
                result.additional_audios = json.dumps(audios, ensure_ascii=False)
                session.add(result)
                session.commit()
                return True
        return False
    except Exception as e:
        print(f"Error updating additional video url: {e}")
        return False


def upsert_video_result_node(slug: str, video_url: str, video_stats: dict = None,
                              video_format: str = "16:9", avatar_style: str = "normal",
                              avatar_id: str = "", heygen_engine: str = "avatar_iv") -> bool:
    """
    Создаёт или обновляет video ResultNode (status=completed) для основного аудио.
    Ищет существующий video-узел; если не найден — создаёт дочерний к первому audio-узлу.
    """
    try:
        import time as _time
        with Session(engine) as session:
            # Ищем существующий video-узел
            stmt = select(ResultNode).where(
                ResultNode.slug == slug,
                ResultNode.node_type == "video"
            ).order_by(ResultNode.position)
            video_node = session.exec(stmt).first()

            s = video_stats or {}
            if "started_at" in s and "generation_time_sec" not in s:
                s["generation_time_sec"] = int(_time.time()) - s["started_at"]
            s["status"] = "completed"
            stats_str = json.dumps(s, ensure_ascii=False)
            params_str = json.dumps({
                "video_format": video_format,
                "avatar_style": avatar_style,
                "avatar_id": avatar_id,
                "heygen_engine": heygen_engine,
            }, ensure_ascii=False)

            if video_node:
                video_node.content_url = video_url
                video_node.status = "completed"
                video_node.stats_json = stats_str
                video_node.params_json = params_str
                session.add(video_node)
            else:
                # Найти первый audio-узел как родителя
                audio_stmt = select(ResultNode).where(
                    ResultNode.slug == slug,
                    ResultNode.node_type == "audio"
                ).order_by(ResultNode.position)
                audio_node = session.exec(audio_stmt).first()
                if not audio_node:
                    return False
                new_node = ResultNode(
                    slug=slug,
                    parent_node_id=audio_node.node_id,
                    node_type="video",
                    title="Видео #1",
                    status="completed",
                    position=0,
                    content_url=video_url,
                    params_json=params_str,
                    stats_json=stats_str,
                    created_at=datetime.utcnow(),
                )
                session.add(new_node)
            session.commit()
            return True
    except Exception as e:
        print(f"Error upsert_video_result_node: {e}")
        return False


def create_processing_video_node(slug: str, video_id: str, video_format: str = "16:9",
                                  avatar_style: str = "normal", avatar_id: str = "",
                                  heygen_engine: str = "avatar_iv",
                                  started_at: int = None) -> str:
    """
    Создаёт video ResultNode со status=processing (до того как видео готово).
    Возвращает node_id созданного узла или пустую строку при ошибке.
    """
    try:
        import time as _time
        with Session(engine) as session:
            # Не создаём повторно, если уже есть
            stmt = select(ResultNode).where(
                ResultNode.slug == slug,
                ResultNode.node_type == "video"
            )
            existing = session.exec(stmt).first()
            if existing:
                return existing.node_id

            audio_stmt = select(ResultNode).where(
                ResultNode.slug == slug,
                ResultNode.node_type == "audio"
            ).order_by(ResultNode.position)
            audio_node = session.exec(audio_stmt).first()
            if not audio_node:
                return ""

            stats = {
                "model": "heygen_v2",
                "avatar_id": avatar_id,
                "avatar_style": avatar_style,
                "video_id": video_id,
                "status": "processing",
                "started_at": started_at or int(_time.time()),
            }
            params = {
                "video_format": video_format,
                "avatar_style": avatar_style,
                "avatar_id": avatar_id,
                "heygen_engine": heygen_engine,
            }
            new_node = ResultNode(
                slug=slug,
                parent_node_id=audio_node.node_id,
                node_type="video",
                title="Видео #1",
                status="processing",
                position=0,
                params_json=json.dumps(params, ensure_ascii=False),
                stats_json=json.dumps(stats, ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
            session.add(new_node)
            session.commit()
            session.refresh(new_node)
            return new_node.node_id
    except Exception as e:
        print(f"Error create_processing_video_node: {e}")
        return ""
