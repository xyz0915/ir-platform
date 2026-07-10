"""AI 分析输入质量评估服务."""

from __future__ import annotations

from typing import Any

from app.services.explainability_service import ExplainabilityService


class InputQualityService:
    """对 AI 分析输入上下文做本地规则评估与补充建议生成。"""

    @staticmethod
    def evaluate(tiered_data: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []
        suggestions: list[dict[str, Any]] = []
        score = 100

        host_basic = tiered_data.get("host_basic", {}) or {}
        analysis_result = tiered_data.get("analysis_result", {}) or {}
        timeline_events = (
            (tiered_data.get("timeline_high", []) or [])
            + (tiered_data.get("timeline_medium", []) or [])
            + (tiered_data.get("timeline_low", []) or [])
        )
        suspicious_connections = (
            (tiered_data.get("suspicious_connections_high", []) or [])
            + (tiered_data.get("suspicious_connections_medium", []) or [])
            + (tiered_data.get("suspicious_connections_low", []) or [])
        )
        abnormal_processes = (
            (tiered_data.get("abnormal_processes_high", []) or [])
            + (tiered_data.get("abnormal_processes_medium", []) or [])
            + (tiered_data.get("abnormal_processes_low", []) or [])
        )
        ioc_hits = (
            (tiered_data.get("ioc_hits_high", []) or [])
            + (tiered_data.get("ioc_hits_medium", []) or [])
            + (tiered_data.get("ioc_hits_low", []) or [])
        )
        persistence_items = tiered_data.get("persistence_suspicious", []) or []

        if not host_basic.get("hostname") and not host_basic.get("ip_address"):
            score -= 20
            issues.append("缺少主机标识信息，难以确认分析对象。")
            suggestions.append(InputQualityService._suggestion("host_identity", "补充主机标识", "建议补充主机名或 IP 地址，用于确认分析对象。", "high"))

        if not analysis_result.get("risk_level") and not analysis_result.get("summary"):
            score -= 15
            issues.append("缺少本地分析结果摘要，AI 需要从原始异常中自行归纳。")
            suggestions.append(InputQualityService._suggestion("local_summary", "补充本地分析摘要", "建议提供风险等级、风险摘要或本地分析结论。", "high"))

        if len(timeline_events) < 2:
            score -= 15
            issues.append("时间线事件过少，攻击链推断可能不完整。")
            suggestions.append(InputQualityService._suggestion("timeline", "补充时间线", "建议补充关键时间点、事件顺序或系统日志时间线。", "medium"))

        if not suspicious_connections:
            score -= 10
            issues.append("缺少可疑外连信息，难以判断 C2 或横向行为。")
            suggestions.append(InputQualityService._suggestion("network", "补充网络外连", "建议补充远端 IP/端口、协议和关联进程。", "medium"))

        if not abnormal_processes:
            score -= 10
            issues.append("缺少异常进程信息，执行链分析可能偏弱。")
            suggestions.append(InputQualityService._suggestion("process", "补充异常进程", "建议补充可疑进程名、命令行、父子进程关系。", "medium"))

        if not ioc_hits:
            score -= 10
            issues.append("没有 IOC 命中记录，外部威胁画像佐证较少。")
            suggestions.append(InputQualityService._suggestion("ioc", "补充 IOC 信息", "可补充域名、IP、哈希等 IOC 命中上下文。", "low"))

        if not persistence_items:
            score -= 10
            issues.append("缺少持久化痕迹信息，驻留判断可能不充分。")
            suggestions.append(InputQualityService._suggestion("persistence", "补充持久化痕迹", "建议补充启动项、计划任务、注册表自启等信息。", "low"))

        if score >= 80:
            level = "high"
        elif score >= 55:
            level = "medium"
        else:
            level = "low"

        input_quality = {
            "score": max(0, min(100, score)),
            "level": level,
            "issues": issues,
            "suggestions": suggestions,
        }
        coverage_gaps = ExplainabilityService.build_coverage_gaps(
            tiered_data=tiered_data,
            evidence_items=[],
            input_quality=input_quality,
        )
        miss_risk = {
            "level": "high" if level == "low" else "medium" if coverage_gaps.get("missing_data") or coverage_gaps.get("blind_spots") else "low",
            "summary": "；".join((coverage_gaps.get("missing_data") or []) + (coverage_gaps.get("weak_evidence") or []) + (coverage_gaps.get("blind_spots") or [])) or "当前输入质量较好，但仍建议结合人工复核。",
        }
        evidence_insufficiency = list(dict.fromkeys((coverage_gaps.get("weak_evidence") or []) + (coverage_gaps.get("recommended_collection") or [])))

        return {
            "input_quality": input_quality,
            "input_suggestions": suggestions,
            "coverage_gaps": coverage_gaps,
            "miss_risk": miss_risk,
            "evidence_insufficiency": evidence_insufficiency,
        }

    @staticmethod
    def _suggestion(suggestion_type: str, title: str, detail: str, priority: str) -> dict[str, Any]:
        return {
            "type": suggestion_type,
            "title": title,
            "detail": detail,
            "priority": priority,
        }
