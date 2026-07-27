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

    async def subscribe(self, run_id: str, history: Optional[list] = None) -> AsyncGenerator[str, None]:
        """为 run_id 创建一个异步生成器，用于 SSE StreamingResponse。

        P1-3.2: 支持传入 history 事件列表，在实时流开始前回放已完成阶段的状态。

        yield 格式: "event: {event_type}\ndata: {json}\n\n"
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues[run_id] = queue
        if run_id not in self._clients:
            self._clients[run_id] = set()
        self._clients[run_id].add(id(queue))

        try:
            # 立即发送首条注释，触发客户端 onopen（绕过浏览器超时）
            yield ": connected\n\n"
            # P1-3.2: SSE 重连时回放历史事件（已完成 stages 的状态）
            if history:
                for event_type, data in history:
                    payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    yield payload
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
        """向指定 run_id 的队列推送事件。

        P0-3.1: 队列满时丢弃最早事件（非阻塞），优先保留最新事件；
        确保 run_completed / pipeline_complete 等关键状态事件不被丢弃。
        """
        queue = self._queues.get(run_id)
        if queue is None:
            logger.debug("No SSE subscriber for run_id=%s, event dropped", run_id)
            return
        try:
            # 非阻塞写入 — 若队列满则挤掉最早的未消费事件
            queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            try:
                # 丢旧保新：弹出最早事件再写入
                queue.get_nowait()
                queue.put_nowait((event_type, data))
                logger.warning(
                    "SSE queue full for run_id=%s, dropped oldest event (type=%s)",
                    run_id, event_type,
                )
            except asyncio.QueueEmpty:
                # 并发竞争：其他消费者刚取走了元素，重试写入
                try:
                    queue.put_nowait((event_type, data))
                except asyncio.QueueFull:
                    logger.warning(
                        "SSE queue still full for run_id=%s, event dropped (type=%s)",
                        run_id, event_type,
                    )

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
