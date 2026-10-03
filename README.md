# Consent Safety Apps

A transparent parent/child safety system built with **FastAPI**, **Kivy**, optional **Supabase Auth/PostgreSQL/Storage**, JWT access tokens, WebSockets, and visible Android permissions.

> This project is consent-based. It does not hide monitoring, secretly activate the camera or microphone, bypass Android permissions, keylog, or provide stealth surveillance. Location sharing is visible, user-controlled, and accompanied by an Android foreground-service notification.

## Project layout

- `backend/` — FastAPI REST/WebSocket backend with SQLite development fallback
- `parent_app/` — Parent dashboard APK source and `buildozer.spec`
- `child_app/` — Child safety APK source, visible location service, and `buildozer.spec`
- `supabase/migrations/001_initial.sql` — PostgreSQL tables, indexes, functions, and RLS
- `.github/workflows/backend.yml` — backend compile/test/Docker validation
- `.github/workflows/parent-android.yml` — Parent APK artifact build
- `.github/workflows/child-android.yml` — Child APK artifact build

## Backend configuration

Copy `backend/.env.example` and configure secrets in Render/GitHub Secrets, never in the APK:

```text
DATABASE_URL=sqlite:///./child_safety.db
JWT_SECRET=replace-with-a-long-random-secret
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
MAX_CONNECTIONS=500
REQUEST_LIMIT=120
LOCATION_RETENTION_DAYS=30
```

For production, use a private PostgreSQL connection and HTTPS/WSS. The Supabase service-role key is backend-only. Android clients call the backend and never receive it.

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API documentation is available at `/docs`; health is `/health`. Deploy with `backend/Dockerfile`.

## Authentication and pairing

1. Parent and child each register with a role (`parent` or `child`).
2. Parent creates a short-lived one-time pairing code.
3. Child enters the code in the visible Child app.
4. Backend creates the link and the parent can revoke it.
5. Parent data access is restricted to actively linked children; child data access is restricted to the child's own account.
6. Location tracking requires explicit sharing enabled in the Child app and uses a short-lived location session.

Core routes include `/auth/register`, `/auth/login`, `/auth/refresh`, `/devices/pairing-code`, `/devices/claim`, `/devices/revoke`, `/children`, `/location`, `/geofences`, `/sos`, `/checkins`, `/messages`, `/media/photo`, `/media/voice`, `/device/status/{child_id}`, and `/ws`.

## Android apps

Configure the server URL in each app or through the `SERVER_URL` environment/build setting. Parent features include children, latest location, history, zones, alerts, check-ins, messages, pairing, and device status. Child features include visible sharing control, SOS countdown, check-in response, messaging, photo/voice actions, battery/status, and settings.

Build locally:

```bash
cd parent_app && buildozer -v android debug
cd ../child_app && buildozer -v android debug
```

GitHub Actions uploads separate `parent-apk` and `child-apk` artifacts. APK builds target ARM64, API 24 minimum, and use the stable python-for-android release pin.

## Supabase

1. Create a Supabase project and run `supabase/migrations/001_initial.sql` as database owner.
2. Configure Supabase Auth email/password and password-reset email delivery.
3. Set backend-only `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and private PostgreSQL `DATABASE_URL` as needed.
4. Review RLS policies and retention before production. Location history is intended to be retained for a bounded period, not indefinitely.

## Security and operational limits

- JWT access tokens expire and refresh tokens can be revoked.
- Pairing codes expire and are one-time use.
- WebSocket connections are authenticated and bounded by `MAX_CONNECTIONS` with cleanup/ping handling.
- HTTP rate limiting is configurable; use a shared reverse proxy limiter for multi-instance deployments.
- Media uploads have type and size limits and are only shared through linked conversations.
- SOS and location events are audited and ownership checked.
- Never log passwords, JWT secrets, service-role keys, or private tokens.
- GPS accuracy is not guaranteed; the UI displays last update and sharing state.

## Tests

```bash
cd backend
pytest -q
python3 -m compileall -q app tests
```

Tests cover registration/login, JWT validation, one-time pairing, parent/child isolation, location history, geofences, SOS acknowledgement, check-ins, messaging, revocation, and unauthorized access.
