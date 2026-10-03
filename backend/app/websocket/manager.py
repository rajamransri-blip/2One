"""In-process fan-out. Production multi-worker deployments need shared pub/sub."""
import asyncio
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, maximum: int):
        self.maximum = maximum
        self.by_user: dict[str, set[WebSocket]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def add(self, user_id: str, websocket: WebSocket) -> bool:
        async with self.lock:
            if sum(map(len, self.by_user.values())) >= self.maximum:
                return False
            self.by_user[user_id].add(websocket)
            return True

    async def remove(self, user_id: str, websocket: WebSocket):
        async with self.lock:
            self.by_user[user_id].discard(websocket)
            if not self.by_user[user_id]:
                del self.by_user[user_id]

    async def send(self, user_ids: list[str], payload: dict):
        recipients = [ws for uid in set(user_ids) for ws in tuple(self.by_user.get(uid, ())) ]
        for websocket in recipients:
            try:
                await asyncio.wait_for(websocket.send_json(payload), timeout=3)
            except (OSError, RuntimeError, asyncio.TimeoutError):
                for uid in set(user_ids):
                    if websocket in self.by_user.get(uid, ()):
                        await self.remove(uid, websocket)
