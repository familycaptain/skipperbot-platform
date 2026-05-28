"""
SkipperBot Connection Manager
Manages active WebSocket connections keyed by user_id.
"""

from fastapi import WebSocket
from config import logger


class ConnectionManager:
    """Manages active WebSocket connections keyed by user_id."""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[user_id] = websocket
        logger.debug("WS CONNECT: %s (total: %d)", user_id, len(self.active))

    def disconnect(self, user_id: str):
        self.active.pop(user_id, None)
        logger.debug("WS DISCONNECT: %s (total: %d)", user_id, len(self.active))

    async def send_to_user(self, user_id: str, message: dict):
        ws = self.active.get(user_id)
        if ws:
            await ws.send_json(message)
            return True
        return False

    async def broadcast(self, message: dict):
        """Send a message to all connected WebSocket clients."""
        for user_id, ws in list(self.active.items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.debug("WS BROADCAST: Failed to send to %s", user_id)

    def list_connected_users(self) -> list[str]:
        return list(self.active.keys())


manager = ConnectionManager()
