"""PTv Cloud Control FastAPI server."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "PTv"
APP_VERSION = "2.0.0"
DB = os.getenv("DATABASE_PATH", "data/cloud.db")
STARTED_AT = time.monotonic()

app = FastAPI(title=f"{APP_NAME} Cloud Control API", version=APP_VERSION)

allowed_origins = [
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "*").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    name: str = Field(default="PTv Application", min_length=1, max_length=100)


class DeviceRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    device_name: str = Field(default="Unknown", max_length=100)
    platform: str = Field(default="Unknown", max_length=50)
    app_name: str = Field(default=APP_NAME, max_length=100)
    app_version: str = Field(default=APP_VERSION, max_length=30)


class ProvisionRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    device_name: str = Field(default="PTv Mobile", max_length=100)
    platform: str = Field(default="Android", max_length=50)
    app_version: str = Field(default=APP_VERSION, max_length=30)
    token_type: str = Field(default="python", max_length=32)


class SQLRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)
    params: list[Any] = Field(default_factory=list, max_length=50)


def time_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection() -> sqlite3.Connection:
    path = Path(DB)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def initialize() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT UNIQUE NOT NULL,
                token_prefix TEXT NOT NULL,
                token_type TEXT NOT NULL,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                device_name TEXT,
                platform TEXT,
                app_name TEXT,
                app_version TEXT,
                ip TEXT,
                token_id INTEGER NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(device_id, token_id)
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id INTEGER,
                action TEXT NOT NULL,
                ip TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                ip TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


initialize()


def log_event(token_id: int | None, action: str, ip: str = "") -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO logs(token_id, action, ip, created_at) VALUES (?, ?, ?, ?)",
            (token_id, action, ip, time_now()),
        )


def authenticate(authorization: str | None) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Bearer token required")
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM tokens WHERE token_hash = ? AND active = 1",
            (digest(raw),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")
    return row


def require_admin(x_admin_key: str | None) -> None:
    configured = os.getenv("ADMIN_KEY", "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_KEY is not configured on the server",
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(status_code=403, detail="Valid X-Admin-Key required")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def provision_allowed(device_id: str, ip: str) -> bool:
    """Limit public provisioning to five requests per device/IP per hour."""
    since = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    with connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM provision_events WHERE device_id = ? AND ip = ? AND created_at >= ?",
            (device_id, ip, since),
        ).fetchone()[0]
    return count < 5


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": APP_NAME, "status": "online", "version": APP_VERSION}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "healthy", "service": APP_NAME, "time": time_now()}


@app.get("/api/v1/server")
def server_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authenticate(authorization)
    return {
        "success": True,
        "server": APP_NAME,
        "status": "online",
        "token_type": token["token_type"],
        "time": time_now(),
    }


@app.post("/api/v1/provision")
def provision(body: ProvisionRequest, request: Request) -> dict[str, Any]:
    """Create a scoped PTv token for the mobile app without an app login."""
    ip = client_ip(request)
    if not provision_allowed(body.device_id, ip):
        raise HTTPException(status_code=429, detail="Provisioning limit reached; try again later")
    token_type = body.token_type.lower().strip()
    if token_type not in {"python", "supabase"}:
        raise HTTPException(status_code=400, detail="token_type must be python or supabase")
    raw = "ptv_live_" + secrets.token_urlsafe(32)
    now = time_now()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO tokens(token_hash, token_prefix, token_type, name, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest(raw), raw[:18], token_type, f"PTv {body.device_name}"[:100], now),
        )
        token_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO provision_events(device_id, ip, created_at) VALUES (?, ?, ?)",
            (body.device_id, ip, now),
        )
    log_event(token_id, "mobile_provisioned", ip)
    return {
        "success": True,
        "token": raw,
        "token_id": token_id,
        "type": token_type,
        "device_id": body.device_id,
        "message": "PTv mobile token created; store it securely",
    }


@app.get("/api/v1/dashboard")
def dashboard(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return a token-scoped operational summary for the PTv home screen."""
    token = authenticate(authorization)
    with connection() as conn:
        devices = conn.execute(
            "SELECT COUNT(*) FROM devices WHERE token_id = ?", (token["id"],)
        ).fetchone()[0]
        logs = conn.execute(
            "SELECT COUNT(*) FROM logs WHERE token_id = ?", (token["id"],)
        ).fetchone()[0]
        tokens = conn.execute("SELECT COUNT(*) FROM tokens WHERE active = 1").fetchone()[0]
    log_event(token["id"], "dashboard_viewed", client_ip(request))
    return {
        "success": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "online",
        "summary": {"devices": devices, "logs": logs, "tokens": tokens},
        "uptime_seconds": round(time.monotonic() - STARTED_AT, 1),
        "time": time_now(),
    }


