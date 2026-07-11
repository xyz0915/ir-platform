"""AI 分析输出解析层统一守护（v1.3.0 作战化）.

``normalize_and_guard`` 是**唯一**的评分/缺口/基线/稀有/受众兜底纠正入口。
``ai_service.parse_json_response`` 与 ``ai_task_service._execute_task`` 两处调用点
均委托本模块，避免逻辑分叉、保证可审计、可复现。

守护涵盖：
- R1-2 评分透明：score_breakdown 必含；risk_score == sum(contribution)，不符以 breakdown 为准重算。
- R1-3 置信兜底：高中危结论必带 confidence；finding 缺失补默认并标记。
- R1-1 误报防护：threat_type=="正常" 且恶意行为为空时，risk_level 不得高于「中」并强制 reason。
- R2-1 缺口合并：coverage_gaps/miss_risk/evidence_insufficiency 合并为 data_gaps[]。
- R2-2 动作校验：每个 data_gaps 必挂 recommended_actions[]，字段齐备。
- R3-3 基线降噪：historical_known=true 的 score_breakdown 项按 BASELINE_PENALTY 回落。
- R4-1 ATT&CK 校验：mitre_attack[] 经覆盖库查表，未知标「待确认」。
- R5 稀有提级：命中 RARE_HIGH_SIGNALS 强制 P0 + 独立高亮卡 + escalation_conditions。
- R7-1 可证伪：escalation_conditions[] 结构化产出（R5/T5 已涉及）。
- R7-2 双受众：audience.{technical,executive} 归一，默认 both。
"""

import logging
from typing import Any, Optional

from app.shared.ai_constants import (
    AUDIENCE_DEFAULT,
    BASELINE_PENALTY,
    RARE_HIGH_SIGNALS,
    RISK_SCORE_THRESHOLD_HIGH,
    RISK_SCORE_THRESHOLD_MID,
    SCORE_WEIGHTS,
)

logger = logging.getLogger(__name__)


# 风险等级排序（用于上限封顶与回落）
_RISK_LEVEL_ORDER: dict[str, int] = {
    "安全": 0,
    "低危": 1,
    "低": 1,
    "中危": 2,
    "中": 2,
    "高危": 3,
    "高": 3,
    "严重": 4,
    "critical": 4,
}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_score_breakdown(risk: dict, corrections: list[dict]) -> None:
    """R1-2：确保 score_breakdown 存在且 risk_score == sum(contribution)。

    不符时以 breakdown 之和重算 risk_score，纠正痕迹写入 corrections。
    """
    breakdown = risk.get("score_breakdown")
    if not isinstance(breakdown, list) or len(breakdown) == 0:
        # 由 SCORE_WEIGHTS 给出空骨架，避免前端无数据可渲染
        risk["score_breakdown"] = []
        # 不强行赋值 risk_score，沿用既有或 AI 给出值
        return

    # 字段齐备 + 数值化
    cleaned: list[dict] = []
    for item in breakdown:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "signal": str(item.get("signal", "other")),
            "contribution": _coerce_int(item.get("contribution", 0)),
            "evidence": str(item.get("evidence", "")),
            "historical_known": bool(item.get("historical_known", False)),
            "evidence_source": str(item.get("evidence_source", "")),
        })
    risk["score_breakdown"] = cleaned

    computed = sum(item["contribution"] for item in cleaned)
    declared = _coerce_int(risk.get("risk_score"), None)
    if declared is None or declared != computed:
        action = "init" if declared is None else "recompute"
        risk["risk_score"] = computed
        corrections.append({
            "rule": "R1-2",
            "field": "risk_score",
            "action": action,
            "detail": f"risk_score 以 score_breakdown 之和为准重算为 {computed}",
        })


