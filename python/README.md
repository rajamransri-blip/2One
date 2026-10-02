# PTv Android App

PTv is a Python/Kivy Android client for the PTv Cloud Control FastAPI server in `../server`.

## Features

- Server health and authenticated server status
- Device registration and device list
- Service status
- Activity logs scoped to the current token
- Admin-only token creation and token listing
- Python, Supabase, and Firebase token types
- Settings and stable device ID

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
