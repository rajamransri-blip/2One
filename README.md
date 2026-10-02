# PTv Cloud Control

PTv is an advanced FastAPI cloud-control service with a dark Python/Kivy Android operations client.
The current Render API is `https://twoones-l0s0.onrender.com`.

## Repository layout

- `server/` — FastAPI API, Dockerfile, and Render configuration
- `python/` — committed PTv Python/Kivy app source and `buildozer.spec`
- `.github/workflows/python.yml` — builds a debug APK from `python/`
- `.github/workflows/server.yml` — validates the committed API source

## Deploy the API

Deploy `server/` as a Docker service. Configure these environment variables:

- `ADMIN_KEY` — required for token creation, listing, and revocation
- `DATABASE_PATH` — optional SQLite path; use persistent storage in production
- `CORS_ORIGINS` — optional comma-separated allowed origins
- `SUPABASE_URL` and `FIREBASE_PROJECT_ID` — optional service availability flags

The API exposes FastAPI docs at `/docs` and health at `/health`.
Authenticated dashboard summary is available at `/api/v1/dashboard`.
Safe runtime checks are available at `/api/v1/diagnostics`.

## Build the APK

Open GitHub Actions and run **Build PTv APK**. The workflow uses the committed source in `python/` and uploads a `PTv-APK` artifact. It does not generate or commit source code during CI.

The Android app connects to the API using a bearer token. Admin operations additionally require the server's `X-Admin-Key` value. Do not commit credentials.

## Security fixes included

- Token creation cannot run when `ADMIN_KEY` is missing.
- Admin operations use constant-time key comparison.
- Device and log data are scoped to the authenticated token.
- CORS is configurable.
- SQLite paths work for both `cloud.db` and nested paths.
- API activity is written to the logs table.
- Dashboard and diagnostics data are scoped to the authenticated token.
- Local databases, bytecode, and Buildozer output are ignored by Git.
