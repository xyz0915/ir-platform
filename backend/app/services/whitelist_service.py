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

    @staticmethod
    def is_whitelisted_precise(rule: dict, item: dict) -> bool:
        """精确加白检查（P0 接入点；P1-1 扩展 signature 指纹豁免）.

        当前实现：复用既有 path / process_name 类别白名单（实体级豁免），
        signature 类别通过 DB 精确等值匹配（T-P1-2）。

        Args:
            rule: 规则字典（预留 rule_type/category 维度扩展）。
            item: 扁平化引擎数据项（读 path / name）。

        Returns:
            命中白名单返回 True（该命中应被排除、不告警）。
        """
        # path 和 process_name 类别走已有逻辑
        path_match = WhitelistService._match_path(item)
        if path_match:
            return True

        name_match = WhitelistService._match_process_name(item)
        if name_match:
            return True

        # T-P1-2: signature 类别精确等值匹配
        # 从 item 中提取可用于签名匹配的字段（command_line 完整值，或 name 完整值）
        signature_value = None
        if rule:
            rule_type = rule.get("rule_type", "")
            if rule_type == "regex":
                # 对 regex 规则，取 command_line 作为签名指纹
                signature_value = str(item.get("command_line", item.get("name", "")))
            elif rule_type in ("list", "threshold"):
                # list/threshold 规则，取 name 或 path 作为签名
                signature_value = str(item.get("name", item.get("path", "")))
            else:
                # 默认取 name 作为签名指纹
                signature_value = str(item.get("name", ""))

        if signature_value:
            try:
                with get_connection() as conn:
                    # 先探明 whitelist 表的列名
                    cursor = conn.execute("PRAGMA table_info(whitelist)")
                    cols = {r["name"] for r in cursor.fetchall()}
                    pattern_col = "pattern" if "pattern" in cols else "value"
                    row = conn.execute(
                        f"SELECT COUNT(*) as cnt FROM whitelist WHERE category='signature' AND {pattern_col}=? AND enabled=1",
                        (signature_value,),
                    ).fetchone()
                    if row and row["cnt"] > 0:
                        logger.debug(
                            "Signature whitelist exact match: rule=%s, value=%s",
                            rule.get("name", ""), signature_value[:80],
                        )
                        return True
            except Exception as exc:
                logger.warning("Signature whitelist check failed: %s", exc)

        return False

    @staticmethod
    def _match_path(item: dict) -> bool:
        """检查 item.path 是否匹配 path 类别白名单."""
        proc_path = str(item.get("path", "")).lower()
        if not proc_path:
            return False
        try:
            whitelist_items = WhitelistModel.list_all(category="path")
            enabled_items = [it for it in whitelist_items if it.get("enabled", 0) == 1]
            for wl in enabled_items:
                pattern = str(wl.get("pattern", "")).lower()
                if pattern and pattern in proc_path:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _match_process_name(item: dict) -> bool:
        """检查 item.name 是否匹配 process_name 类别白名单."""
        proc_name = str(item.get("name", "")).lower()
        if not proc_name:
            return False
        try:
            whitelist_items = WhitelistModel.list_all(category="process_name")
            enabled_items = [it for it in whitelist_items if it.get("enabled", 0) == 1]
            for wl in enabled_items:
                pattern = str(wl.get("pattern", "")).lower()
                if pattern and proc_name == pattern:
                    return True
        except Exception:
            pass
        return False
