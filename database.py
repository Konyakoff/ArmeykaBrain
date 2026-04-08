import sqlite3
import os
import json
from datetime import datetime

DB_DIR = "db"
DB_PATH = os.path.join(DB_DIR, "dialogs.db")

def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            user_id INTEGER,
            username TEXT,
            direction TEXT,
            text TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE,
            question TEXT,
            step1_info TEXT,
            answer TEXT,
            timestamp DATETIME,
            char_count INTEGER,
            tab_type TEXT DEFAULT 'text'
        )
    """)
    
    # Пытаемся добавить колонки, если таблица была создана ранее без них
    try:
        cursor.execute("ALTER TABLE saved_results ADD COLUMN tab_type TEXT DEFAULT 'text'")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE saved_results ADD COLUMN step3_audio TEXT")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE saved_results ADD COLUMN step4_audio_url TEXT")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE saved_results ADD COLUMN additional_audios TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

def log_message(user_id: int, username: str, direction: str, text: str):
    if not text:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO messages (timestamp, user_id, username, direction, text)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id, username or "", direction, text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging message: {e}")

def save_result(question: str, step1_info: str, answer: str, tab_type: str = 'text', step3_audio: str = None, step4_audio_url: str = None) -> str:
    """Сохраняет результат и генерирует уникальный slug (YYMMDD-XXXXX)."""
    try:
        now = datetime.now()
        date_prefix = now.strftime("%y%m%d")
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        char_count = len(answer)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Получаем количество записей за сегодня, чтобы сгенерировать номер
        cursor.execute("SELECT COUNT(*) FROM saved_results WHERE slug LIKE ?", (f"{date_prefix}-%",))
        count_today = cursor.fetchone()[0]
        
        slug = f"{date_prefix}-{(count_today + 1):05d}"
        
        cursor.execute("""
            INSERT INTO saved_results (slug, question, step1_info, answer, timestamp, char_count, tab_type, step3_audio, step4_audio_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (slug, question, step1_info, answer, timestamp_str, char_count, tab_type, step3_audio, step4_audio_url))
        
        conn.commit()
        conn.close()
        return slug
    except Exception as e:
        print(f"Error saving result: {e}")
        return ""

def get_result_by_slug(slug: str) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM saved_results WHERE slug = ?", (slug,))
        row = cursor.fetchone()
        conn.close()
        if row:
            res_dict = dict(row)
            # Если есть дополнительные аудио, распарсим их
            if "additional_audios" in res_dict and res_dict["additional_audios"]:
                try:
                    res_dict["additional_audios_list"] = json.loads(res_dict["additional_audios"])
                except:
                    res_dict["additional_audios_list"] = []
            else:
                res_dict["additional_audios_list"] = []
            return res_dict
        return None
    except Exception as e:
        print(f"Error getting result: {e}")
        return None

def add_additional_audio(slug: str, audio_data: dict) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT additional_audios FROM saved_results WHERE slug = ?", (slug,))
        row = cursor.fetchone()
        if not row:
            return False
            
        current_list = []
        if row[0]:
            try:
                current_list = json.loads(row[0])
            except:
                pass
                
        # Добавляем в начало списка
        current_list.insert(0, audio_data)
        
        cursor.execute("""
            UPDATE saved_results 
            SET additional_audios = ? 
            WHERE slug = ?
        """, (json.dumps(current_list, ensure_ascii=False), slug))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error adding additional audio: {e}")
        return False

def get_recent_results(limit: int = 50, tab_type: str = 'text') -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT slug, question, timestamp, char_count FROM saved_results WHERE tab_type = ? ORDER BY id DESC LIMIT ?", (tab_type, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error getting recent results: {e}")
        return []

def get_db_path():
    return DB_PATH
