import sqlite3
import os
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

def get_db_path():
    return DB_PATH
