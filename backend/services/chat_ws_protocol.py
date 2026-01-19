from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


class ChatWsProtocol:
    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def accept(self) -> None:
        try:
            await self._ws.accept()
        except (WebSocketDisconnect, RuntimeError):
            return

    async def receive_text(self) -> str | None:
        try:
            return await self._ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            return None

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._ws.client_state != WebSocketState.CONNECTED:
            return
        try:
            await self._ws.send_text(json.dumps(payload, ensure_ascii=False))
        except (WebSocketDisconnect, RuntimeError):
            return

    async def close(self, code: int = 1000) -> None:
        try:
            await self._ws.close(code=code)
        except (WebSocketDisconnect, RuntimeError):
            return
