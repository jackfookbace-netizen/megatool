import os
import json
import time
import hashlib
import hmac
from typing import Optional, Dict

AUTH_FILE = os.path.join(os.path.dirname(__file__), "users.json")
SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "megatool-secret-key-2026-auth-secure")

def hash_password(password: str, salt: str = "megatool_salt") -> str:
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

# Initial default users if not present
DEFAULT_USERS = {
    "admin": {
        "username": "admin",
        "name": "เจ้าของร้าน (Admin)",
        "password_hash": hash_password("megatool2026"),
        "role": "admin"
    },
    "staff": {
        "username": "staff",
        "name": "ทีมงาน Megatool",
        "password_hash": hash_password("staff1234"),
        "role": "staff"
    }
}

def load_users() -> Dict:
    if not os.path.exists(AUTH_FILE):
        save_users(DEFAULT_USERS)
        return DEFAULT_USERS
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_USERS

def save_users(users: Dict):
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def verify_user(username: str, password: str) -> Optional[Dict]:
    users = load_users()
    user = users.get(username.strip().lower())
    if not user:
        return None
    if user.get("password_hash") == hash_password(password.strip()):
        return {
            "username": user["username"],
            "name": user["name"],
            "role": user["role"]
        }
    return None

def create_token(user: Dict, remember_me: bool = True) -> str:
    # Expiry: 30 days if remember_me, else 1 day
    duration = 30 * 24 * 3600 if remember_me else 24 * 3600
    exp = int(time.time()) + duration
    payload = f"{user['username']}:{user['role']}:{exp}"
    signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def verify_token(token: str) -> Optional[Dict]:
    if not token or ":" not in token:
        return None
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        username, role, exp_str, sig = parts
        exp = int(exp_str)
        if time.time() > exp:
            return None  # Expired
            
        payload = f"{username}:{role}:{exp_str}"
        expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
            
        users = load_users()
        user_info = users.get(username)
        display_name = user_info.get("name") if user_info else username
        
        return {
            "username": username,
            "role": role,
            "name": display_name,
            "exp": exp
        }
    except Exception:
        return None
