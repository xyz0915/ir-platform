"""告警 WebSocket 连接管理器."""
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class AlertWebSocketManager:
    """告警 WebSocket 连接管理器."""

    def __init__(self):
        self._connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)
        logger.info("WebSocket connected: user=%d, total=%d", user_id, self.connection_count)

    def disconnect(self, user_id: int, ws: WebSocket):
        conns = self._connections.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        logger.info("WebSocket disconnected: user=%d, total=%d", user_id, self.connection_count)

    async def broadcast(self, data: dict):
        """广播消息到所有 WebSocket 连接."""
        disconnected = []
        for user_id, conns in self._connections.items():
            for ws in conns:
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.append((user_id, ws))
        for uid, ws in disconnected:
            self.disconnect(uid, ws)

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


alert_ws_manager = AlertWebSocketManager()
