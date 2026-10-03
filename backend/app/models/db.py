"""SQLAlchemy models shared by SQLite local mode and Supabase-hosted PostgreSQL."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Stamp:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class User(Stamp, Base):
    __tablename__ = "profiles"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(8), nullable=False)


class PairCode(Stamp, Base):
    __tablename__ = "pair_codes"
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Link(Stamp, Base):
    __tablename__ = "parent_child_links"
    __table_args__ = (UniqueConstraint("parent_id", "child_id"),)
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Device(Stamp, Base):
    __tablename__ = "child_devices"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sharing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Status(Stamp, Base):
    __tablename__ = "device_status"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), unique=True, nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    battery: Mapped[int | None] = mapped_column(Integer)
    charging: Mapped[bool | None] = mapped_column(Boolean)
    network: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    location_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Location(Stamp, Base):
    __tablename__ = "locations"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    battery: Mapped[int | None] = mapped_column(Integer)
    network: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    __table_args__ = (Index("ix_locations_child_recorded", "child_id", "recorded_at"),)


class Geofence(Stamp, Base):
    __tablename__ = "geofences"
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer, nullable=False)
    notify_enter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_exit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    inside: Mapped[bool | None] = mapped_column(Boolean)


class Sos(Stamp, Base):
    __tablename__ = "sos_events"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    battery: Mapped[int | None] = mapped_column(Integer)
    network: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("profiles.id"))


class Checkin(Stamp, Base):
    __tablename__ = "checkins"
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response: Mapped[str | None] = mapped_column(String(16))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Message(Stamp, Base):
    __tablename__ = "messages"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    media_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("media_files.id"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Media(Stamp, Base):
    __tablename__ = "media_files"
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    mime: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)


class Notification(Stamp, Base):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False)
    detail: Mapped[str] = mapped_column(String(200), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refresh(Stamp, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), default="user", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Audit(Stamp, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    child_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("profiles.id"))


def create_session_factory(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
