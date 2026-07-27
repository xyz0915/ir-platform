"""默认闭环规则相关 Pydantic schema（resolve 预览 / 规则 CRUD）.

后端统一返回 ``{code, data, message}`` 信封；本模块仅定义端点入参。
出参结构见 ``DefaultPipelineService.ResolveResult``（dataclass）。
"""

from typing import Optional

from pydantic import BaseModel, Field


class DefaultRuleCreate(BaseModel):
    """POST /agents/default-pipelines 入参。"""

    preset_id: int = Field(..., description="关联的 pipeline_presets.id（规则与 pipeline 解耦）")
    name: Optional[str] = Field(None, description="规则展示名（缺省取 preset.name）")
    scene_condition: dict = Field(
        default_factory=dict,
        description="场景条件 JSON：{'category': str|null, 'priority': str|null}，AND 组合",
    )
    is_global: bool = Field(False, description="是否为全局默认（无条件兜底，全表唯一）")
    priority_order: int = Field(0, description="场景规则间确定性排序（小者优先）")


class DefaultRuleUpdate(BaseModel):
    """PUT /agents/default-pipelines/{rule_id} 入参（全字段可选）。"""

    name: Optional[str] = Field(None, description="规则展示名")
    scene_condition: Optional[dict] = Field(None, description="场景条件 JSON")
    is_global: Optional[bool] = Field(None, description="是否设为全局默认")
    priority_order: Optional[int] = Field(None, description="场景规则排序")


class ResolvePreviewQuery(BaseModel):
    """GET /agents/default-pipelines/resolve 入参。

    仅用于「预览」，允许前端显式传 category/priority 覆盖映射结果
    （事件属性查不到时手动指定，§7.4）。
    """

    event_id: Optional[str] = Field(None, description="安全事件 ID")
    category: Optional[str] = Field(None, description="显式覆盖 category（可选）")
    priority: Optional[str] = Field(None, description="显式覆盖 priority（可选）")
