"""时钟同步模块：检测本地时钟与服务端时钟偏差，修正采集时间戳."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)


class ClockSync:
    """时钟偏差检测与时间戳修正工具.

    在 agent 启动时检测本地时钟与服务端时钟的偏差（offset = server - local），
    并在 ``build_output()`` 阶段对所有时间戳做修正，确保最终输出时间与服务端一致.
    """

    @staticmethod
    async def detect_offset(server_url: str = "http://localhost:8000") -> float:
        """检测本地时钟与服务端时钟偏差（秒）.

        调用 ``GET {server_url}/api/time`` 获取服务端时间，
        计算 ``offset = server_time - local_time``。

        Args:
            server_url: 服务端基础 URL.

        Returns:
            时钟偏差值（秒）。正数表示服务端时间比本地快；失败时返回 0.0 并记录警告.
        """
        import asyncio
        try:
            local_before = datetime.now(timezone.utc)

            # 使用 asyncio.to_thread 在后台线程执行同步 HTTP 请求
            response_data = await asyncio.to_thread(
                ClockSync._do_http_request, f"{server_url}/api/time"
            )

            local_after = datetime.now(timezone.utc)

            if response_data is None:
                return 0.0

            # 解析服务端返回的时间
            server_time_str = response_data.get("server_time") or response_data.get("time")
            if not server_time_str:
                logger.warning(
                    "ClockSync: server response missing time field: %s",
                    response_data,
                )
                return 0.0

            # 解析服务端时间（支持 ISO 8601 格式）
            server_dt = datetime.fromisoformat(server_time_str)
            if server_dt.tzinfo is None:
                server_dt = server_dt.replace(tzinfo=timezone.utc)

            # 取请求前后的本地时间中点，减少网络延迟影响
            local_mid = local_before + (local_after - local_before) / 2

            offset = (server_dt - local_mid).total_seconds()

            if abs(offset) > 30.0:
                logger.warning(
                    "ClockSync: clock offset %.1f seconds exceeds 30s threshold "
                    "(server=%s, local=%s)",
                    offset, server_time_str, local_mid.isoformat(),
                )

            logger.info("ClockSync: detected offset=%.3f seconds", offset)
            return offset

        except Exception as exc:
            logger.warning("ClockSync: failed to detect offset: %s", exc)
            return 0.0

    @staticmethod
    def adjust_timestamp(ts: str, offset: float) -> str:
        """根据时钟偏差修正时间戳.

        将标准化后的时间戳减去 offset 秒，得到修正后的服务端时间。

        Args:
            ts: 标准化后的 ISO 8601 时间字符串.
            offset: 时钟偏差（秒），来自 ``detect_offset()`` 返回值.

        Returns:
            修正后的 ISO 8601 时间字符串（带时区）。若输入无效或 offset 为 0，返回原值.
        """
        if not ts or offset == 0.0:
            return ts

        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                # 无时区时假设为 UTC+8（与标准化后的格式一致）
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            # 修正：减去 offset（因为 offset = server - local，
            # 所以修正后时间 = 本地时间 + offset = 服务端时间）
            dt += timedelta(seconds=offset)
            return dt.isoformat()
        except (ValueError, TypeError) as exc:
            logger.warning(
                "ClockSync.adjust_timestamp: failed to adjust '%s': %s",
                ts, exc,
            )
            return ts

    @staticmethod
    def _do_http_request(url: str) -> Optional[dict]:
        """执行同步 HTTP GET 请求并返回 JSON 数据.

        Args:
            url: 请求 URL.

        Returns:
            解析后的 JSON 字典，失败时返回 None.
        """
        try:
            req = Request(url, method="GET")
            # 设置超时 5 秒
            with urlopen(req, timeout=5) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except (URLError, json.JSONDecodeError, OSError) as exc:
            logger.warning("ClockSync: HTTP request failed for %s: %s", url, exc)
            return None
