"""采集器基类 — 所有采集器的抽象基类."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Union

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """采集器抽象基类.

    所有具体采集器继承此类，实现 collect() 方法.

    Attributes:
        name: 采集器名称.
        platform: 支持的平台列表 (["windows"], ["linux"], ["windows", "linux"]).
    """

    name: str = "base"
    platform: list = ["windows", "linux"]

    def __init__(self) -> None:
        """初始化采集器."""
        self.logger = logging.getLogger(f"collector.{self.name}")

    @abstractmethod
    def collect(self) -> Union[list, dict]:
        """执行采集逻辑（子类必须实现）.

        Returns:
            采集结果（列表或字典）.
        """
        pass

    def is_supported(self) -> bool:
        """检查当前平台是否支持此采集器.

        Returns:
            当前平台是否在支持列表中.
        """
        from utils.platform import is_windows, is_linux
        if "windows" in self.platform and is_windows():
            return True
        if "linux" in self.platform and is_linux():
            return True
        if "all" in self.platform:
            return True
        return False

    def safe_collect(self) -> Union[list, dict]:
        """安全执行采集，捕获异常不中断.

        Returns:
            采集结果，失败时返回错误字典.
        """
        try:
            return self.collect()
        except Exception as exc:
            self.logger.exception("Collector %s failed: %s", self.name, exc)
            return {"error": str(exc), "collector": self.name}
