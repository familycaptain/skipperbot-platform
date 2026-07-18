"""Voice device registry — persistent satellite links for PROACTIVE voice.

The session-time WebSockets (audio relay + sideband) are keyed by session_id and
only exist AFTER a wake word. Proactive voice — announcements now, two-way
check-ins later — has to reach a satellite while it is IDLE, so each satellite
also holds a standing control link here, keyed by a stable device_id. This
registry tracks which devices are online and lets the host push JSON events and
PCM audio to them. It mirrors ``connections.ConnectionManager`` (the chat-client
registry) deliberately.
"""
from __future__ import annotations

import time

from config import logger


class VoiceDeviceManager:
    def __init__(self) -> None:
        # device_id -> {ws, user_id, room, since}
        self.active: dict[str, dict] = {}

    async def connect(self, device_id: str, websocket, *, user_id: str = "", room: str = "") -> None:
        self.active[device_id] = {"ws": websocket, "user_id": user_id, "room": room, "since": time.time()}
        logger.info("VOICE-DEVICE: %s online (user=%s room=%s; total=%d)",
                    device_id, user_id or "-", room or "-", len(self.active))

    def disconnect(self, device_id: str) -> None:
        if self.active.pop(device_id, None) is not None:
            logger.info("VOICE-DEVICE: %s offline (total=%d)", device_id, len(self.active))

    def is_online(self, device_id: str) -> bool:
        return device_id in self.active

    def list_devices(self) -> list[str]:
        return list(self.active.keys())

    def default_device(self) -> str | None:
        """When a notification doesn't name a device, fall back to the single online
        one (the common single-satellite family case). Ambiguous with 2+ online —
        returns None so the caller decides rather than guessing a room."""
        ids = list(self.active.keys())
        return ids[0] if len(ids) == 1 else None

    def resolve(self, device_id: str = "") -> str | None:
        """The device to actually speak on. A NAMED device resolves only to itself —
        if it's offline we return None (fall back to push) rather than blurting a
        room-specific announcement into a different room. An UNnamed request uses the
        single online device. None means 'nowhere to speak; caller falls back to push'."""
        if device_id:
            return device_id if device_id in self.active else None
        return self.default_device()

    async def send_json(self, device_id: str, message: dict) -> bool:
        entry = self.active.get(device_id)
        if not entry:
            return False
        try:
            await entry["ws"].send_json(message)
            return True
        except Exception as exc:  # noqa: BLE001 — a dead socket must not crash delivery
            logger.warning("VOICE-DEVICE: send_json to %s failed: %s", device_id, exc)
            return False

    async def send_bytes(self, device_id: str, data: bytes) -> bool:
        entry = self.active.get(device_id)
        if not entry:
            return False
        try:
            await entry["ws"].send_bytes(data)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("VOICE-DEVICE: send_bytes to %s failed: %s", device_id, exc)
            return False


manager = VoiceDeviceManager()
