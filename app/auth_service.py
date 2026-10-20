import os
import json
import time
import hashlib
import hmac
from typing import Optional, Dict

AUTH_FILE = os.path.join(os.path.dirname(__file__), "users.json")
SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "megatool-secret-key-2026-auth-secure")

def hash_password(password: str, salt: str = "megatool_secure_salt_2026") -> str:
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

# Load initial or environment-configured accounts
def get_system_users() -> Dict:
    admin_email = os.environ.get("ADMIN_EMAIL", "jackfookbace@gmail.com").strip().lower()
    admin_pass = os.environ.get("ADMIN_PASSWORD", "megatool2026").strip()
    
    staff_email = os.environ.get("STAFF_EMAIL", "staff@megatool.com").strip().lower()
    staff_pass = os.environ.get("STAFF_PASSWORD", "staff1234").strip()
    
    default_users = {
        admin_email: {
            "email": admin_email,
            "name": "เจ้าของร้าน (Admin)",
            "password_hash": hash_password(admin_pass),
            "role": "admin"
        },
        staff_email: {
            "email": staff_email,
            "name": "ทีมงาน Megatool",
            "password_hash": hash_password(staff_pass),
            "role": "staff"
        }
    }
    
    # If users.json exists locally, merge custom added staff members
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_users.update(saved)
        except Exception:
            pass
            
    return default_users

def verify_user(email_or_user: str, password: str) -> Optional[Dict]:
    users = get_system_users()
    identifier = email_or_user.strip().lower()
    user = users.get(identifier)
    
    # Also allow matching by email property if key differs
    if not user:
        for u in users.values():
            if u.get("email", "").lower() == identifier:
                user = u
                break
                
    if not user:
        return None
        
    if user.get("password_hash") == hash_password(password.strip()):
        return {
            "email": user["email"],
            "name": user["name"],
            "role": user["role"]
        }
    return None

def create_token(user: Dict, remember_me: bool = True) -> str:
    # 30 days if remember_me, else 1 day
    duration = 30 * 24 * 3600 if remember_me else 24 * 3600
    exp = int(time.time()) + duration
    payload = f"{user['email']}:{user['role']}:{exp}"
    signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def verify_token(token: str) -> Optional[Dict]:
    if not token or ":" not in token:
        return None
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        email, role, exp_str, sig = parts
        exp = int(exp_str)
        if time.time() > exp:
            return None  # Expired
            
        payload = f"{email}:{role}:{exp_str}"
        expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
            
        users = get_system_users()
        user_info = users.get(email.lower())
        display_name = user_info.get("name") if user_info else email
        
        return {
            "email": email,
            "role": role,
            "name": display_name,
            "exp": exp
        }
    except Exception:
        return None
