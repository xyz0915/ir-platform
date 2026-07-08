"""白名单服务 — 白名单的 CRUD 和进程过滤逻辑."""

import logging
from typing import Any, Optional

from app.database import get_connection
from app.models.whitelist import WhitelistModel

logger = logging.getLogger(__name__)


class WhitelistService:
    """白名单服务.

    提供白名单的 CRUD 操作以及进程过滤逻辑。
    """

    @staticmethod
    def get_all(category: Optional[str] = None) -> list:
        """获取白名单列表.

        Args:
            category: 按类别筛选（可选）.

        Returns:
            白名单项列表.
        """
        return WhitelistModel.list_all(category=category)

    @staticmethod
    def get_by_id(id: int) -> Optional[dict]:
        """按 ID 获取白名单项.

        Args:
            id: 白名单项 ID.

        Returns:
            白名单项字典.
        """
        return WhitelistModel.get_by_id(id)

    @staticmethod
    def create(category: str, pattern: str, description: str = "") -> dict:
        """创建白名单项.

        Args:
            category: 类别（path / process_name / signature）.
            pattern: 匹配值.
            description: 描述.

        Returns:
            创建结果.
        """
        items = [{"category": category, "pattern": pattern, "source": "user", "description": description, "enabled": True}]
        count = WhitelistModel.batch_create(items)
        return {"created": count}

    @staticmethod
    def update(id: int, category: str = None, pattern: str = None,
               description: str = None, enabled: bool = None) -> bool:
        """更新白名单项.

        Args:
            id: 白名单项 ID.
            category: 新类别（可选）.
            pattern: 新匹配值（可选）.
            description: 新描述（可选）.
            enabled: 是否启用（可选）.

        Returns:
            是否更新成功.
        """
        with get_connection() as conn:
            existing = WhitelistModel.get_by_id(id)
            if not existing:
                return False

            updates = {}
            if category is not None:
                updates["category"] = category
            if pattern is not None:
                updates["pattern"] = pattern
            if description is not None:
                updates["description"] = description
            if enabled is not None:
                updates["enabled"] = 1 if enabled else 0

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                values = list(updates.values()) + [id]
                conn.execute(f"UPDATE whitelist SET {set_clause} WHERE id = ?", values)
                return True
            return False

    @staticmethod
    def delete(id: int) -> bool:
        """删除白名单项.

        Args:
            id: 白名单项 ID.

        Returns:
            是否删除成功.
        """
        return WhitelistModel.delete_by_id(id)

    @staticmethod
    def is_whitelisted(process: dict) -> bool:
        """判断单个进程是否在白名单中.

        - path 类别：pattern in process['path'].lower()
        - process_name 类别：process['name'].lower() == pattern.lower()
        - 只检查 enabled=1 的项

        Args:
            process: 进程数据项字典.

        Returns:
            是否在白名单中.
        """
        whitelist_items = WhitelistModel.list_all()
        enabled_items = [item for item in whitelist_items if item.get("enabled", 0) == 1]

        proc_path = str(process.get("path", "")).lower()
        proc_name = str(process.get("name", "")).lower()

        for item in enabled_items:
            category = item.get("category", "")
            pattern = str(item.get("pattern", "")).lower()

            if category == "path" and pattern:
                if pattern in proc_path:
                    return True
            elif category == "process_name" and pattern:
                if proc_name == pattern:
                    return True
            elif category == "signature" and pattern:
                # signature 类别暂不做匹配，预留扩展
                pass

        return False

    @staticmethod
    def filter_whitelisted(processes: list) -> list:
        """过滤掉白名单进程，返回非白名单进程列表.

        Args:
            processes: 进程列表.

        Returns:
            过滤后的进程列表（仅包含非白名单进程）.
        """
        # 获取所有启用的白名单项（一次性查询，避免重复查询）
        whitelist_items = WhitelistModel.list_all()
        enabled_items = [item for item in whitelist_items if item.get("enabled", 0) == 1]

        # 构建快速查找集合
        path_patterns: list[str] = []
        name_patterns: set[str] = set()

        for item in enabled_items:
            category = item.get("category", "")
            pattern = str(item.get("pattern", "")).lower()
            if category == "path" and pattern:
                path_patterns.append(pattern)
            elif category == "process_name" and pattern:
                name_patterns.add(pattern)

        # 过滤
        filtered = []
        for proc in processes:
            if not isinstance(proc, dict):
                continue
            proc_path = str(proc.get("path", "")).lower()
            proc_name = str(proc.get("name", "")).lower()

            # 检查路径白名单
            is_path_whitelisted = any(p in proc_path for p in path_patterns)
            # 检查进程名白名单
            is_name_whitelisted = proc_name in name_patterns

            if not is_path_whitelisted and not is_name_whitelisted:
                filtered.append(proc)

        logger.info(
            "Whitelist filtering: %d → %d (removed %d)",
            len(processes), len(filtered), len(processes) - len(filtered),
        )
        return filtered
