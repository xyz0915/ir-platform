"""Agent 定义模型 — agent_definitions / pipeline_presets 表 CRUD."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


def _j(value: Any) -> str:
    """将 Python 对象序列化为 JSON 字符串."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _d(value: Any, default: Any = None) -> Any:
    """将 JSON 字符串反序列化为 Python 对象."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _auto_json_fields(row_dict: dict, fields: list[str]) -> dict:
    """自动将指定字段从 JSON 字符串解析为 Python 对象."""
    for field in fields:
        if field in row_dict and isinstance(row_dict[field], str):
            row_dict[field] = _d(row_dict[field], [] if field != "config" else {})
    return row_dict


class AgentDefinitionModel:
    """Agent 定义表 CRUD — agent_definitions."""

    JSON_FIELDS = ["data_sources", "depends_on", "config", "tools"]

    @staticmethod
    def create(data: dict) -> dict:
        """插入一条 Agent 定义记录."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_definitions
                    (name, display_name, type, description, data_sources,
                     depends_on, prompt_template, config, enabled, hitl,
                     tools, model_profile)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data.get("display_name", data["name"]),
                    data.get("type", "custom"),
                    data.get("description", ""),
                    _j(data.get("data_sources", [])),
                    _j(data.get("depends_on", [])),
                    data.get("prompt_template", ""),
                    _j(data.get("config", {})),
                    1 if data.get("enabled", True) else 0,
                    1 if data.get("hitl", False) else 0,
                    _j(data.get("tools", [])),
                    data.get("model_profile", ""),
                ),
            )
            rid = cursor.lastrowid
        return AgentDefinitionModel.get_by_id(rid)

    @staticmethod
    def get(name: str) -> Optional[dict]:
        """按 name 查询 Agent 定义."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_definitions WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            return _auto_json_fields(result, AgentDefinitionModel.JSON_FIELDS)

    @staticmethod
    def get_by_id(rid: int) -> Optional[dict]:
        """按主键 id 查询 Agent 定义."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_definitions WHERE id = ?", (rid,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            return _auto_json_fields(result, AgentDefinitionModel.JSON_FIELDS)

    @staticmethod
    def update(name: str, updates: dict) -> Optional[dict]:
        """局部更新 Agent 定义，返回更新后的记录.

        Args:
            name: Agent 名称（唯一标识）.
            updates: 要更新的字段字典.

        Returns:
            更新后的完整记录，或 None（如果记录不存在）.
        """
        allowed = {
            "display_name", "type", "description", "data_sources",
            "depends_on", "prompt_template", "config", "enabled", "hitl",
            "tools", "model_profile",
        }
        data = {}
        for k in allowed:
            if k in updates:
                raw = updates[k]
                if k in ("data_sources", "depends_on", "tools"):
                    data[k] = _j(raw)
                elif k == "config":
                    data[k] = _j(raw)
                elif k in ("enabled", "hitl"):
                    data[k] = 1 if raw else 0
                else:
                    data[k] = raw
        if not data:
            return AgentDefinitionModel.get(name)

        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(name)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE agent_definitions SET {', '.join(clauses)}, "
                f"updated_at = datetime('now') WHERE name = ?",
                values,
            )
        return AgentDefinitionModel.get(name)

    @staticmethod
    def delete(name: str) -> bool:
        """删除 Agent 定义。如果有 pipeline_presets 引用则返回 False。

        Returns:
            True 表示删除成功，False 表示被引用无法删除或记录不存在.
        """
        # 检查是否有 pipeline_presets 引用该 agent
        with get_connection() as conn:
            presets = conn.execute(
                "SELECT id, agents FROM pipeline_presets"
            ).fetchall()
            for preset in presets:
                agents_list = _d(preset["agents"], [])
                if name in agents_list:
                    logger.warning(
                        "Cannot delete agent '%s': referenced by pipeline_preset id=%d",
                        name, preset["id"],
                    )
                    return False

            cursor = conn.execute(
                "DELETE FROM agent_definitions WHERE name = ?", (name,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def list(enabled_only: bool = True) -> list[dict]:
        """列出 Agent 定义列表.

        Args:
            enabled_only: 是否只返回已启用的 Agent.

        Returns:
            记录列表，自动解析 JSON 字段.
        """
        with get_connection() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM agent_definitions WHERE enabled = 1 ORDER BY name ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_definitions ORDER BY name ASC"
                ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            results.append(_auto_json_fields(d, AgentDefinitionModel.JSON_FIELDS))
        return results

    @staticmethod
    def count() -> int:
        """返回 Agent 定义总数."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM agent_definitions"
            ).fetchone()
            return row[0] if row else 0


class PipelinePresetModel:
    """Pipeline 预设表 CRUD — pipeline_presets."""

    @staticmethod
    def create(data: dict) -> dict:
        """创建一条 Pipeline 预设（含元数据字段）.

        Args:
            data: 预设数据。支持字段：
                name(必填), description, agents(必填, list[str]),
                author, category, tags(list[str]), usage_count, last_used_at,
                status('draft'/'published'，默认 draft；非法值回退 draft)。
                缺失的元数据字段使用默认值。
        """
        agents = data.get("agents", [])
        agents_str = json.dumps(agents, ensure_ascii=False) if isinstance(agents, list) else str(agents)
        tags = data.get("tags", [])
        tags_str = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else str(tags)
        # A2 发布语义：status 白名单校验（draft / published），非法回退 draft
        status = data.get("status", "draft")
        if status not in ("draft", "published"):
            status = "draft"
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_presets
                    (name, description, agents, author, category, tags,
                     usage_count, last_used_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data.get("description", ""),
                    agents_str,
                    data.get("author", ""),
                    data.get("category", "other"),
                    tags_str,
                    int(data.get("usage_count", 0) or 0),
                    data.get("last_used_at"),
                    status,
                ),
            )
            pid = cursor.lastrowid
        return PipelinePresetModel.get(pid)

    @staticmethod
    def get(pid: int) -> Optional[dict]:
        """按主键查询 Pipeline 预设，自动解析 agents / tags JSON."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_presets WHERE id = ?", (pid,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["agents"] = _d(result.get("agents"), [])
            result["tags"] = _d(result.get("tags"), [])
            return result

    @staticmethod
    def list() -> list[dict]:
        """列出所有 Pipeline 预设，自动解析 agents / tags JSON."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_presets ORDER BY name ASC"
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["agents"] = _d(d.get("agents"), [])
            d["tags"] = _d(d.get("tags"), [])
            results.append(d)
        return results

    @staticmethod
    def get_by_name(name: str) -> Optional[dict]:
        """按 name 查询 Pipeline 预设，自动解析 agents / tags JSON. 返回 None 表示不存在."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_presets WHERE name = ?", (name,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["agents"] = _d(result.get("agents"), [])
        result["tags"] = _d(result.get("tags"), [])
        return result

    @staticmethod
    def delete(pid: int) -> bool:
        """删除 Pipeline 预设."""
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pipeline_presets WHERE id = ?", (pid,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def update(pid: int, updates: dict) -> Optional[dict]:
        """局部更新 Pipeline 预设（如 name / description / agents）.

        Args:
            pid: 预设主键 id。
            updates: 要更新的字段字典（允许 name / description / agents）。

        Returns:
            更新后的完整记录，或 None（记录不存在）。
        """
        allowed = {"name", "description", "agents", "status"}
        data: dict[str, Any] = {}
        for k in allowed:
            if k not in updates:
                continue
            v = updates[k]
            if k == "agents":
                data[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
            else:
                data[k] = v
        if not data:
            return PipelinePresetModel.get(pid)
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(pid)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE pipeline_presets SET {', '.join(clauses)}, "
                f"updated_at = datetime('now') WHERE id = ?",
                values,
            )
        return PipelinePresetModel.get(pid)

    @staticmethod
    def increment_usage(preset_id: int) -> bool:
        """记录一次预设加载使用：usage_count +1 并刷新 last_used_at.

        Args:
            preset_id: 预设主键 id。

        Returns:
            True 表示更新成功，False 表示预设不存在。
        """
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE pipeline_presets SET usage_count = usage_count + 1, "
                "last_used_at = datetime('now') WHERE id = ?",
                (preset_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def update_meta(preset_id: int, **kwargs: Any) -> Optional[dict]:
        """更新预设元数据字段（白名单：category / tags / description / status）.

        与 update() 不同，该方法仅允许修改展示型元数据，避免误改
        name / agents 等结构性字段；tags 传入 list 时自动序列化为 JSON。
        status 允许 draft/published 流转（A2 发布语义，非法回退 draft）。

        Args:
            preset_id: 预设主键 id。
            **kwargs: 允许 category / tags / description / status 四个字段。

        Returns:
            更新后的完整记录，或 None（记录不存在）。
        """
        allowed = {"category", "tags", "description", "status"}
        data: dict[str, Any] = {}
        for k in allowed:
            if k not in kwargs:
                continue
            v = kwargs[k]
            if k == "tags":
                data[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
            else:
                data[k] = v
        if not data:
            return PipelinePresetModel.get(preset_id)
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(preset_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE pipeline_presets SET {', '.join(clauses)} WHERE id = ?",
                values,
            )
        return PipelinePresetModel.get(preset_id)
