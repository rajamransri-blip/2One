"""Consent-first child safety API. All data access is scoped server-side to an active link."""
import asyncio
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import delete, desc, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (CheckinRequest, CheckinResponse, ChildID, Credentials, GeofenceIn, LocationIn,
                             MessageIn, PairRequest, RefreshRequest, Register, StatusIn)
from app.auth.provider import supabase_request
from app.config import Settings
from app.models.db import (Audit, Checkin, Device, Geofence, Link, Location, Media, Message, Notification, PairCode,
                           Refresh, Sos, Status, User, create_session_factory, now)
from app.security.tokens import access_token, decode_token, digest, password_hash, service_token, verify_password
from app.services.geo import meters
from app.websocket.manager import ConnectionManager


def aware(value: datetime | None):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def iso(value):
    return aware(value).isoformat() if value else None


def serialize(obj, *fields):
    return {field: iso(getattr(obj, field)) if isinstance(getattr(obj, field), datetime) else getattr(obj, field)
            for field in fields}


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, session_factory = create_session_factory(settings.database_url)
    app = FastAPI(title="Consent Safety API", version="1.0.0", description="Explicitly paired accounts only. Use HTTPS/WSS in production.")
    app.state.settings = settings
    app.state.sessions = session_factory
    app.state.manager = ConnectionManager(settings.max_connections)
    app.state.rate = defaultdict(deque)

    @app.on_event("shutdown")
    async def close_engine():
        engine.dispose()

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        # Single-process protection; production needs a shared reverse-proxy limiter too.
        key = (request.client.host if request.client else "unknown", request.url.path)
        window = app.state.rate[key]
        current = time.monotonic()
        while window and window[0] < current - 60:
            window.popleft()
        if len(window) >= settings.request_limit:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        window.append(current)
        return await call_next(request)

    def db():
        with session_factory() as session:
            yield session

    async def identity(request: Request, authorization: str | None = Header(default=None), session: Session = Depends(db)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer access token required")
        token = authorization[7:]
        try:
            service_claims = decode_token(token, settings.jwt_secret, expected_type="service")
        except HTTPException:
            service_claims = None
        if service_claims:
            if request.method != "POST" or request.url.path not in ("/location", "/device/status"):
                raise HTTPException(403, "Location session is limited to status and location upload")
            user = session.get(User, service_claims["sub"])
            if not user or user.role != "child":
                raise HTTPException(401, "Unknown child device")
            device = session.scalar(select(Device).where(Device.child_id == user.id))
            if not device or not device.sharing:
                raise HTTPException(403, "Child switched location sharing off")
        elif settings.supabase_url:
            remote = await supabase_request(settings, "GET", "user", token=token)
            user_id = remote.get("id")
            user = session.get(User, user_id) if user_id else None
            if user is None:
                raise HTTPException(401, "Account profile missing")
        else:
            claims = decode_token(token, settings.jwt_secret)
            user = session.get(User, claims["sub"])
            if user is None or user.role != claims.get("role"):
                raise HTTPException(401, "Unknown account")
        return user

    def role(user: User, required: str):
        if user.role != required:
            raise HTTPException(403, f"{required} account required")

    def linked(session: Session, parent_id: str, child_id: str):
        link = session.scalar(select(Link).where(Link.parent_id == parent_id, Link.child_id == child_id, Link.active == True))
        if link is None:
            raise HTTPException(404, "Child not linked")
        return link

    def child_scope(session: Session, user: User, child_id: str):
        if user.role == "parent":
            linked(session, user.id, child_id)
        elif user.role == "child" and user.id == child_id:
            if not session.scalar(select(Link.id).where(Link.child_id == child_id, Link.active == True)):
                raise HTTPException(404, "Child not linked")
        else:
            raise HTTPException(404, "Child not linked")

    def parents(session: Session, child_id: str):
        return list(session.scalars(select(Link.parent_id).where(Link.child_id == child_id, Link.active == True)))

    def notify(session: Session, recipients: list[str], child_id: str, kind: str, detail: str):
        for recipient in recipients:
            session.add(Notification(user_id=recipient, child_id=child_id, kind=kind, detail=detail[:200]))

    def audit(session: Session, user: User, action: str, child_id=None):
        session.add(Audit(actor_id=user.id, action=action, child_id=child_id))

    def status_data(item: Status | None, device: Device | None):
        return {"online": bool(item and item.online and (now() - aware(item.last_sync)).total_seconds() < settings.online_seconds),
                "battery": item.battery if item else None, "charging": item.charging if item else None,
                "network": item.network if item else "unknown", "location_enabled": item.location_enabled if item else False,
                "notifications_enabled": item.notifications_enabled if item else False,
                "last_sync": iso(item.last_sync) if item else None,
                "sharing": device.sharing if device else False}

    def location_data(item: Location):
        return serialize(item, "id", "child_id", "latitude", "longitude", "accuracy", "recorded_at", "battery", "network")

    def checkin_data(item: Checkin):
        return serialize(item, "id", "parent_id", "child_id", "created_at", "deadline", "response", "responded_at")

    def message_data(item: Message):
        return serialize(item, "id", "child_id", "sender_id", "body", "media_id", "created_at", "delivered_at", "read_at")

    def sos_data(item: Sos):
        return serialize(item, "id", "child_id", "latitude", "longitude", "battery", "network", "created_at", "acknowledged_at", "acknowledged_by")

    @app.get("/health")
    def health():
        return {"status": "ok", "database": "postgres" if not settings.database_url.startswith("sqlite") else "sqlite"}

    @app.post("/auth/register", status_code=201)
    async def register(data: Register, session: Session = Depends(db)):
        email = data.email.lower()
        if session.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(409, "Account already exists")
        if settings.supabase_url:
            result = await supabase_request(settings, "POST", "signup", json={"email": email, "password": data.password,
                                                                                 "data": {"role": data.role}})
            if not result.get("access_token"):
                return {"confirmation_required": True, "message": "Check email, then log in to finish registration"}
            remote = result.get("user", {})
            user = User(id=remote["id"], email=email, role=data.role)
        else:
            user = User(email=email, role=data.role, password_hash=password_hash(data.password))
        try:
            session.add(user)
            session.flush()
            audit(session, user, "register")
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Account already exists") from None
        if settings.supabase_url:
            return {"user_id": user.id, "role": user.role, "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token"), "token_type": "bearer"}
        return {"user_id": user.id, "role": user.role, "message": "Account created; log in to receive tokens"}

    @app.post("/auth/login")
    async def login(data: Credentials, session: Session = Depends(db)):
        user = session.scalar(select(User).where(User.email == data.email.lower()))
        if settings.supabase_url:
            result = await supabase_request(settings, "POST", "token?grant_type=password", json={"email": data.email.lower(), "password": data.password})
            remote = result.get("user", {})
            if user is None and remote.get("id"):
                candidate = remote.get("user_metadata", {}).get("role")
                if candidate not in ("parent", "child"):
                    raise HTTPException(403, "Registration role missing")
                user = User(id=remote["id"], email=data.email.lower(), role=candidate)
                session.add(user)
                session.commit()
            if user is None or user.id != remote.get("id"):
                raise HTTPException(401, "Invalid credentials")
            return {"access_token": result["access_token"], "refresh_token": result["refresh_token"],
                    "token_type": "bearer", "role": user.role, "user_id": user.id}
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        raw = secrets.token_urlsafe(48)
        session.add(Refresh(user_id=user.id, token_hash=digest(raw), expires_at=now() + timedelta(days=30)))
        session.commit()
        return {"access_token": access_token(user, settings.jwt_secret), "refresh_token": raw,
                "token_type": "bearer", "role": user.role, "user_id": user.id}

    @app.post("/auth/refresh")
    async def refresh(data: RefreshRequest, session: Session = Depends(db)):
        if settings.supabase_url:
            result = await supabase_request(settings, "POST", "token?grant_type=refresh_token", json={"refresh_token": data.refresh_token})
            return {"access_token": result["access_token"], "refresh_token": result["refresh_token"], "token_type": "bearer"}
        token = session.scalar(select(Refresh).where(Refresh.token_hash == digest(data.refresh_token)))
        if not token or token.kind != "user" or token.revoked_at or aware(token.expires_at) < now():
            raise HTTPException(401, "Invalid refresh token")
        user = session.get(User, token.user_id)
        token.revoked_at = now()
        raw = secrets.token_urlsafe(48)
        session.add(Refresh(user_id=user.id, token_hash=digest(raw), expires_at=now() + timedelta(days=30)))
        session.commit()
        return {"access_token": access_token(user, settings.jwt_secret), "refresh_token": raw, "token_type": "bearer"}

    @app.post("/auth/location-session")
    def location_session(user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        child_scope(session, user, user.id)
        device = session.scalar(select(Device).where(Device.child_id == user.id))
        if not device.sharing:
            raise HTTPException(403, "Enable visible sharing before creating a location session")
        raw = secrets.token_urlsafe(48)
        session.add(Refresh(user_id=user.id, kind="service", token_hash=digest(raw), expires_at=now() + timedelta(days=1)))
        audit(session, user, "location_session", user.id)
        session.commit()
        return {"access_token": service_token(user, settings.jwt_secret), "refresh_token": raw, "token_type": "bearer"}

    @app.post("/auth/location-session/refresh")
    def refresh_location_session(data: RefreshRequest, session: Session = Depends(db)):
        token = session.scalar(select(Refresh).where(Refresh.token_hash == digest(data.refresh_token)))
        if not token or token.kind != "service" or token.revoked_at or aware(token.expires_at) < now():
            raise HTTPException(401, "Invalid location session")
        user = session.get(User, token.user_id)
        if not user or user.role != "child":
            raise HTTPException(401, "Unknown child device")
        child_scope(session, user, user.id)
        device = session.scalar(select(Device).where(Device.child_id == user.id))
        if not device.sharing:
            raise HTTPException(403, "Location sharing is off")
        token.revoked_at = now()
        raw = secrets.token_urlsafe(48)
        session.add(Refresh(user_id=user.id, kind="service", token_hash=digest(raw), expires_at=now() + timedelta(days=1)))
        session.commit()
        return {"access_token": service_token(user, settings.jwt_secret), "refresh_token": raw, "token_type": "bearer"}

    @app.post("/auth/logout")
    async def logout(data: RefreshRequest, authorization: str | None = Header(default=None), session: Session = Depends(db)):
        if settings.supabase_url:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(401, "Access token required to log out")
            await supabase_request(settings, "POST", "logout", token=authorization[7:])
        else:
            token = session.scalar(select(Refresh).where(Refresh.token_hash == digest(data.refresh_token)))
            if token:
                token.revoked_at = now()
                session.commit()
        return {"ok": True}

    @app.post("/auth/forgot-password")
    async def forgot_password(data: dict):
        from pydantic import EmailStr, TypeAdapter
        try:
            email = str(TypeAdapter(EmailStr).validate_python(data.get("email", "")))
        except ValueError:
            raise HTTPException(422, "Valid email required") from None
        if not settings.supabase_url:
            raise HTTPException(503, "Password recovery requires Supabase Auth and configured email delivery")
        await supabase_request(settings, "POST", "recover", json={"email": email})
        return {"message": "If this account exists, a reset email will be sent"}

    @app.get("/me")
    def me(user: User = Depends(identity)):
        return serialize(user, "id", "email", "role")

    @app.post("/devices/pairing-codes", status_code=201)
    def create_code(user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        item = PairCode(parent_id=user.id, code_hash=digest(code), expires_at=now() + timedelta(minutes=settings.pair_minutes))
        session.add(item)
        audit(session, user, "pair_code")
        session.commit()
        return {"id": item.id, "code": code, "expires_at": iso(item.expires_at), "qr_payload": code}

    @app.post("/devices/pair", status_code=201)
    async def pair(data: PairRequest, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        if session.scalar(select(Link.id).where(Link.child_id == user.id, Link.active == True)):
            raise HTTPException(409, "Revoke the existing pairing first")
        item = session.scalar(select(PairCode).where(PairCode.code_hash == digest(data.code.upper())))
        if not item or item.used_at or aware(item.expires_at) < now():
            raise HTTPException(400, "Pairing code invalid, used, or expired")
        claimed = session.execute(update(PairCode).where(PairCode.id == item.id, PairCode.used_at == None, PairCode.expires_at > now()).values(used_at=now()).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            session.rollback()
            raise HTTPException(400, "Pairing code already used")
        link = session.scalar(select(Link).where(Link.parent_id == item.parent_id, Link.child_id == user.id))
        if link:
            link.active = True
        else:
            link = Link(parent_id=item.parent_id, child_id=user.id)
            session.add(link)
        device = session.scalar(select(Device).where(Device.child_id == user.id))
        if device:
            device.name = data.device_name
            device.sharing = False
        else:
            session.add(Device(child_id=user.id, name=data.device_name, sharing=False))
        audit(session, user, "pair", user.id)
        notify(session, [item.parent_id], user.id, "paired", "Child account paired with your account")
        session.commit()
        await app.state.manager.send([item.parent_id], {"type": "paired", "child_id": user.id})
        return {"child_id": user.id, "parent_id": item.parent_id, "parent_email": session.get(User, item.parent_id).email}

    @app.post("/devices/revoke")
    async def revoke(data: ChildID, user: User = Depends(identity), session: Session = Depends(db)):
        if user.role == "parent":
            link = linked(session, user.id, data.child_id)
        elif user.role == "child" and user.id == data.child_id:
            link = session.scalar(select(Link).where(Link.child_id == user.id, Link.active == True))
            if not link:
                raise HTTPException(404, "Child not linked")
        else:
            raise HTTPException(404, "Child not linked")
        link.active = False
        device = session.scalar(select(Device).where(Device.child_id == data.child_id))
        if device:
            device.sharing = False
        session.execute(update(Refresh).where(Refresh.user_id == data.child_id, Refresh.kind == "service", Refresh.revoked_at == None).values(revoked_at=now()))
        # Clear previously shared family data; it must not become visible to a future parent.
        media_paths = session.scalars(select(Media.path).where(Media.child_id == data.child_id)).all()
        for model in (Message, Media, Location, Geofence, Sos, Checkin, Status, Notification):
            session.execute(delete(model).where(model.child_id == data.child_id))
        audit(session, user, "revoke", data.child_id)
        session.commit()
        for media_path in media_paths:
            Path(media_path).unlink(missing_ok=True)
        await app.state.manager.send([link.parent_id, data.child_id], {"type": "revoked", "child_id": data.child_id})
        return {"revoked": True}

    @app.get("/children")
    def children(user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        ids = session.scalars(select(Link.child_id).where(Link.parent_id == user.id, Link.active == True)).all()
        return [child_summary(session, cid) for cid in ids]

    @app.get("/parents")
    def my_parents(user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        ids = parents(session, user.id)
        return [serialize(session.get(User, parent_id), "id", "email") for parent_id in ids]

    def child_summary(session: Session, child_id: str):
        child = session.get(User, child_id)
        device = session.scalar(select(Device).where(Device.child_id == child_id))
        status = session.scalar(select(Status).where(Status.child_id == child_id))
        latest = session.scalar(select(Location).where(Location.child_id == child_id).order_by(desc(Location.recorded_at)))
        last_checkin = session.scalar(select(Checkin).where(Checkin.child_id == child_id).order_by(desc(Checkin.created_at)))
        active_sos = session.scalars(select(Sos).where(Sos.child_id == child_id, Sos.acknowledged_at == None)).all()
        return {"id": child_id, "email": child.email, "device_name": device.name if device else None,
                "status": status_data(status, device), "last_location": location_data(latest) if latest else None,
                "last_checkin": checkin_data(last_checkin) if last_checkin else None, "active_sos": [sos_data(item) for item in active_sos]}

    @app.get("/children/{child_id}")
    def child_detail(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        linked(session, user.id, child_id)
        return child_summary(session, child_id)

    @app.post("/device/status")
    async def report_status(data: StatusIn, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        child_scope(session, user, user.id)
        device = session.scalar(select(Device).where(Device.child_id == user.id))
        device.sharing = data.sharing
        status = session.scalar(select(Status).where(Status.child_id == user.id))
        if not status:
            status = Status(child_id=user.id)
            session.add(status)
        for field in ("online", "battery", "charging", "network", "location_enabled", "notifications_enabled"):
            setattr(status, field, getattr(data, field))
        status.last_sync = now()
        if data.battery is not None and data.battery <= 15:
            notify(session, parents(session, user.id), user.id, "low_battery", "Battery at or below 15%")
        session.commit()
        await app.state.manager.send(parents(session, user.id), {"type": "status", "child_id": user.id, "status": status_data(status, device)})
        return status_data(status, device)

    @app.get("/device/status/{child_id}")
    def device_status(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        return status_data(session.scalar(select(Status).where(Status.child_id == child_id)),
                           session.scalar(select(Device).where(Device.child_id == child_id)))

    @app.post("/location", status_code=201)
    async def upload_location(data: LocationIn, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        child_scope(session, user, user.id)
        device = session.scalar(select(Device).where(Device.child_id == user.id))
        if not device.sharing:
            raise HTTPException(403, "Location sharing is switched off")
        when = data.recorded_at.astimezone(timezone.utc)
        if when > now() + timedelta(minutes=5) or when < now() - timedelta(hours=24):
            raise HTTPException(422, "Location timestamp out of range")
        item = Location(child_id=user.id, **data.model_dump(exclude={"recorded_at"}), recorded_at=when)
        session.add(item)
        session.flush()
        session.execute(delete(Location).where(Location.recorded_at < now() - timedelta(days=settings.retention_days)))
        events = []
        zones = session.scalars(select(Geofence).where(Geofence.child_id == user.id)).all()
        for zone in zones:
            inside = meters(data.latitude, data.longitude, zone.latitude, zone.longitude) <= zone.radius_m
            if data.accuracy > zone.radius_m:
                continue  # avoid a misleading transition on highly uncertain readings
            if zone.inside is not None and zone.inside != inside and (zone.notify_enter if inside else zone.notify_exit):
                kind = "geofence_enter" if inside else "geofence_exit"
                events.append({"type": kind, "child_id": user.id, "zone_id": zone.id, "name": zone.name})
                notify(session, [zone.parent_id], user.id, kind, zone.name)
            zone.inside = inside
        session.commit()
        recipients = parents(session, user.id)
        await app.state.manager.send(recipients, {"type": "location", "child_id": user.id, "location": location_data(item)})
        for event in events:
            await app.state.manager.send(recipients, event)
        return location_data(item)

    @app.get("/location/latest/{child_id}")
    def latest(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        item = session.scalar(select(Location).where(Location.child_id == child_id, Location.recorded_at >= now() - timedelta(days=settings.retention_days)).order_by(desc(Location.recorded_at)))
        if not item:
            raise HTTPException(404, "No recent location")
        return location_data(item)

    @app.get("/location/history/{child_id}")
    def history(child_id: str, limit: int = 100, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        items = session.scalars(select(Location).where(Location.child_id == child_id, Location.recorded_at >= now() - timedelta(days=settings.retention_days)).order_by(desc(Location.recorded_at)).limit(limit)).all()
        return [location_data(item) for item in items]

    @app.post("/geofences", status_code=201)
    def create_geofence(data: GeofenceIn, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        linked(session, user.id, data.child_id)
        item = Geofence(parent_id=user.id, **data.model_dump())
        session.add(item)
        audit(session, user, "geofence_create", data.child_id)
        session.commit()
        return serialize(item, "id", "child_id", "name", "latitude", "longitude", "radius_m", "notify_enter", "notify_exit")

    @app.get("/geofences")
    def geofences(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        items = session.scalars(select(Geofence).where(Geofence.child_id == child_id, Geofence.parent_id.in_(parents(session, child_id)))).all()
        return [serialize(item, "id", "child_id", "name", "latitude", "longitude", "radius_m", "notify_enter", "notify_exit", "inside") for item in items]

    @app.delete("/geofences/{zone_id}")
    def delete_geofence(zone_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        item = session.get(Geofence, zone_id)
        if not item or item.parent_id != user.id:
            raise HTTPException(404, "Safety zone not found")
        linked(session, user.id, item.child_id)
        audit(session, user, "geofence_delete", item.child_id)
        session.delete(item)
        session.commit()
        return {"deleted": True}

    @app.post("/sos", status_code=201)
    async def create_sos(user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        child_scope(session, user, user.id)
        location = session.scalar(select(Location).where(Location.child_id == user.id).order_by(desc(Location.recorded_at)))
        status = session.scalar(select(Status).where(Status.child_id == user.id))
        item = Sos(child_id=user.id, latitude=location.latitude if location else None,
                   longitude=location.longitude if location else None, battery=status.battery if status else None,
                   network=status.network if status else "unknown")
        session.add(item)
        recipients = parents(session, user.id)
        notify(session, recipients, user.id, "sos", "ACTIVE SOS — child requested help")
        audit(session, user, "sos", user.id)
        session.commit()
        await app.state.manager.send(recipients, {"type": "sos", "child_id": user.id, "sos": sos_data(item)})
        return sos_data(item)

    @app.get("/sos/{child_id}")
    def sos_history(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        return [sos_data(item) for item in session.scalars(select(Sos).where(Sos.child_id == child_id).order_by(desc(Sos.created_at)).limit(100))]

    @app.post("/sos/{sos_id}/acknowledge")
    async def acknowledge(sos_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        item = session.get(Sos, sos_id)
        if not item:
            raise HTTPException(404, "SOS not found")
        linked(session, user.id, item.child_id)
        if not item.acknowledged_at:
            item.acknowledged_at, item.acknowledged_by = now(), user.id
            audit(session, user, "sos_ack", item.child_id)
            session.commit()
            await app.state.manager.send([item.child_id], {"type": "sos_acknowledged", "sos_id": item.id})
        return sos_data(item)

    @app.post("/checkins/request", status_code=201)
    async def request_checkin(data: CheckinRequest, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "parent")
        linked(session, user.id, data.child_id)
        item = Checkin(parent_id=user.id, child_id=data.child_id, deadline=now() + timedelta(minutes=data.reminder_minutes))
        session.add(item)
        notify(session, [data.child_id], data.child_id, "checkin_request", "Parent requested a safety check-in")
        session.commit()
        await app.state.manager.send([data.child_id], {"type": "checkin_request", "checkin": checkin_data(item)})
        return checkin_data(item)

    @app.get("/checkins/{child_id}")
    def checkins(child_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        items = session.scalars(select(Checkin).where(Checkin.child_id == child_id, Checkin.parent_id.in_(parents(session, child_id))).order_by(desc(Checkin.created_at)).limit(100)).all()
        if user.role == "parent":
            for item in items:
                if item.parent_id == user.id and not item.response and not item.reminder_sent and aware(item.deadline) < now():
                    item.reminder_sent = True
                    notify(session, [user.id], child_id, "checkin_overdue", "Child check-in is overdue")
            session.commit()  # missed check-ins are raised on polling, not on a scheduler
        return [checkin_data(item) for item in items]

    @app.post("/checkins/respond")
    async def respond_checkin(data: CheckinResponse, user: User = Depends(identity), session: Session = Depends(db)):
        role(user, "child")
        child_scope(session, user, user.id)
        item = session.get(Checkin, data.checkin_id)
        if not item or item.child_id != user.id or item.parent_id not in parents(session, user.id):
            raise HTTPException(404, "Check-in not found")
        if item.response:
            raise HTTPException(409, "Check-in already answered")
        item.response, item.responded_at = data.response, now()
        notify(session, [item.parent_id], user.id, "checkin_response", f"Child responded: {data.response}")
        if data.response == "help":
            notify(session, [item.parent_id], user.id, "needs_help", "Child says they need help")
        session.commit()
        await app.state.manager.send([item.parent_id], {"type": "checkin_response", "checkin": checkin_data(item)})
        return checkin_data(item)

    @app.post("/messages", status_code=201)
    async def create_message(data: MessageIn, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, data.child_id)
        if not data.body.strip() and not data.media_id:
            raise HTTPException(422, "Message must contain text or media")
        media = session.get(Media, data.media_id) if data.media_id else None
        if data.media_id and (not media or media.child_id != data.child_id or user.role != "child"):
            raise HTTPException(404, "Media not found")
        item = Message(child_id=data.child_id, sender_id=user.id, body=data.body, media_id=data.media_id, delivered_at=now())
        session.add(item)
        recipients = parents(session, data.child_id) if user.role == "child" else [data.child_id]
        notify(session, recipients, data.child_id, "message", "New family message")
        session.commit()
        await app.state.manager.send(recipients, {"type": "message", "message": message_data(item)})
        return message_data(item)

    @app.get("/messages/{child_id}")
    def messages(child_id: str, limit: int = 100, user: User = Depends(identity), session: Session = Depends(db)):
        child_scope(session, user, child_id)
        if not 1 <= limit <= 200:
            raise HTTPException(422, "limit must be between 1 and 200")
        return [message_data(item) for item in session.scalars(select(Message).where(Message.child_id == child_id).order_by(desc(Message.created_at)).limit(limit))]

    @app.post("/messages/{message_id}/read")
    async def read_message(message_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        item = session.get(Message, message_id)
        if not item:
            raise HTTPException(404, "Message not found")
        child_scope(session, user, item.child_id)
        if item.sender_id == user.id:
            raise HTTPException(403, "Sender cannot mark own message read")
        if not item.read_at:
            item.read_at = now()
            session.commit()
            await app.state.manager.send([item.sender_id], {"type": "message_read", "message_id": item.id})
        return message_data(item)

    async def upload_media(kind: str, file: UploadFile, user: User, session: Session):
        role(user, "child")
        child_scope(session, user, user.id)
        types = {"photo": {"image/jpeg": ".jpg", "image/png": ".png"},
                 "voice": {"audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/wav": ".wav"}}
        if file.content_type not in types[kind]:
            raise HTTPException(415, "Unsupported media type")
        content = await file.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(413, "Media must be 1 byte to 5 MiB")
        if kind == "photo" and not (content.startswith(b"\xff\xd8\xff") or content.startswith(b"\x89PNG\r\n\x1a\n")):
            raise HTTPException(415, "Invalid image header")
        name = str(uuid4()) + types[kind][file.content_type]
        path = Path(settings.media_dir) / name
        path.write_bytes(content)
        path.chmod(0o600)
        item = Media(child_id=user.id, kind=kind, mime=file.content_type, path=str(path), size=len(content))
        session.add(item)
        audit(session, user, "media_upload", user.id)
        session.commit()
        return {"id": item.id, "kind": kind, "size": item.size, "message": "Send a message with media_id to share this file"}

    @app.post("/media/photo", status_code=201)
    async def photo(file: UploadFile = File(...), user: User = Depends(identity), session: Session = Depends(db)):
        return await upload_media("photo", file, user, session)

    @app.post("/media/voice", status_code=201)
    async def voice(file: UploadFile = File(...), user: User = Depends(identity), session: Session = Depends(db)):
        return await upload_media("voice", file, user, session)

    @app.get("/media/{media_id}")
    def download_media(media_id: str, user: User = Depends(identity), session: Session = Depends(db)):
        item = session.get(Media, media_id)
        if not item:
            raise HTTPException(404, "Media not found")
        child_scope(session, user, item.child_id)
        if user.role == "parent" and not session.scalar(select(Message.id).where(Message.media_id == media_id)):
            raise HTTPException(404, "Media not shared")
        return FileResponse(item.path, media_type=item.mime, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/notifications")
    def notifications(user: User = Depends(identity), session: Session = Depends(db)):
        return [serialize(item, "id", "kind", "child_id", "detail", "created_at", "read_at") for item in
                session.scalars(select(Notification).where(Notification.user_id == user.id).order_by(desc(Notification.created_at)).limit(100))]

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        await websocket.accept()
        user_id = None
        try:
            # First frame authenticates; never place bearer tokens in URL/query logs.
            first = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            if first.get("type") != "auth" or not isinstance(first.get("token"), str):
                await websocket.close(code=1008)
                return
            token = first["token"]
            if settings.supabase_url:
                remote = await supabase_request(settings, "GET", "user", token=token)
                user_id = remote.get("id")
            else:
                user_id = decode_token(token, settings.jwt_secret)["sub"]
            with session_factory() as session:
                if not session.get(User, user_id):
                    await websocket.close(code=1008)
                    return
            if not await app.state.manager.add(user_id, websocket):
                await websocket.close(code=1013)
                return
            await websocket.send_json({"type": "ready"})
            while True:
                try:
                    incoming = await asyncio.wait_for(websocket.receive_json(), timeout=45)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})
                    incoming = await asyncio.wait_for(websocket.receive_json(), timeout=15)
                if incoming.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif incoming.get("type") != "pong":
                    await websocket.close(code=1008)
                    return
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, HTTPException, KeyError):
            try:
                await websocket.close(code=1008)
            except RuntimeError:
                return
        finally:
            if user_id:
                await app.state.manager.remove(user_id, websocket)

    return app


app = create_app()
