"""采集健康状态累加器（任务③）.

collector 在 run_collectors 中逐个执行，每完成一个就记录其状态/数量/告警。
最终 build() 产出符合 §3.2 的 collection_health 顶层字段。
"""

from typing import Optional


class CollectorHealth:
    """采集健康状态累加器."""

    def __init__(self) -> None:
        # name -> {"status": "ok"|"degraded"|"failed"|"skipped", "count": int, "warnings": [str]}
        self.collectors: dict[str, dict] = {}
        self.warnings: list[str] = []

    def record(
        self,
        name: str,
        status: str,
        count: int = 0,
        warnings: Optional[list] = None,
    ) -> None:
        """记录单个采集器的健康状态.

        Args:
            name: 采集器名称.
            status: ok / degraded / failed / skipped.
            count: 采集到的条目数.
            warnings: 该采集器的告警信息列表.
        """
        warnings = warnings or []
        self.collectors[name] = {
            "status": status,
            "count": count,
            "warnings": list(warnings),
        }
        for w in warnings:
            self.warnings.append(w)

    def build(self, collected_at: str) -> dict:
        """生成最终 collection_health 结构.

        Args:
            collected_at: 采集完成时间字符串.

        Returns:
            collection_health 字典（见设计 §3.2）.
        """
        summary_parts: list[str] = []
        for status in ("failed", "degraded", "skipped", "ok"):
            n = sum(1 for c in self.collectors.values() if c["status"] == status)
            if n:
                summary_parts.append(f"{n} {status}")
        return {
            "collected_at": collected_at,
            "collectors": self.collectors,
            "warnings": self.warnings,
            "summary": ", ".join(summary_parts) if summary_parts else "all ok",
        }
