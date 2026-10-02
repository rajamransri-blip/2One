import os
import sqlite3
import secrets
import hashlib
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB = os.getenv("DATABASE_PATH", "data/cloud.db")

app = FastAPI(
    title="Cloud Control",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

def time_now():
    return datetime.now(timezone.utc).isoformat()

def connection():
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def digest(value):
    return hashlib.sha256(
        value.encode()
    ).hexdigest()

def initialize():
    c = connection()

    c.execute("""
    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_hash TEXT UNIQUE NOT NULL,
        token_prefix TEXT NOT NULL,
        token_type TEXT NOT NULL,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    c.execute("""
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
        last_seen TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_id INTEGER,
        action TEXT,
        ip TEXT,
        created_at TEXT NOT NULL
    )
    """)

    c.commit()
    c.close()

initialize()

class TokenRequest(BaseModel):
    type: str
    name: str = "Application"

class DeviceRequest(BaseModel):
    device_id: str
    device_name: str = "Unknown"
    platform: str = "Unknown"
    app_name: str = "Unknown"
    app_version: str = "1.0"

def authenticate(authorization):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization"
        )

    raw = authorization[7:].strip()

    c = connection()

    row = c.execute(
        """
        SELECT *
        FROM tokens
        WHERE token_hash=?
        AND active=1
        """,
        (digest(raw),)
    ).fetchone()

    c.close()

    if not row:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked token"
        )

    return row

@app.get("/")
async def root():
    return {
        "service": "Cloud Control",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "time": time_now()
    }

@app.get("/api/v1/server")
async def server(
    authorization: str | None = Header(default=None)
):
    token = authenticate(authorization)

    return {
        "success": True,
        "server": "Cloud Control",
        "status": "online",
        "token_type": token["token_type"],
        "time": time_now()
    }

@app.post("/api/v1/tokens")
async def create_token(
    request: TokenRequest,
    x_admin_key: str | None = Header(default=None)
):
    admin = os.getenv("ADMIN_KEY", "")

    if admin and x_admin_key != admin:
        raise HTTPException(
            status_code=403,
            detail="Admin key required"
        )

    token_type = request.type.lower()

    if token_type not in (
        "python",
        "supabase",
        "firebase"
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid token type"
        )

    raw = (
        "cc_live_" +
        secrets.token_urlsafe(32)
    )

    c = connection()

    cur = c.execute(
        """
        INSERT INTO tokens
        (
            token_hash,
            token_prefix,
            token_type,
            name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            digest(raw),
            raw[:18],
            token_type,
            request.name,
            time_now()
        )
    )

    token_id = cur.lastrowid

    c.commit()
    c.close()

    return {
        "success": True,
        "token": raw,
        "token_id": token_id,
        "type": token_type,
        "name": request.name
    }

@app.get("/api/v1/tokens")
async def tokens(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    c = connection()

    rows = c.execute(
        """
        SELECT id,
               token_prefix,
               token_type,
               name,
               active,
               created_at
        FROM tokens
        ORDER BY id DESC
        """
    ).fetchall()

    c.close()

    return {
        "success": True,
        "tokens": [dict(x) for x in rows]
    }

@app.delete("/api/v1/tokens/{token_id}")
async def revoke(
    token_id: int,
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    c = connection()

    cur = c.execute(
        """
        UPDATE tokens
        SET active=0
        WHERE id=?
        """,
        (token_id,)
    )

    c.commit()
    c.close()

    if cur.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail="Token not found"
        )

    return {
        "success": True,
        "status": "revoked"
    }

@app.post("/api/v1/devices/register")
async def register(
    request: Request,
    body: DeviceRequest,
    authorization: str | None = Header(default=None)
):
    token = authenticate(authorization)

    client_ip = ""

    if request.client:
        client_ip = request.client.host

    c = connection()

    existing = c.execute(
        """
        SELECT id
        FROM devices
        WHERE device_id=?
        AND token_id=?
        """,
        (
            body.device_id,
            token["id"]
        )
    ).fetchone()

    if existing:

        c.execute(
            """
            UPDATE devices
            SET device_name=?,
                platform=?,
                app_name=?,
                app_version=?,
                ip=?,
                last_seen=?
            WHERE id=?
            """,
            (
                body.device_name,
                body.platform,
                body.app_name,
                body.app_version,
                client_ip,
                time_now(),
                existing["id"]
            )
        )

    else:

        c.execute(
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
                body.device_id,
                body.device_name,
                body.platform,
                body.app_name,
                body.app_version,
                client_ip,
                token["id"],
                time_now(),
                time_now()
            )
        )

    c.commit()
    c.close()

    return {
        "success": True,
        "device_id": body.device_id,
        "status": "connected"
    }

@app.get("/api/v1/devices")
async def devices(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    c = connection()

    rows = c.execute(
        """
        SELECT id,
               device_id,
               device_name,
               platform,
               app_name,
               app_version,
               ip,
               first_seen,
               last_seen
        FROM devices
        ORDER BY id DESC
        """
    ).fetchall()

    c.close()

    return {
        "success": True,
        "devices": [dict(x) for x in rows]
    }

@app.get("/api/v1/services")
async def services(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    return {
        "success": True,
        "services": {
            "python": True,
            "supabase": bool(
                os.getenv("SUPABASE_URL")
            ),
            "firebase": bool(
                os.getenv("FIREBASE_PROJECT_ID")
            )
        }
    }

@app.get("/api/v1/logs")
async def logs(
    authorization: str | None = Header(default=None)
):
    authenticate(authorization)

    c = connection()

    rows = c.execute(
        """
        SELECT *
        FROM logs
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()

    c.close()

    return {
        "success": True,
        "logs": [dict(x) for x in rows]
    }
