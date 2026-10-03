from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.fixture
def api(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", app_env="test",
                        jwt_secret="test-only-long-secret-that-is-at-least-32-chars", media_dir=str(tmp_path / "media"))
    with TestClient(create_app(settings)) as client:
        yield client


def account(api, email, role):
    payload = {"email": email, "password": "safe-password-1234", "role": role}
    assert api.post("/auth/register", json=payload).status_code == 201
    response = api.post("/auth/login", json={"email": email, "password": payload["password"]})
    assert response.status_code == 200
    result = response.json()
    return result["user_id"], {"Authorization": "Bearer " + result["access_token"]}, result["refresh_token"]


def paired(api, suffix="1"):
    parent, ph, _ = account(api, f"parent{suffix}@example.com", "parent")
    child, ch, _ = account(api, f"child{suffix}@example.com", "child")
    code = api.post("/devices/pairing-codes", headers=ph).json()["code"]
    result = api.post("/devices/pair", json={"code": code, "device_name": "Kid's phone"}, headers=ch)
    assert result.status_code == 201, result.text
    return parent, ph, child, ch, code


def test_auth_jwt_refresh_and_validation(api):
    _, ph, refresh = account(api, "test@example.com", "parent")
    assert api.get("/me", headers=ph).json()["role"] == "parent"
    assert api.get("/me").status_code == 401
    assert api.get("/me", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert api.post("/auth/login", json={"email": "test@example.com", "password": "incorrect-password"}).status_code == 401
    assert api.post("/auth/register", json={"email": "test@example.com", "password": "safe-password-1234", "role": "child"}).status_code == 409
    rotated = api.post("/auth/refresh", json={"refresh_token": refresh}).json()
    assert api.get("/me", headers={"Authorization": "Bearer " + rotated["access_token"]}).status_code == 200
    assert api.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert api.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]}).status_code == 200
    assert api.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]}).status_code == 401


def test_pairing_expiry_reuse_revoke_and_role(api):
    parent, ph, child, ch, code = paired(api)
    assert api.post("/devices/pair", headers=ch, json={"code": code, "device_name": "Again"}).status_code == 409
    other, otherh, _ = account(api, "otherchild@example.com", "child")
    assert api.post("/devices/pair", headers=otherh, json={"code": code, "device_name": "Other"}).status_code == 400
    assert api.post("/devices/pair", headers=ph, json={"code": "BADCODE1", "device_name": "Phone"}).status_code == 403
    assert api.get("/children", headers=ph).json()[0]["id"] == child
    assert api.post("/devices/revoke", headers=ph, json={"child_id": child}).status_code == 200
    assert api.get(f"/children/{child}", headers=ph).status_code == 404
    assert api.post("/device/status", headers=ch, json={"sharing": True}).status_code == 404
    expired = api.post("/devices/pairing-codes", headers=ph).json()["code"]
    from app.models.db import PairCode, now
    from sqlalchemy import select
    with api.app.state.sessions() as session:
        item = session.scalar(select(PairCode).where(PairCode.code_hash == __import__("hashlib").sha256(expired.encode()).hexdigest()))
        item.expires_at = now() - timedelta(seconds=1)
        session.commit()
    assert api.post("/devices/pair", headers=otherh, json={"code": expired, "device_name": "Other"}).status_code == 400


def test_location_status_geofence_and_isolation(api):
    _, ph, child, ch, _ = paired(api)
    _, ph2, child2, ch2, _ = paired(api, "2")
    coordinates = {"latitude": 11.001, "longitude": 12.001, "accuracy": 8, "recorded_at": datetime.now(timezone.utc).isoformat(), "battery": 74, "network": "wifi"}
    assert api.post("/location", headers=ch, json=coordinates).status_code == 403
    assert api.post("/device/status", headers=ch, json={"sharing": True, "location_enabled": True, "online": True, "battery": 74, "network": "wifi"}).status_code == 200
    zone = api.post("/geofences", headers=ph, json={"child_id": child, "name": "Home", "latitude": 11.001, "longitude": 12.001, "radius_m": 300})
    assert zone.status_code == 201
    assert api.post("/geofences", headers=ph2, json={"child_id": child, "name": "No", "latitude": 0, "longitude": 0, "radius_m": 50}).status_code == 404
    assert api.post("/location", headers=ch, json=coordinates).status_code == 201
    coordinates["latitude"] = 12.0
    assert api.post("/location", headers=ch, json=coordinates).status_code == 201
    assert any(n["kind"] == "geofence_exit" for n in api.get("/notifications", headers=ph).json())
    assert api.get(f"/location/latest/{child}", headers=ph).json()["latitude"] == 12.0
    assert len(api.get(f"/location/history/{child}", headers=ph).json()) == 2
    assert api.get(f"/device/status/{child}", headers=ph).json()["battery"] == 74
    for route in (f"/children/{child}", f"/location/latest/{child}", f"/location/history/{child}", f"/device/status/{child}", f"/geofences?child_id={child}"):
        assert api.get(route, headers=ph2).status_code == 404
    assert api.get(f"/location/latest/{child}", headers=ch2).status_code == 404
    assert api.post("/location", headers=ph, json=coordinates).status_code == 403
    coordinates["latitude"] = 91
    assert api.post("/location", headers=ch, json=coordinates).status_code == 422
    assert api.delete(f"/geofences/{zone.json()['id']}", headers=ph2).status_code == 404
    assert api.delete(f"/geofences/{zone.json()['id']}", headers=ph).status_code == 200


