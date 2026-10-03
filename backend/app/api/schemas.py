from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, field_validator


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class Register(Credentials):
    role: Literal["parent", "child"]


class Login(Credentials):
    pass


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class PairRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8)
    device_name: str = Field(min_length=1, max_length=80)


class ChildID(BaseModel):
    child_id: str


class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0, le=10000)
    recorded_at: datetime
    battery: int | None = Field(default=None, ge=0, le=100)
    network: str = Field(default="unknown", max_length=32)

    @field_validator("recorded_at")
    @classmethod
    def requires_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Location timestamp must include timezone")
        return value


class StatusIn(BaseModel):
    online: bool = True
    battery: int | None = Field(default=None, ge=0, le=100)
    charging: bool | None = None
    network: str = Field(default="unknown", max_length=32)
    location_enabled: bool = False
    notifications_enabled: bool = False
    sharing: bool = False


class GeofenceIn(BaseModel):
    child_id: str
    name: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(ge=50, le=50000)
    notify_enter: bool = True
    notify_exit: bool = True


class CheckinRequest(BaseModel):
    child_id: str
    reminder_minutes: int = Field(default=15, ge=1, le=1440)


class CheckinResponse(BaseModel):
    checkin_id: str
    response: Literal["safe", "help"]


class MessageIn(BaseModel):
    child_id: str
    body: str = Field(default="", max_length=2000)
    media_id: str | None = None


class MarkRead(BaseModel):
    child_id: str
