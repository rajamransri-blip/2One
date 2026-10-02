import os
import sqlite3
import secrets
import hashlib
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_NAME = "Cloud Control Server"
DB_PATH = os.getenv("DATABASE_PATH", "data/cloud.db")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    description="Universal token based cloud control API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_token(token: str):
    return hashlib.sha256(token.encode()).hexdigest()

def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            token_prefix TEXT NOT NULL,
            token_type TEXT NOT NULL,
            name TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            device_name TEXT,
            platform TEXT,
            app_name TEXT,
            app_version TEXT,
            ip TEXT,
            token_id INTEGER,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            FOREIGN KEY(token_id) REFERENCES tokens(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id INTEGER,
            action TEXT,
            ip TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

init_db()

class TokenCreate(BaseModel):
    type: str
    name: str = "Application"

class DeviceRegister(BaseModel):
    device_id: str
    device_name: str = "Unknown device"
    platform: str = "Unknown"
    app_name: str = "Unknown"
    app_version: str = "1.0"

def allowed_types():
    return {
        "python",
        "supabase",
        "firebase"
    }

def authenticate(authorization: str | None):
    if not authorization:
        raise HTTPException(401, "Authorization token required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Use Bearer token")

    raw = authorization[7:].strip()

    if not raw:
        raise HTTPException(401, "Invalid token")

    token_hash = hash_token(raw)

    conn = db()
    row = conn.execute(
        """
        SELECT * FROM tokens
        WHERE token_hash=? AND active=1
        """,
        (token_hash,)
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(401, "Invalid or revoked token")

    return row

@app.get("/")
async def root():
    return {
        "service": APP_NAME,
        "version": "1.0.0",
        "status": "online"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": APP_NAME,
        "time": now()
    }

@app.get("/api/v1/server")
async def server_info(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    return {
        "name": APP_NAME,
        "status": "online",
        "api": "v1",
        "time": now()
    }

@app.post("/api/v1/tokens")
async def create_token(
    request: TokenCreate,
    x_admin_key: str | None = Header(default=None)
):
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "Admin key required")

    token_type = request.type.lower().strip()

    if token_type not in allowed_types():
        raise HTTPException(
            400,
            "type must be python, supabase or firebase"
        )

    raw = "cc_live_" + secrets.token_urlsafe(32)
    token_hash = hash_token(raw)

    conn = db()

    cursor = conn.execute(
        """
        INSERT INTO tokens
        (token_hash, token_prefix, token_type, name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            token_hash,
            raw[:18],
            token_type,
            request.name,
            now()
        )
    )

    token_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": raw,
        "token_id": token_id,
        "type": token_type,
        "name": request.name,
        "warning": "Store this token securely. It will not be returned again."
    }

@app.get("/api/v1/tokens")
async def list_tokens(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    conn = db()
    rows = conn.execute(
        """
        SELECT id, token_prefix, token_type,
               name, active, created_at
        FROM tokens
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()

    return {
        "success": True,
        "tokens": [dict(x) for x in rows]
    }

@app.delete("/api/v1/tokens/{token_id}")
async def revoke_token(
    token_id: int,
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    conn = db()
    cursor = conn.execute(
        "UPDATE tokens SET active=0 WHERE id=?",
        (token_id,)
    )
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        raise HTTPException(404, "Token not found")

    return {
        "success": True,
        "token_id": token_id,
        "status": "revoked"
    }

@app.post("/api/v1/devices/register")
async def register_device(
    request: DeviceRegister,
    authorization: str | None = Header(default=None)
):
    token = authenticate(authorization)

    # Server-side client IP.
    # The application can additionally provide metadata.
    conn = db()

    existing = conn.execute(
        """
        SELECT id FROM devices
        WHERE device_id=? AND token_id=?
        """,
        (request.device_id, token["id"])
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE devices
            SET device_name=?,
                platform=?,
                app_name=?,
                app_version=?,
                last_seen=?
            WHERE id=?
            """,
            (
                request.device_name,
                request.platform,
                request.app_name,
                request.app_version,
                now(),
                existing["id"]
            )
        )
    else:
        conn.execute(
            """
            INSERT INTO devices
            (
                device_id,
                device_name,
                platform,
                app_name,
                app_version,
                ip,
                token_id,
                first_seen,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.device_id,
                request.device_name,
                request.platform,
                request.app_name,
                request.app_version,
                "",
                token["id"],
                now(),
                now()
            )
        )

    conn.execute(
        """
        INSERT INTO logs(token_id, action, ip, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            token["id"],
            "device_register",
            "",
            now()
        )
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "device_id": request.device_id,
        "status": "connected"
    }

@app.get("/api/v1/devices")
async def devices(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    conn = db()
    rows = conn.execute(
        """
        SELECT id, device_id, device_name,
               platform, app_name, app_version,
               first_seen, last_seen
        FROM devices
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()

    return {
        "success": True,
        "devices": [dict(x) for x in rows]
    }

@app.get("/api/v1/logs")
async def logs(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    conn = db()
    rows = conn.execute(
        """
        SELECT id, token_id, action,
               ip, created_at
        FROM logs
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()
    conn.close()

    return {
        "success": True,
        "logs": [dict(x) for x in rows]
    }

@app.get("/api/v1/services")
async def services(
    authorization: str | None = Header(default=None)
):
    token = authenticate(authorization)

    return {
        "success": True,
        "token_type": token["token_type"],
        "services": {
            "python": True,
            "supabase": bool(os.getenv("SUPABASE_URL")),
            "firebase": bool(os.getenv("FIREBASE_PROJECT_ID"))
        }
    }
