"""SSE 事件管理器 — 按 run_id 维护异步队列 + 客户端流."""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class SseManager:
    """SSE 连接管理器。

    每个 run_id 维护一个 asyncio.Queue，订阅者从队列中消费事件，
    推送者向队列中放入事件。无订阅者时队列丢弃事件。
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._clients: dict[str, set] = {}

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        """为 run_id 创建一个异步生成器，用于 SSE StreamingResponse。

        yield 格式: "event: {event_type}\ndata: {json}\n\n"
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues[run_id] = queue
        if run_id not in self._clients:
            self._clients[run_id] = set()
        self._clients[run_id].add(id(queue))

        try:
            # 立即发送首条注释，触发客户端 onopen（绕过浏览器超时）
            yield ": connected\n\n"
            while True:
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    yield payload
                except asyncio.TimeoutError:
                    # 15s 心跳：触发代理/浏览器 keep-alive
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            logger.info("SSE subscribe cancelled: run_id=%s", run_id)
        finally:
            self._disconnect_client(run_id, id(queue))

    async def push(self, run_id: str, event_type: str, data: dict) -> None:
        """向指定 run_id 的队列推送事件。"""
        queue = self._queues.get(run_id)
        if queue is None:
            logger.debug("No SSE subscriber for run_id=%s, event dropped", run_id)
            return
        try:
            await asyncio.wait_for(queue.put((event_type, data)), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("SSE queue full for run_id=%s, event dropped", run_id)

    def disconnect(self, run_id: str) -> None:
        """主动断开指定 run_id 的所有连接。"""
        if run_id in self._queues:
            del self._queues[run_id]
        if run_id in self._clients:
            del self._clients[run_id]

    def _disconnect_client(self, run_id: str, client_id: int) -> None:
        """移除单个客户端引用。"""
        if run_id in self._clients:
            self._clients[run_id].discard(client_id)
            if not self._clients[run_id]:
                del self._clients[run_id]
        if run_id in self._queues and run_id not in self._clients:
            del self._queues[run_id]


# 单例
sse_manager = SseManager()
