import os
import time
import hashlib
import hmac
from typing import Optional, Dict

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "megatool-secret-key-2026-auth-secure")

# Sole authorized owner email
AUTHORIZED_EMAIL = os.environ.get("ADMIN_EMAIL", "jackfookbace@gmail.com").strip().lower()

# PBKDF2-HMAC-SHA256 (100,000 iterations) Salted Hash
# Even with access to the server/code, the plaintext password CANNOT be reversed or stolen.
SALT = b"megatool_exclusive_vault_salt_2026"
ENCRYPTED_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    "0cf917bc826fde0c0a7b561a3f1d1154982783a2e96aebd4ff80aeb512039c12"
)

def compute_secure_hash(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, 100000).hex()

def verify_user(email: str, password: str) -> Optional[Dict]:
    clean_email = email.strip().lower()
    clean_pass = password.strip()
    
    # 1. Strictly allow only the owner's email
    if clean_email != AUTHORIZED_EMAIL:
        return None
        
    # 2. Verify encrypted password hash in constant time
    input_hash = compute_secure_hash(clean_pass)
    if hmac.compare_digest(input_hash, ENCRYPTED_PASSWORD_HASH):
        return {
            "email": clean_email,
            "name": "เจ้าของร้าน (Jack)",
            "role": "owner"
        }
    return None

def create_token(user: Dict, remember_me: bool = True) -> str:
    # 30 days if remember_me, else 1 day
    duration = (30 * 24 * 3600) if remember_me else (24 * 3600)
    exp = int(time.time()) + duration
    payload = f"{user['email']}:{user['role']}:{exp}"
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
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
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
            
        # Ensure token belongs to the authorized email
        if email.strip().lower() != AUTHORIZED_EMAIL:
            return None
            
        return {
            "email": email,
            "role": role,
            "name": "เจ้าของร้าน (Jack)",
            "exp": exp
        }
    except Exception:
        return None
