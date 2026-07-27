"""默认闭环匹配服务（场景匹配 → 全局默认 → 硬编码兜底）.

职责（架构 §1.3 / §3.4）：
- ``resolve_default_pipeline(event) -> ResolveResult``：三级解析；
- ``list_rules / create_rule / update_rule / delete_rule``：规则 CRUD；
- ``validate_default_pipeline(agent_names)``：默认 pipeline 最小节点约束强校验。

匹配逻辑与执行（Orchestrator）、注册表（AgentRegistry）正交，独立 service 便于单测。
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.models.pipeline_default_rule import PipelineDefaultRuleModel
from app.models.agent_definition import PipelinePresetModel
from app.services.agents.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)

# severity → priority 映射（§7.4）：critical→P0 / high→P1 / medium→P2 / low→P3
SEVERITY_TO_PRIORITY = {
    "critical": "P0",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
}


class DefaultPipelineError(ValueError):
    """默认规则业务错误，携带建议的 HTTP 状态码."""

    status_code: int = 400


class GlobalDefaultConflict(DefaultPipelineError):
    """全局默认已存在（创建第二条时返回 409）."""

    status_code = 409


@dataclass
class ResolveResult:
    """resolve 结果结构（§7.2）.

    match_type: 'scene' | 'global' | 'hardcoded'
    scene/global 时 preset_id/preset_name/agent_names/rule_id/scene_condition 均非空；
    hardcoded 时 preset_id/agent_names 为 None，调用方走 run_pipeline。
    """

    match_type: str
    preset_id: Optional[int] = None
    preset_name: Optional[str] = None
    agent_names: Optional[list] = None
    rule_id: Optional[int] = None
    scene_condition: Optional[dict] = None
    is_global: bool = False
    message: str = ""


class DefaultPipelineService:
    """默认闭环匹配服务（无状态，可安全实例化/复用）."""

    # ──────────────────────────────────────────────────────────────
    # 三级解析：场景规则 → 全局默认 → 硬编码兜底
    # ──────────────────────────────────────────────────────────────

    def resolve_default_pipeline(self, event: dict) -> ResolveResult:
        """三级解析默认 pipeline。

        Args:
            event: 至少含 ``event_id``；可直接携带 ``category`` / ``priority`` 覆盖映射。
                优先级：直读 event > 从 security_events 映射（event_type→category,
                severity→priority）。

        Returns:
            ResolveResult：命中 scene / global 返回 agent_names；否则 hardcoded 兜底。
        """
        event_id = event.get("event_id")
        category = event.get("category")
        priority = event.get("priority")

        # 事件属性来源与映射（§7.4）：直读缺失时从 security_events 映射
        if (category is None or priority is None) and event_id:
            mapped = self._load_event_attributes(event_id)
            if category is None:
                category = mapped.get("category")
            if priority is None:
                priority = mapped.get("priority")

        rules = PipelineDefaultRuleModel.list()

        # 1) 场景规则匹配：在所有命中约束的规则中选择「最具体优先」
        #    （最具体 = scene_condition 中非 null 维度最多的规则）；
        #    同分时按 priority_order ASC、id ASC 确定（更小优先）。
        best_match = None  # (rule, preset, score)
        for rule in rules:
            if rule.get("is_global"):
                continue
            cond = rule.get("scene_condition") or {}
            rc = cond.get("category")
            rp = cond.get("priority")
            if rc is not None and rc != category:
                continue
            if rp is not None and rp != priority:
                continue
            # 命中：以非 null 约束维度数打分（维度越多越具体）
            score = (1 if rc is not None else 0) + (1 if rp is not None else 0)
            preset = PipelinePresetModel.get(rule["preset_id"])
            if not preset:
                continue
            if best_match is None or score > best_match[2]:
                best_match = (rule, preset, score)
            elif score == best_match[2]:
                # 同分按 priority_order ASC、id ASC 保持稳定
                existing_rule = best_match[0]
                if (rule.get("priority_order", 0) or 0) < (existing_rule.get("priority_order", 0) or 0):
                    best_match = (rule, preset, score)
                elif (rule.get("priority_order", 0) or 0) == (existing_rule.get("priority_order", 0) or 0) and (rule["id"] < existing_rule["id"]):
                    best_match = (rule, preset, score)

        if best_match:
            rule, preset, _score = best_match
            return ResolveResult(
                match_type="scene",
                preset_id=preset["id"],
                preset_name=preset["name"],
                agent_names=preset.get("agents") or [],
                rule_id=rule["id"],
                scene_condition=rule.get("scene_condition"),
                is_global=False,
                message="命中场景规则",
            )

        # 2) 全局默认（无条件兜底，全表唯一）
        globals = [r for r in rules if r.get("is_global")]
        if globals:
            g = globals[0]
            preset = PipelinePresetModel.get(g["preset_id"])
            if preset:
                return ResolveResult(
                    match_type="global",
                    preset_id=preset["id"],
                    preset_name=preset["name"],
                    agent_names=preset.get("agents") or [],
                    rule_id=g["id"],
                    scene_condition=g.get("scene_condition"),
                    is_global=True,
                    message="使用全局默认",
                )

        # 3) 硬编码兜底（保持现状，零配置兼容）
        return ResolveResult(
            match_type="hardcoded",
            preset_id=None,
            preset_name=None,
            agent_names=None,
            rule_id=None,
            scene_condition=None,
            is_global=False,
            message="无默认配置，回退硬编码 4 阶段",
        )

    def _load_event_attributes(self, event_id: str) -> dict:
        """从 security_events 映射出 category/priority（§7.4）.

        SQL 只查 security_events 现有列（event_type, severity）；
        Python 层映射：category ← event_type, priority ← severity_to_priority(severity)。
        向前兼容：若 row 含 category/priority 列（未来 schema 扩展）则优先使用。
        """
        from app.database import get_connection

        eid = event_id.split(":")[-1] if ":" in event_id else event_id
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT event_type, severity FROM security_events WHERE id = ? LIMIT 1",
                    (eid,),
                ).fetchone()
                if not row:
                    return {}
                # 用 dict() 转换以提供向前兼容的 .get() 访问（未来加列不影响）
                rd = dict(row)
                category = rd.get("category") or rd["event_type"]
                severity = (rd.get("severity") or "").lower()
                priority = rd.get("priority") or SEVERITY_TO_PRIORITY.get(severity, None)
                return {"category": category, "priority": priority}
        except Exception as exc:
            logger.warning(
                "resolve 事件属性映射失败 (event_id=%s): %s", event_id, exc
            )
            return {}

    # ──────────────────────────────────────────────────────────────
    # 规则 CRUD
    # ──────────────────────────────────────────────────────────────

    def list_rules(self) -> list[dict]:
        """列出全部规则，补充 preset_name / agent_count 供管理列表展示."""
        rules = PipelineDefaultRuleModel.list()
        result: list[dict] = []
        for r in rules:
            preset = (
                PipelinePresetModel.get(r["preset_id"]) if r.get("preset_id") else None
            )
            item = dict(r)
            item["preset_name"] = preset["name"] if preset else None
            item["agent_count"] = len(preset.get("agents") or []) if preset else 0
            result.append(item)
        return result

    def create_rule(self, payload: dict, user: Optional[dict]) -> dict:
        """创建规则（写操作，admin）。

        流程：校验 preset 存在 → 全局默认唯一性 → 默认 pipeline 强校验 → 落库。
        """
        preset_id = payload.get("preset_id")
        preset = PipelinePresetModel.get(preset_id) if preset_id else None
        if not preset:
            raise DefaultPipelineError(f"preset_id={preset_id} 不存在")

        is_global = bool(payload.get("is_global"))
        if is_global:
            existing_global = [r for r in PipelineDefaultRuleModel.list() if r.get("is_global")]
            if existing_global:
                raise GlobalDefaultConflict(
                    "全局默认已存在，请先取消现有全局默认再创建"
                )

        # 默认 pipeline 强校验（§1.4.3）：非空 + validate_pipeline + 含 responder
        agents = preset.get("agents") or []
        errors = self.validate_default_pipeline(agents)
        if errors:
            raise DefaultPipelineError("；".join(errors))

        data = {
            "preset_id": preset_id,
            "name": payload.get("name") or preset.get("name"),
            "scene_condition": payload.get("scene_condition", {}) or {},
            "is_global": is_global,
            "priority_order": payload.get("priority_order", 0) or 0,
            "created_by": (user or {}).get("username"),
        }
        return PipelineDefaultRuleModel.create(data)

    def update_rule(self, rule_id: int, payload: dict) -> dict:
        """编辑规则（写操作，admin）."""
        rule = PipelineDefaultRuleModel.get(rule_id)
        if not rule:
            raise DefaultPipelineError(f"规则 #{rule_id} 不存在")

        updates: dict[str, Any] = {}
        if "name" in payload:
            updates["name"] = payload["name"]
        if "priority_order" in payload:
            updates["priority_order"] = payload["priority_order"]
        if "scene_condition" in payload:
            updates["scene_condition"] = payload["scene_condition"] or {}
        if "is_global" in payload:
            is_global = bool(payload["is_global"])
            if is_global and not rule.get("is_global"):
                existing_global = [
                    r for r in PipelineDefaultRuleModel.list() if r.get("is_global")
                ]
                if existing_global:
                    raise GlobalDefaultConflict(
                        "全局默认已存在，请先取消现有全局默认"
                    )
            updates["is_global"] = is_global

        return PipelineDefaultRuleModel.update(rule_id, updates)

    def delete_rule(self, rule_id: int) -> dict:
        """删除规则（写操作，admin）。

        Returns:
            {"deleted": True, "fell_back_to_hardcoded": bool} —— 删全局默认且无其它全局时
            自动回退硬编码（仅告警，不阻断）。
        """
        rule = PipelineDefaultRuleModel.get(rule_id)
        if not rule:
            raise DefaultPipelineError(f"规则 #{rule_id} 不存在")
        was_global = bool(rule.get("is_global"))
        PipelineDefaultRuleModel.delete(rule_id)
        fell_back = was_global and not any(
            r.get("is_global") for r in PipelineDefaultRuleModel.list()
        )
        return {"deleted": True, "fell_back_to_hardcoded": fell_back}

    # ──────────────────────────────────────────────────────────────
    # 校验
    # ──────────────────────────────────────────────────────────────

    def validate_default_pipeline(self, agent_names: list) -> list[str]:
        """默认 pipeline 最小节点约束强校验（阻断式错误列表）.

        强校验（返回错误即阻断创建）：
        - 非空；
        - ``AgentRegistry.validate_pipeline`` 通过（无非存在/禁用 agent、无环）；
        - 必须含 ``responder``（默认零自主处置门控）。

        ``reporter`` 缺失仅告警（引擎 ``ensure_reporter`` 保底），不计入返回。

        Returns:
            错误字符串列表；为空表示通过。
        """
        errors: list[str] = []
        if not agent_names:
            errors.append("默认 pipeline 不可为空")
            return errors

        reg_errors = AgentRegistry().validate_pipeline(agent_names)
        for m in reg_errors:
            # 仅阻断「缺失/禁用 agent」「环」类错误；其余（如缺依赖）作为告警不阻断
            if "not found" in m or "disabled" in m or "Circular" in m:
                errors.append(m)

        if "responder" not in agent_names:
            errors.append(
                "默认 pipeline 必须包含 responder 节点（默认零自主处置门控）"
            )
        if "reporter" not in agent_names:
            logger.warning(
                "默认 pipeline 未显式包含 reporter 节点；"
                "引擎将在末尾自动追加 reporter（ensure_reporter）"
            )
        return errors
