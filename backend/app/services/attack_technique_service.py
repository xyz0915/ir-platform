"""MITRE ATT&CK 覆盖库查询服务（v1.3.0 支柱④）.

提供技术点查表能力：未知技术点统一返回「待确认」，禁止 AI 杜撰。
数据来自静态内置快照 ``app/data/mitre_attack_coverage.json``（Enterprise 2024-06）。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class AttackTechniqueService:
    """ATT&CK 技术点查表服务（无状态、只读）."""

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_coverage() -> dict:
        """加载静态 ATT&CK 覆盖库（带缓存）.

        Returns:
            完整的覆盖库 dict（含 _meta 与 techniques）。
        """
        path = Path(settings.BACKEND_DIR) / "app" / "data" / "mitre_attack_coverage.json"
        if not path.exists():
            logger.warning("MITRE ATT&CK 覆盖库不存在: %s", path)
            return {"techniques": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("MITRE ATT&CK 覆盖库格式异常")
                return {"techniques": {}}
            data.setdefault("techniques", {})
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("MITRE ATT&CK 覆盖库加载失败: %s", exc)
            return {"techniques": {}}

    @classmethod
    def get_technique(cls, technique_id: str) -> dict:
        """查询单个技术点.

        Args:
            technique_id: 技术点 ID（如 ``T1059.001``）。

        Returns:
            ``{"id", "name", "tactic", "tactic_id", "known": bool}``；
            未知时 ``name="待确认"``、``known=False``。
        """
        tid = (technique_id or "").strip().upper()
        techniques = cls._load_coverage().get("techniques", {})
        info = techniques.get(tid)
        if info:
            return {
                "id": tid,
                "name": info.get("name", tid),
                "tactic": info.get("tactic", ""),
                "tactic_id": info.get("tactic_id", ""),
                "known": True,
            }
        return {
            "id": tid,
            "name": "待确认",
            "tactic": "",
            "tactic_id": "",
            "known": False,
        }

    @classmethod
    def resolve(cls, technique_ids: list[str]) -> list[dict]:
        """批量查询技术点，保留输入顺序并去重.

        Args:
            technique_ids: 技术点 ID 列表（可能含未知/脏数据）。

        Returns:
            技术点信息列表（每个元素见 ``get_technique``）。
            非法/空值会被跳过，但空串仍对应一个「待确认」占位以便前端展示。
        """
        result: list[dict] = []
        seen: set[str] = set()
        for tid in technique_ids or []:
            if tid is None:
                continue
            key = str(tid).strip().upper()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(cls.get_technique(key))
        return result

    @classmethod
    def invalidate_cache(cls) -> None:
        """使覆盖库缓存失效（测试或热更新时使用）."""
        cls._load_coverage.cache_clear()
