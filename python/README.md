# PTv Android App

PTv is a Python/Kivy Android client for the PTv Cloud Control FastAPI server in `../server`.
The default connection is `https://twoones-l0s0.onrender.com`.

## Features

- Server health and authenticated server status
- Device registration and device list
- Service status
- Activity logs scoped to the current token
- Admin-only token creation and token listing
- Python, Supabase, and Firebase token types
- Settings and stable device ID
- Dark operations dashboard with separate Home, Devices, Services, Tokens, Logs, Diagnostics, and Settings screens
- Persistent server URL, bearer token, and admin-key fields
- Dashboard summary and safe runtime diagnostics
- No-login first-run provisioning: the app requests and stores its own user API token
- Services screen with live Python, Supabase database/storage, and Firebase database/storage indicators

## Local run

```bash
python -m pip install kivy requests
python main.py
```

## APK build

The GitHub Actions workflow `.github/workflows/python.yml` builds this directory with Buildozer. Run it from the repository's **Actions** tab using **Build PTv APK**, then download the `PTv-APK` artifact.

The APK needs:

- The deployed PTv API URL, for example `https://your-server.onrender.com`
- A bearer token for normal API operations
- The `ADMIN_KEY` value only when creating/listing tokens

Never commit real admin keys or bearer tokens.