def _apply_baseline_penalty(risk: dict, baseline: Optional[dict], corrections: list[dict]) -> None:
    """R3-3：historical_known=true 的 score_breakdown 项按 BASELINE_PENALTY 回落。

    新增项不受影响；重算 risk_score 并记录。
    """
    if baseline is None:
        return
    breakdown = risk.get("score_breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        return

    known_signatures: set[str] = set()
    known_items = (baseline or {}).get("known_items") or {}
    if isinstance(known_items, dict):
        for items in known_items.values():
            if isinstance(items, list):
                for sig in items:
                    if isinstance(sig, str):
                        known_signatures.add(sig.strip().lower())

    adjusted = False
    for item in breakdown:
        is_known = bool(item.get("historical_known", False))
        if not is_known and known_signatures and isinstance(item.get("evidence"), str):
            ev = item["evidence"].strip().lower()
            if ev and any(ev in sig or sig in ev for sig in known_signatures):
                item["historical_known"] = True
                is_known = True
        if is_known and item.get("contribution", 0) > 0:
            original = item["contribution"]
            item["contribution"] = int(round(original * BASELINE_PENALTY))
            if item["contribution"] != original:
                adjusted = True
                corrections.append({
                    "rule": "R3-3",
                    "field": f"score_breakdown.{item.get('signal')}",
                    "action": "baseline_penalty",
                    "detail": f"基线已知项贡献 {original} → {item['contribution']} (×{BASELINE_PENALTY})",
                })

    if adjusted:
        new_score = sum(item["contribution"] for item in breakdown)
        corrections.append({
            "rule": "R3-3",
            "field": "risk_score",
            "action": "recompute",
            "detail": f"基线降噪后 risk_score 回落至 {new_score}",
        })
        risk["risk_score"] = new_score


def _apply_confidence_penalty(risk: dict, corrections: list[dict]) -> None:
    breakdown = risk.get("score_breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        risk["risk_score"] = 0
        return

    confidence_level = str(risk.get("confidence", "medium")).strip().lower()
    _cn = {"高": "high", "中": "medium", "低": "low"}
    confidence_level = _cn.get(confidence_level, confidence_level)
    if confidence_level not in ("high", "medium", "low"):
        confidence_level = "medium"  # 默认中等,不惩罚未知

    penalty = {"high": 1.0, "medium": 0.85, "low": 0.6}[confidence_level]

    # 安全求和(防 KeyError)
    raw_score = 0
    for item in breakdown:
        try:
            raw_score += int(item.get("contribution", 0))
        except (TypeError, ValueError):
            pass

    adjusted_score = round(raw_score * penalty)

    # 更新 adjusted_contribution
    for item in breakdown:
        try:
            item["adjusted_contribution"] = round(int(item.get("contribution", 0)) * penalty)
        except (TypeError, ValueError):
            item["adjusted_contribution"] = 0

    # 全局封顶 85——无论置信度多高,无人能在无实锤的情况下拿满分
    adjusted_score = min(adjusted_score, 85)

    # 无 confirmed 证据 → 进一步封顶 50
    evidence_confirmed = any(
        str(it.get("evidence_source", "")).strip().lower() == "confirmed" 
        for it in breakdown
    )
    if not evidence_confirmed:
        adjusted_score = min(adjusted_score, 50)

    if adjusted_score != raw_score or not evidence_confirmed:
        risk["risk_score"] = adjusted_score
        corrections.append({
            "rule": "R-CONFIDENCE",
            "field": "risk_score",
            "action": "confidence_penalty",
            "detail": (
                f"置信度 '{confidence_level}' ×{penalty}，"
                f"{raw_score} → {adjusted_score}"
                f"{'（无 confirmed 证据封顶 50）' if not evidence_confirmed else '（全局封顶 85）' if raw_score > 85 else ''}"
            ),
        })


def _ensure_confidence(risk: dict, threat: dict, corrections: list[dict]) -> None:
    """R1-3：高中危结论必带 confidence；finding 缺失补默认并标记。"""
    level = str(risk.get("risk_level", ""))
    is_high_or_mid = _RISK_LEVEL_ORDER.get(level, 0) >= 2

    conf = risk.get("confidence")
    if not conf:
        risk["confidence"] = "中" if is_high_or_mid else "低"
        corrections.append({
            "rule": "R1-3",
            "field": "risk_assessment.confidence",
            "action": "default",
            "detail": f"缺失置信度，按等级补默认 '{risk['confidence']}'",
        })

    # 威胁分析 findings 互补默认值（仅当为 dict 结构才补字段）
    malicious = threat.get("malicious_behaviors")
    if isinstance(malicious, list):
        for beh in malicious:
            if isinstance(beh, dict) and not beh.get("confidence"):
                beh["confidence"] = "中"
            if isinstance(beh, dict) and not beh.get("evidence"):
                beh["evidence"] = ""


def _ensure_evidence_chains(threat: dict, risk: dict, corrections: list[dict]) -> None:
    """为 threat_analysis 的每条 malicious_behavior / 关键发现增加 evidence_chain 字段.

    evidence_chain 结构: {"confirmed": [...], "missing": [...], "upgrade_path": "..."}

    优先级:
    1. AI 已输出 evidence_chain 的 → 原样保留
    2. AI 未输出 → 从 behavior 自身证据 + coverage_gaps/data_gaps 推导默认值
    3. 全局提示 "RAG/规则证据较少" 保留作为概述，不替代逐结论证据链

    Args:
        threat: threat_analysis 分段字典。
        risk: risk_assessment 分段字典。
        corrections: 一致性纠正痕迹列表。
    """
    malicious = threat.get("malicious_behaviors")
    if not isinstance(malicious, list) or not malicious:
        return

    # 收集全局缺失维度信息
    data_gaps = risk.get("data_gaps", [])
    coverage_gaps = risk.get("coverage_gaps", [])

    gap_titles: list[str] = []
    for gap_list in (data_gaps, coverage_gaps):
        for gap in _as_list(gap_list):
            if isinstance(gap, dict):
                title = gap.get("title") or gap.get("category", "")
                if title:
                    gap_titles.append(title)

    ensured_count = 0
    for beh in malicious:
        if not isinstance(beh, dict):
            continue

        # AI 已提供完整 evidence_chain → 跳过
        if "evidence_chain" in beh and isinstance(beh.get("evidence_chain"), dict):
            ec = beh["evidence_chain"]
            if ec.get("confirmed") and ec.get("missing") and ec.get("upgrade_path"):
                continue

        # 构建 confirmed
        confirmed: list[str] = []
        if beh.get("evidence"):
            confirmed.append(str(beh.get("evidence")))
        if beh.get("name"):
            confirmed.append(f"发现: {beh.get('name')}")
        # 从 behavior 的字符串字段提取信息
        for key in ("name", "description", "evidence"):
            val = beh.get(key)
            if isinstance(val, str) and val and val not in confirmed and not val.startswith("发现:"):
                confirmed.append(val)

        # 构建 missing
        missing: list[str] = []
        for title in gap_titles[:5]:
            if title not in missing:
                missing.append(title)
        if not missing:
            missing.append("需补充更多维度数据验证")

        # 构建 upgrade_path
        if gap_titles:
            upgrade_path = f"补采 {'、'.join(gap_titles[:3])} 后可提升置信度"
        else:
            upgrade_path = "补充缺失证据后可提升置信度"

        if not confirmed:
            confirmed.append("基于模型推断")

        beh["evidence_chain"] = {
            "confirmed": confirmed,
            "missing": missing,
            "upgrade_path": upgrade_path,
        }
        ensured_count += 1

    if ensured_count > 0:
        corrections.append({
            "rule": "R-EVIDENCE",
            "field": "threat_analysis.malicious_behaviors[*].evidence_chain",
            "action": "ensure",
            "detail": f"为 {ensured_count} 条恶意行为补全 evidence_chain 字段",
        })


def _cap_normal_threat(risk: dict, threat: dict, corrections: list[dict]) -> None:
    """R1-1：threat_type=='正常' 且恶意行为为空时，risk_level 不得高于「中」并强制 reason。"""
    threat_type = str(risk.get("threat_type", "")).strip()
    if threat_type != "正常":
        return
    malicious = threat.get("malicious_behaviors") or []
    if isinstance(malicious, list) and len(malicious) == 0:
        level = str(risk.get("risk_level", ""))
        if _RISK_LEVEL_ORDER.get(level, 0) > 2:
            risk["risk_level"] = "中"
            corrections.append({
                "rule": "R1-1",
                "field": "risk_assessment.risk_level",
                "action": "cap",
                "detail": f"threat_type=正常且无恶意行为，risk_level 封顶为「中」(原 {level})",
            })
        if not risk.get("reason"):
            risk["reason"] = "判定为正常：未发现明确恶意行为，已按 R1-1 强制收敛风险等级。"
            corrections.append({
                "rule": "R1-1",
                "field": "risk_assessment.reason",
                "action": "force",
                "detail": "缺失 reason，按 R1-1 强制补充收敛说明",
            })


def _merge_data_gaps(risk: dict) -> list[dict]:
    """R2-1：将 coverage_gaps / miss_risk / evidence_insufficiency 合并为 data_gaps[]。

    兼容 AI 直出的 risk_assessment.data_gaps；旧字段保留不破坏向后读取。
    """
    gaps: list[dict] = []

    def _norm_gap(g: Any, source: str) -> Optional[dict]:
        if not isinstance(g, dict):
            return None
        return {
            "category": str(g.get("category", source)),
            "title": str(g.get("title", g.get("field", "数据缺口"))),
            "severity": str(g.get("severity", "medium")),
            "description": str(g.get("description", g.get("summary", g.get("reason", "")))),
            "suggestion": str(g.get("suggestion", "")),
            "recommended_actions": _as_list(g.get("recommended_actions")),
            "source": source,
        }

    # AI 直出
    for g in _as_list(risk.get("data_gaps")):
        ng = _norm_gap(g, "data_gaps")
        if ng:
            gaps.append(ng)

    # coverage_gaps
    for g in _as_list(risk.get("coverage_gaps")):
        ng = _norm_gap(g, "coverage_gaps")
        if ng:
            gaps.append(ng)

    # evidence_insufficiency → 每条一个 gap
    for g in _as_list(risk.get("evidence_insufficiency")):
        if isinstance(g, dict):
            ng = _norm_gap({
                "category": g.get("field", "evidence_insufficiency"),
                "title": g.get("label", g.get("field", "证据不足")),
                "severity": "medium",
                "description": g.get("reason", ""),
                "suggestion": "补充对应维度证据后重新分析",
            }, "evidence_insufficiency")
            if ng:
                gaps.append(ng)

    # miss_risk → 单个 gap
    mr = risk.get("miss_risk")
    if isinstance(mr, dict):
        ng = _norm_gap({
            "category": "miss_risk",
            "title": "漏检风险",
            "severity": str(mr.get("level", "medium")),
            "description": mr.get("summary", "存在潜在漏检风险"),
            "suggestion": "结合盲点维度补充采集与研判",
        }, "miss_risk")
        if ng:
            gaps.append(ng)

    # 去重（按 category+title）
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for g in gaps:
        key = (g["category"], g["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)
    return deduped


_VALID_ACTION_TYPES = {
    "wmi_dump", "autostart_extract", "net_capture", "log_export",
    "registry_dump", "process_dump", "manual_review",
}


def _normalize_recommended_actions(gap: dict) -> list[dict]:
    """R2-2：每个 data_gap 必挂 recommended_actions[]，字段齐备。

    缺失字段补默认值；若 gap 完全没有动作，补一条 manual_review 占位动作。
    """
    actions = _as_list(gap.get("recommended_actions"))
    normalized: list[dict] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        action_type = a.get("action_type") or "manual_review"
        if action_type not in _VALID_ACTION_TYPES:
            action_type = "manual_review"
        normalized.append({
            "action_type": action_type,
            "target": str(a.get("target", gap.get("category", ""))),
            "command_or_api": str(a.get("command_or_api", "")),
            "priority": str(a.get("priority", "P1")),
            "rationale": str(a.get("rationale", gap.get("suggestion", ""))),
            "auto_runnable": bool(a.get("auto_runnable", False)),
        })

    if not normalized:
        normalized.append({
            "action_type": "manual_review",
            "target": str(gap.get("category", "")),
            "command_or_api": "",
            "priority": "P1",
            "rationale": gap.get("suggestion", "需人工补充采集"),
            "auto_runnable": False,
        })
    return normalized


def _resolve_mitre_attack(parsed: dict, risk: dict) -> list[dict]:
    """R4-1：聚合并校验 mitre_attack[]（未知标「待确认」）。"""
    raw = parsed.get("mitre_attack") or risk.get("mitre_attack") or []
    ids = _as_list(raw)
    # 扁平化（可能嵌套字符串/数字）
    flat_ids: list[str] = []
    for x in ids:
        if isinstance(x, str):
            flat_ids.append(x)
        elif isinstance(x, dict):
            flat_ids.append(str(x.get("id", x.get("technique_id", ""))))
    try:
        from app.services.attack_technique_service import AttackTechniqueService

        return AttackTechniqueService.resolve(flat_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ATT&CK 查表失败，降级为原始 ID: %s", exc)
        return [{"id": i, "name": "待确认", "tactic": "", "tactic_id": "", "known": False} for i in flat_ids]


def _detect_rare_high_signals(threat: dict, risk: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """R5：扫描命中 RARE_HIGH_SIGNALS → 强制 P0 + 独立高亮卡 + escalation_conditions。

    Returns:
        (rare_high_signals, p0_actions, escalation_conditions)
    """
    # 构成待扫描文本
    texts: list[str] = []
    malicious = threat.get("malicious_behaviors")
    if isinstance(malicious, list):
        for beh in malicious:
            if isinstance(beh, str):
                texts.append(beh.lower())
            elif isinstance(beh, dict):
                texts.append(str(beh.get("name", beh.get("evidence", ""))).lower())
    texts.append(str(threat.get("attack_vector", "")).lower())
    texts.append(str(risk.get("reason", "")).lower())
    combined = "\n".join(texts)

    hit_signals: list[str] = []
    for sig in RARE_HIGH_SIGNALS:
        if sig.lower() in combined:
            hit_signals.append(sig)

    rare_high_signals: list[dict] = []
    p0_actions: list[dict] = []
    escalations: list[dict] = []
    for sig in hit_signals:
        rare_high_signals.append({
            "signal": sig,
            "priority": "P0",
            "evidence": f"检出稀有高危信号：{sig}",
        })
        p0_actions.append({
            "action_type": "manual_review",
            "target": sig,
            "command_or_api": "",
            "priority": "P0",
            "rationale": f"稀有高危信号 {sig} 命中，需立即人工研判并处置",
            "auto_runnable": False,
        })
        escalations.append({
            "condition": f"检出稀有高危信号 {sig}",
            "if_true": "立即升至 P0 并通知应急负责人",
            "target_level": "高",
        })

    return rare_high_signals, p0_actions, escalations


def _normalize_audience(parsed: dict) -> Any:
    """R7-2：audience 归一。dict 原样保留；字符串规范为 technical/executive/both；缺失默认 both。"""
    aud = parsed.get("audience")
    if isinstance(aud, dict):
        return {
            "technical": aud.get("technical", {}) or {},
            "executive": aud.get("executive", {}) or {},
        }
    if isinstance(aud, str) and aud.strip().lower() in ("technical", "executive", "both"):
        return aud.strip().lower()
    return AUDIENCE_DEFAULT


def normalize_and_guard(
    parsed: dict,
    *,
    baseline: Optional[dict] = None,
    attack_chain_hits: Optional[list] = None,
    audience: Optional[str] = None,
) -> dict:
    """解析层统一守护入口。

    对 AI 原始解析结果做一致性纠正、评分回落、置信兜底、缺口合并、
    基线降噪、ATT&CK 校验、稀有提级、受众归一，返回作战化增强后的结构化结果。

    Args:
        parsed: 原始解析字典（含 risk_assessment / threat_analysis / ...）。
        baseline: 主机差分基线 JSON（R3-3 降噪用），可为 None。
        attack_chain_hits: 引擎攻击链命中（v1.2.0 已落库），仅叙述不重判；可为 None。
        audience: 提交时透传的受众偏好（technical/executive/both），覆盖 parsed。

    Returns:
        守护后的字典，包含：
        risk_assessment / threat_analysis / data_gaps / mitre_attack /
        rare_high_signals / escalation_conditions / audience / attack_chain_hits /
        consistency_corrections / recommended_actions
    """
    parsed = parsed if isinstance(parsed, dict) else {}
    risk = dict(parsed.get("risk_assessment", {}) or {})
    threat = dict(parsed.get("threat_analysis", {}) or {})
    recommendations = dict(parsed.get("recommendations", {}) or {})
    corrections: list[dict] = []

    # ── 评分与结论纠正 ──
    _normalize_score_breakdown(risk, corrections)
    _ensure_confidence(risk, threat, corrections)
    _cap_normal_threat(risk, threat, corrections)
    _apply_baseline_penalty(risk, baseline, corrections)
    _apply_confidence_penalty(risk, corrections)
    _ensure_evidence_chains(threat, risk, corrections)

    # ── 缺口即动作 ──
    data_gaps = _merge_data_gaps(risk)
    # v1.3.2: 平台 InputQualityService 不产出 data_gaps 键，
    # 如果 risk 中仍存在 data_gaps，说明 AI 产出了缺口（旧 prompt 缓存或模型惯性），
    # 追加一致性纠正说明。
    ai_data_gaps = _as_list(risk.get("data_gaps"))
    if ai_data_gaps:
        corrections.append({
            "rule": "R2-1-CONSISTENCY",
            "field": "risk_assessment.data_gaps",
            "action": "note",
            "detail": "data_gaps 应由平台侧 input_quality_service 生成，AI 产生的缺口仅供参考",
        })
    # 合并平台侧 InputQualityService.evaluate() 产出的缺口
    # （coverage_gaps / miss_risk / evidence_insufficiency 已由 _merge_data_gaps 合并）
    merged_actions: list[dict] = []
    for gap in data_gaps:
        gap["recommended_actions"] = _normalize_recommended_actions(gap)
        merged_actions.extend(gap["recommended_actions"])
    # v1.3.0 BugFix: 完整合并 coverage_gaps / miss_risk / evidence_insufficiency
    # 为 data_gaps[] 后，删除残留旧字段，避免前端列表中出现独立条目。
    risk.pop("coverage_gaps", None)
    risk.pop("miss_risk", None)
    risk.pop("evidence_insufficiency", None)
    # data_gaps 同时落到 risk_assessment 与 recommendations，便于前端取用
    risk["data_gaps"] = data_gaps
    recommendations["data_gaps"] = data_gaps
    recommendations["recommended_actions"] = merged_actions

    # ── ATT&CK 校验 ──
    mitre_attack = _resolve_mitre_attack(parsed, risk)
    risk["mitre_attack"] = [m["id"] for m in mitre_attack if m.get("id")]

    # ── 稀有高危提级 ──
    rare_high_signals, p0_actions, rare_escalations = _detect_rare_high_signals(threat, risk)
    if rare_high_signals:
        merged_actions.extend(p0_actions)
        recommendations["recommended_actions"] = merged_actions
        risk["rare_high_signals"] = [r["signal"] for r in rare_high_signals]

    # ── 可证伪 escalation_conditions ──
    escalation_conditions: list[dict] = _as_list(risk.get("escalation_conditions"))
    if not isinstance(escalation_conditions, list):
        escalation_conditions = []
    escalation_conditions = [
        c for c in escalation_conditions if isinstance(c, dict)
    ]
    escalation_conditions.extend(rare_escalations)
    # 高分触发升级条件（可证伪，禁止自我引用循环）
    try:
        score = int(risk.get("risk_score", 0))
    except (TypeError, ValueError):
        score = 0
    if score >= RISK_SCORE_THRESHOLD_HIGH:
        # 不再生成「评分达到高危阈值 → 升高危」这种循环升级条件。
        # 改为基于实际证据缺口生成可证伪的升级条件。
        breakdown = risk.get("score_breakdown", [])
        if not isinstance(breakdown, list):
            breakdown = []
        mitre_attack_ids = risk.get("mitre_attack", [])
        has_confirmed = any(
            it.get("evidence_source") == "confirmed" for it in breakdown
        )
        has_c2_signal = any(
            str(it.get("signal", "")).lower() in ("c2_external", "data_exfiltration")
            for it in breakdown
        )

        # 避免重复生成同类条件
        existing_conditions = {c.get("condition", "") for c in escalation_conditions}

        if mitre_attack_ids and not has_confirmed:
            cond = "发现行为证据（如进程注入/内存加载）"
            if cond not in existing_conditions:
                escalation_conditions.append({
                    "condition": cond,
                    "if_true": "升高危",
                    "target_level": "高",
                })
        elif has_c2_signal and not has_confirmed:
            cond = "外连流量出现 beacon 模式"
            if cond not in existing_conditions:
                escalation_conditions.append({
                    "condition": cond,
                    "if_true": "升高危",
                    "target_level": "高",
                })
        elif has_confirmed:
            cond = "新增 confirmed 证据"
            if cond not in existing_conditions:
                escalation_conditions.append({
                    "condition": cond,
                    "if_true": "保持或升级风险等级",
                    "target_level": "高",
                })
        else:
            cond = "若补充到 confirmed 级别证据"
            if cond not in existing_conditions:
                escalation_conditions.append({
                    "condition": cond,
                    "if_true": "升一级",
                    "target_level": "高",
                })
    risk["escalation_conditions"] = escalation_conditions

    # ── 风险等级自洽约束：低置信度 + 评分 < 60 → 等级不高于「高」──
    confidence_for_level = str(risk.get("confidence", "")).strip().lower()
    _cn_low = {"低", "low"}
    if confidence_for_level in _cn_low and score < RISK_SCORE_THRESHOLD_HIGH:
        current_level = str(risk.get("risk_level", ""))
        current_order = _RISK_LEVEL_ORDER.get(current_level, 0)
        cap_order = _RISK_LEVEL_ORDER.get("高", 3)
        if current_order > cap_order:
            risk["risk_level"] = "高"
            corrections.append({
                "rule": "R-CONSISTENCY",
                "field": "risk_assessment.risk_level",
                "action": "cap",
                "detail": (
                    f"置信度为低且评分 {score} < {RISK_SCORE_THRESHOLD_HIGH}，"
                    f"风险等级从 '{current_level}' 封顶为 '高'"
                ),
            })

    # ── 一致性纠正痕迹 ──
    risk["consistency_corrections"] = corrections

    # ── 受众 ──
    aud = _normalize_audience(parsed)
    if audience in ("technical", "executive", "both"):
        aud = audience

    # ── 攻击链（仅叙述，不重判）──
    ach = attack_chain_hits if isinstance(attack_chain_hits, list) else []

    return {
        "risk_assessment": risk,
        "threat_analysis": threat,
        "recommendations": recommendations,
        "data_gaps": data_gaps,
        "mitre_attack": mitre_attack,
        "rare_high_signals": rare_high_signals,
        "escalation_conditions": escalation_conditions,
        "audience": aud,
        "attack_chain_hits": ach,
        "consistency_corrections": corrections,
        "recommended_actions": merged_actions,
    }