@app.get("/api/v1/diagnostics")
def diagnostics(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return safe runtime diagnostics without exposing secrets or DB paths."""
    token = authenticate(authorization)
    db_ok = True
    try:
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        db_ok = False
    log_event(token["id"], "diagnostics_viewed", client_ip(request))
    return {
        "success": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "checks": {
            "api": True,
            "database": db_ok,
            "supabase_configured": bool(os.getenv("SUPABASE_URL")),
            "firebase_configured": bool(os.getenv("FIREBASE_PROJECT_ID")),
            "admin_configured": bool(os.getenv("ADMIN_KEY", "").strip()),
        },
        "uptime_seconds": round(time.monotonic() - STARTED_AT, 1),
        "time": time_now(),
    }


@app.get("/api/v1/database/tables")
def database_tables(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authenticate(authorization)
    with connection() as conn:
        rows = conn.execute(
            """SELECT name, type FROM sqlite_master
               WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
               ORDER BY name"""
        ).fetchall()
    log_event(token["id"], "database_tables_viewed", client_ip(request))
    return {"success": True, "tables": [dict(row) for row in rows]}


@app.post("/api/v1/sql")
def execute_sql(
    body: SQLRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Execute one controlled SQLite statement for the connected PTv workspace."""
    token = authenticate(authorization)
    sql = body.sql.strip()
    first_word = sql.split(None, 1)[0].upper() if sql else ""
    blocked = {"ATTACH", "DETACH", "VACUUM", "PRAGMA", "REINDEX", "ANALYZE"}
    allowed = {"SELECT", "WITH", "CREATE", "INSERT", "UPDATE", "DELETE", "ALTER", "DROP"}
    if ";" in sql.rstrip(";"):
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed")
    if first_word in blocked or first_word not in allowed:
        raise HTTPException(status_code=400, detail="Only safe data and table SQL is allowed")
    try:
        with connection() as conn:
            cursor = conn.execute(sql, body.params)
            if first_word in {"SELECT", "WITH"}:
                rows = cursor.fetchmany(500)
                result = {"columns": [item[0] for item in cursor.description or []], "rows": [dict(row) for row in rows]}
            else:
                result = {"affected_rows": cursor.rowcount, "message": "SQL executed successfully"}
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}") from exc
    log_event(token["id"], "sql_executed", client_ip(request))
    return {"success": True, "statement": first_word, **result}


@app.post("/api/v1/tokens")
def create_token(
    body: TokenRequest,
    request: Request,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_key)
    token_type = body.type.lower().strip()
    if token_type not in {"python", "supabase", "firebase"}:
        raise HTTPException(status_code=400, detail="type must be python, supabase, or firebase")
    raw = "ptv_live_" + secrets.token_urlsafe(32)
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO tokens(token_hash, token_prefix, token_type, name, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest(raw), raw[:18], token_type, body.name.strip(), time_now()),
        )
        token_id = cursor.lastrowid
    log_event(token_id, "token_created", client_ip(request))
    return {"success": True, "token": raw, "token_id": token_id, "type": token_type, "name": body.name.strip()}


@app.get("/api/v1/tokens")
def list_tokens(
    request: Request,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_key)
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, token_prefix, token_type, name, active, created_at FROM tokens ORDER BY id DESC"
        ).fetchall()
    log_event(None, "tokens_listed", client_ip(request))
    return {"success": True, "tokens": [dict(row) for row in rows]}


@app.delete("/api/v1/tokens/{token_id}")
def revoke_token(
    token_id: int,
    request: Request,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(x_admin_key)
    with connection() as conn:
        cursor = conn.execute("UPDATE tokens SET active = 0 WHERE id = ?", (token_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Token not found")
    log_event(token_id, "token_revoked", client_ip(request))
    return {"success": True, "status": "revoked", "token_id": token_id}


@app.post("/api/v1/devices/register")
def register_device(
    body: DeviceRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authenticate(authorization)
    now = time_now()
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM devices WHERE device_id = ? AND token_id = ?",
            (body.device_id, token["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE devices SET device_name = ?, platform = ?, app_name = ?,
                   app_version = ?, ip = ?, last_seen = ? WHERE id = ?""",
                (body.device_name, body.platform, body.app_name, body.app_version,
                 client_ip(request), now, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO devices(device_id, device_name, platform, app_name, app_version,
                   ip, token_id, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (body.device_id, body.device_name, body.platform, body.app_name, body.app_version,
                 client_ip(request), token["id"], now, now),
            )
    log_event(token["id"], "device_registered", client_ip(request))
    return {"success": True, "device_id": body.device_id, "status": "connected"}


@app.get("/api/v1/devices")
def list_devices(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authenticate(authorization)
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, device_id, device_name, platform, app_name, app_version, ip, first_seen, last_seen
               FROM devices WHERE token_id = ? ORDER BY id DESC""",
            (token["id"],),
        ).fetchall()
    log_event(token["id"], "devices_listed", client_ip(request))
    return {"success": True, "devices": [dict(row) for row in rows]}


@app.get("/api/v1/services")
def services(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authenticate(authorization)
    log_event(token["id"], "services_viewed", client_ip(request))
    return {
        "success": True,
        "services": {
            "python": {"enabled": True, "status": "ready", "label": "Python API"},
            "supabase": {
                "enabled": bool(os.getenv("SUPABASE_URL")),
                "status": "configured" if os.getenv("SUPABASE_URL") else "not_configured",
                "database": bool(os.getenv("SUPABASE_URL")),
                "storage": bool(os.getenv("SUPABASE_URL")),
            },
            "firebase": {
                "enabled": bool(os.getenv("FIREBASE_PROJECT_ID")),
                "status": "configured" if os.getenv("FIREBASE_PROJECT_ID") else "not_configured",
                "database": bool(os.getenv("FIREBASE_PROJECT_ID")),
                "storage": bool(os.getenv("FIREBASE_PROJECT_ID")),
            },
        },
    }


@app.get("/api/v1/logs")
def list_logs(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authenticate(authorization)
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, token_id, action, ip, created_at FROM logs WHERE token_id = ? ORDER BY id DESC LIMIT 100",
            (token["id"],),
        ).fetchall()
    return {"success": True, "logs": [dict(row) for row in rows]}
