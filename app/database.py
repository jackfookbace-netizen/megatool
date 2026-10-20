import os
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "megatool.db")
BACKUP_PATH = os.path.join(DATA_DIR, "users_backup.json")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    
    # Check if backup exists to restore
    cursor.execute("SELECT COUNT(*) as count FROM users")
    count = cursor.fetchone()["count"]
    if count == 0 and os.path.exists(BACKUP_PATH):
        try:
            with open(BACKUP_PATH, "r", encoding="utf-8") as f:
                saved_users = json.load(f)
                for u in saved_users:
                    cursor.execute("""
                    INSERT OR IGNORE INTO users (email, name, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """, (u["email"].lower().strip(), u["name"], u["password_hash"], u.get("role", "member"), u.get("created_at", datetime.now().isoformat())))
                conn.commit()
        except Exception:
            pass
    conn.close()

def backup_users_to_file():
    try:
        users = get_all_users()
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_all_users() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, password_hash, role, created_at FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_by_email(email: str) -> Optional[Dict]:
    if not email:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, password_hash, role, created_at FROM users WHERE email = ?", (email.strip().lower(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(email: str, name: str, password_hash: str, role: str = "member") -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO users (email, name, password_hash, role, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (email.strip().lower(), name.strip(), password_hash, role, created_at))
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    
    backup_users_to_file()
    return {
        "id": user_id,
        "email": email.strip().lower(),
        "name": name.strip(),
        "role": role,
        "created_at": created_at
    }

# Initialize on module load
init_db()
