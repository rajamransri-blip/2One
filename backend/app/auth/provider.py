"""Supabase Auth is server-side only and uses the public anon key, never a service-role key."""
import httpx
from fastapi import HTTPException


async def supabase_request(settings, method: str, path: str, *, json=None, token=None):
    headers = {"apikey": settings.supabase_anon_key}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(method, settings.supabase_url.rstrip("/") + "/auth/v1/" + path, headers=headers, json=json)
        if response.status_code >= 400:
            raise HTTPException(401 if response.status_code in (400, 401, 403) else 502, "Authentication provider rejected request")
        return response.json()
    except httpx.RequestError:
        raise HTTPException(503, "Authentication provider unavailable") from None
