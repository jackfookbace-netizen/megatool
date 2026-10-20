import os
import time
import hashlib
import hmac
import re
from typing import Optional, Dict

from app.database import get_user_by_email, create_user

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "megatool-secret-key-2026-auth-secure")
STORE_INVITE_CODE = os.environ.get("STORE_INVITE_CODE", "MEGATOOL-2026").strip()
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "jackfookbace@gmail.com").strip().lower()
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "megatool2026").strip()

def hash_password(password: str, salt: str = "megatool_secure_salt_2026") -> str:
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

def is_valid_email(email: str) -> bool:
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return bool(re.match(pattern, email.strip()))

def ensure_initial_admin():
    # Ensure owner exists in database
    existing = get_user_by_email(ADMIN_EMAIL)
    if not existing:
        create_user(
            email=ADMIN_EMAIL,
            name="เจ้าของร้าน (Jack)",
            password_hash=hash_password(ADMIN_PASS),
            role="member"
        )

# Ensure owner is registered
try:
    ensure_initial_admin()
except Exception:
    pass

def register_user(email: str, name: str, password: str, invite_code: str) -> Dict:
    clean_email = email.strip().lower()
    clean_name = name.strip()
    clean_pass = password.strip()
    clean_code = invite_code.strip()
    
    # 1. Validate invite code
    if clean_code != STORE_INVITE_CODE:
        raise ValueError("รหัสเชิญชวนของร้าน (Invite Code) ไม่ถูกต้อง กรุณาติดต่อเจ้าของร้าน")
        
    # 2. Validate email format
    if not is_valid_email(clean_email):
        raise ValueError("รูปแบบอีเมลไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง")
        
    # 3. Validate name
    if len(clean_name) < 2:
        raise ValueError("กรุณากรอกชื่ออย่างน้อย 2 ตัวอักษร")
        
    # 4. Validate password length
    if len(clean_pass) < 6:
        raise ValueError("รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร")
        
    # 5. Check duplicate email
    if get_user_by_email(clean_email):
        raise ValueError("อีเมลนี้ถูกลงทะเบียนไว้ในระบบแล้ว กรุณาเข้าสู่ระบบ")
        
    # Create user
    pw_hash = hash_password(clean_pass)
    user = create_user(clean_email, clean_name, pw_hash, role="member")
    return {
        "email": user["email"],
        "name": user["name"],
        "role": user["role"]
    }

def verify_user(email: str, password: str) -> Optional[Dict]:
    clean_email = email.strip().lower()
    clean_pass = password.strip()
    
    user = get_user_by_email(clean_email)
    if not user:
        return None
        
    if user["password_hash"] == hash_password(clean_pass):
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
            
        user = get_user_by_email(email)
        display_name = user["name"] if user else email.split("@")[0].capitalize()
        
        return {
            "email": email,
            "role": role,
            "name": display_name,
            "exp": exp
        }
    except Exception:
        return None
