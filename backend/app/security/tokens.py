"""Local auth primitives; only the backend possesses signing material."""
import hashlib
import hmac
import secrets
from datetime import timedelta
import jwt
from fastapi import HTTPException
from app.models.db import now


def password_hash(password: str):
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + salt.hex() + "$" + key.hex()


def verify_password(password: str, encoded: str | None):
    if not encoded:
        return False
    try:
        algorithm, rounds, salt, key = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(candidate, bytes.fromhex(key))
    except (ValueError, TypeError):
        return False


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def access_token(user, secret: str):
    issued = now()
    return jwt.encode({"sub": user.id, "role": user.role, "iat": issued, "exp": issued + timedelta(minutes=15), "type": "access"}, secret, algorithm="HS256")


def service_token(user, secret: str):
    issued = now()
    return jwt.encode({"sub": user.id, "role": "child", "scope": "location",
                       "iat": issued, "exp": issued + timedelta(minutes=15), "type": "service"}, secret, algorithm="HS256")


def decode_token(value: str, secret: str, expected_type="access"):
    try:
        claims = jwt.decode(value, secret, algorithms=["HS256"], options={"require": ["sub", "iat", "exp", "type"]})
        if claims["type"] != expected_type:
            raise ValueError("Wrong token type")
        if expected_type == "service" and (claims.get("role") != "child" or claims.get("scope") != "location"):
            raise ValueError("Wrong service scope")
        return claims
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid or expired access token") from None
