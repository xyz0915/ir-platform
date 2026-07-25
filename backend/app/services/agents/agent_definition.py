"""Agent 定义传输层 — 纯 Python dataclass，用于 API 传输与业务逻辑."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentDefinition:
    """Agent 定义 dataclass（非 DB 模型，用于 API 传输）.

    Attributes:
        name: Agent 唯一标识名.
        display_name: 显示名称.
        type: 类型（"built-in" | "custom"）.
        description: 描述信息.
        data_sources: 数据源列表.
        depends_on: 依赖的其他 Agent 名称列表.
        prompt_template: 提示词模板.
        config: 配置字典.
        enabled: 是否启用.
        hitl: 是否需人工审批（Human-in-the-Loop）.
        created_at: 创建时间.
        updated_at: 更新时间.
    """

    name: str
    display_name: str
    type: str = "custom"
    description: str = ""
    data_sources: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    prompt_template: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    hitl: bool = False
    tools: list[str] = field(default_factory=list)
    model_profile: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """将 dataclass 转换为字典."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "type": self.type,
            "description": self.description,
            "data_sources": list(self.data_sources),
            "depends_on": list(self.depends_on),
            "prompt_template": self.prompt_template,
            "config": dict(self.config),
            "enabled": self.enabled,
            "hitl": self.hitl,
            "tools": list(self.tools),
            "model_profile": self.model_profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "AgentDefinition":
        """从字典创建 AgentDefinition dataclass.

        Args:
            data: 包含 Agent 字段的字典（来自 DB 或 API 请求）.

        Returns:
            AgentDefinition 实例.
        """
        return AgentDefinition(
            name=data.get("name", ""),
            display_name=data.get("display_name", data.get("name", "")),
            type=data.get("type", "custom"),
            description=data.get("description", ""),
            data_sources=list(data.get("data_sources", [])),
            depends_on=list(data.get("depends_on", [])),
            prompt_template=data.get("prompt_template", ""),
            config=dict(data.get("config", {})),
            enabled=bool(data.get("enabled", True)),
            hitl=bool(data.get("hitl", False)),
            tools=list(data.get("tools", [])),
            model_profile=data.get("model_profile", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
