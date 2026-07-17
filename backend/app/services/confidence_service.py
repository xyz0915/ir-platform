"""可信度评估服务 — 基于数据源数量 / 推理链长度 / 证据充分性."""
from typing import Any


class ConfidenceService:
    """可信度评估 — 返回 high / medium / low."""

    @staticmethod
    def evaluate(data: Any, source_count: int = 0, query: str = "") -> dict:
        """
        综合评估可信度。
        
        Args:
            data: 查询结果数据（list 或 dict）
            source_count: 数据源数量
            query: 原始查询（用于关键词分析）
            
        Returns:
            {"level": "high"|"medium"|"low", "reason": str, "source_ids": list[str]}
        """
        # 1. 数据是否为空
        if not data:
            return {"level": "low", "reason": "无数据支撑", "source_ids": []}
        
        items = data if isinstance(data, list) else [data]
        item_count = len(items)
        
        # 2. 基于数据量判断
        if item_count >= 5 and source_count >= 2:
            return {"level": "high", "reason": f"{item_count} 条记录来自 {source_count} 个数据源", "source_ids": []}
        elif item_count >= 2:
            return {"level": "medium", "reason": f"{item_count} 条记录，建议核实关键数据", "source_ids": []}
        else:
            return {"level": "low", "reason": "仅 1 条记录，请进一步确认", "source_ids": []}
