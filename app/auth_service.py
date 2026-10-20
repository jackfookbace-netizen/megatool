import os
import json
import time
import hashlib
import hmac
import re
from typing import Optional, Dict

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "megatool-secret-key-2026-auth-secure")
STORE_PASSWORD = os.environ.get("STORE_PASSWORD", "megatool2026").strip()

def hash_password(password: str, salt: str = "megatool_secure_salt_2026") -> str:
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

def is_valid_email(email: str) -> bool:
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return bool(re.match(pattern, email.strip()))

def verify_user(email: str, password: str) -> Optional[Dict]:
    email_clean = email.strip().lower()
    pass_clean = password.strip()
    
    # Check if email is valid format
    if not is_valid_email(email_clean):
        return None
        
    # Check password matches store/team password
    if pass_clean == STORE_PASSWORD:
        # Extract display name from email (e.g. jack from jack@gmail.com)
        name_part = email_clean.split("@")[0].capitalize()
        return {
            "email": email_clean,
            "name": f"ทีมงาน ({name_part})",
            "role": "member"
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
            
        name_part = email.split("@")[0].capitalize()
        return {
            "email": email,
            "role": role,
            "name": f"ทีมงาน ({name_part})",
            "exp": exp
        }
    except Exception:
        return None