def test_sos_checkin_messages_and_isolation(api):
    _, ph, child, ch, _ = paired(api)
    _, ph2, _, ch2, _ = paired(api, "2")
    sos = api.post("/sos", headers=ch)
    assert sos.status_code == 201
    sos_id = sos.json()["id"]
    assert api.post(f"/sos/{sos_id}/acknowledge", headers=ph2).status_code == 404
    assert api.get(f"/sos/{child}", headers=ph2).status_code == 404
    assert api.post(f"/sos/{sos_id}/acknowledge", headers=ph).json()["acknowledged_by"] is not None
    checkin = api.post("/checkins/request", headers=ph, json={"child_id": child, "reminder_minutes": 1})
    assert checkin.status_code == 201
    cid = checkin.json()["id"]
    assert api.post("/checkins/respond", headers=ch2, json={"checkin_id": cid, "response": "safe"}).status_code == 404
    assert api.post("/checkins/respond", headers=ch, json={"checkin_id": cid, "response": "help"}).status_code == 200
    assert api.post("/checkins/respond", headers=ch, json={"checkin_id": cid, "response": "safe"}).status_code == 409
    assert api.get(f"/checkins/{child}", headers=ph2).status_code == 404
    message = api.post("/messages", headers=ch, json={"child_id": child, "body": "Hi"})
    assert message.status_code == 201
    mid = message.json()["id"]
    assert api.get(f"/messages/{child}", headers=ph2).status_code == 404
    assert api.post(f"/messages/{mid}/read", headers=ph2).status_code == 404
    assert api.post(f"/messages/{mid}/read", headers=ph).json()["read_at"]
    assert api.post("/messages", headers=ph, json={"child_id": child, "body": "Be safe"}).status_code == 201
    assert len(api.get(f"/messages/{child}", headers=ch).json()) == 2
    assert api.post("/messages", headers=ph2, json={"child_id": child, "body": "bad"}).status_code == 404
    assert api.post("/messages", headers=ch2, json={"child_id": child, "body": "bad"}).status_code == 404


def test_media_private_only_after_share(api):
    _, ph, child, ch, _ = paired(api)
    _, ph2, _, _, _ = paired(api, "2")
    uploaded = api.post("/media/photo", headers=ch, files={"file": ("selfie.png", b"\x89PNG\r\n\x1a\nhello", "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["id"]
    assert api.get(f"/media/{media_id}", headers=ph).status_code == 404
    assert api.post("/messages", headers=ch, json={"child_id": child, "media_id": media_id}).status_code == 201
    assert api.get(f"/media/{media_id}", headers=ph).status_code == 200
    assert api.get(f"/media/{media_id}", headers=ph2).status_code == 404
    assert api.post("/media/voice", headers=ph, files={"file": ("x.wav", b"RIFF", "audio/wav")}).status_code == 403


def test_websocket_reconnect_auth_and_events(api):
    _, ph, child, ch, _ = paired(api)
    with api.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": ph["Authorization"][7:]})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        assert api.post("/sos", headers=ch).status_code == 201
        assert ws.receive_json()["type"] == "sos"
    assert not api.app.state.manager.by_user
    with api.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": ph["Authorization"][7:]})
        assert ws.receive_json()["type"] == "ready"
    assert not api.app.state.manager.by_user
    with pytest.raises(Exception):
        with api.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "forged"})
            ws.receive_json()


def test_rate_limit(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'rate.db'}", jwt_secret="test-secret-long-enough-to-be-32-characters",
                        app_env="test", media_dir=str(tmp_path / "media"), request_limit=2)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 429
