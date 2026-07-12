"""风险等级评估器 — 根据分析结果评估整体风险."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RiskAssessor:
    """风险等级评估器.

    根据所有发现（findings）评估整体风险，计算 0-100 分数.
    """

    # 严重程度权重（与 anomaly_detector.SEVERITY_SCORES 统一，决策4/§4.1）
    SEVERITY_WEIGHTS = {
        "critical": 35,
        "high": 20,
        "medium": 10,
        "low": 5,
        "info": 1,
    }

    # 风险等级映射
    RISK_LEVELS = [
        (80, "critical"),
        (60, "high"),
        (40, "medium"),
        (20, "low"),
        (0, "info"),
    ]

    @staticmethod
    def assess(findings: dict) -> dict:
        """根据所有分析结果评估整体风险.

        Args:
            findings: 包含各类发现数量的字典.
                {
                    "abnormal_processes": [...],
                    "suspicious_connections": [...],
                    "suspicious_startup_items": [...],
                    "persistence_items": [...],
                    "ioc_hits": [...],
                    "timeline_events": [...],
                }

        Returns:
            {
                "risk_level": "critical/high/medium/low/info",
                "risk_score": 0-100,
                "total_findings": N,
                "summary": "...",
                "details": {...}
            }
        """
        total_findings = 0
        score = 0
        details: dict[str, Any] = {}

        # 异常进程
        abnormal_processes = findings.get("abnormal_processes", [])
        proc_count = len(abnormal_processes)
        total_findings += proc_count
        proc_score = RiskAssessor._calculate_category_score(abnormal_processes)
        score += proc_score
        details["abnormal_processes"] = {"count": proc_count, "score": proc_score}

        # 可疑外连
        suspicious_connections = findings.get("suspicious_connections", [])
        conn_count = len(suspicious_connections)
        total_findings += conn_count
        conn_score = RiskAssessor._calculate_category_score(suspicious_connections)
        score += conn_score
        details["suspicious_connections"] = {"count": conn_count, "score": conn_score}

        # 可疑启动项
        suspicious_startup = findings.get("suspicious_startup_items", [])
        startup_count = len(suspicious_startup)
        total_findings += startup_count
        startup_score = RiskAssessor._calculate_category_score(suspicious_startup)
        score += startup_score
        details["suspicious_startup_items"] = {"count": startup_count, "score": startup_score}

        # 可疑持久化
        persistence_items = findings.get("persistence_items", [])
        suspicious_persistence = [p for p in persistence_items if p.get("is_suspicious")]
        persistence_count = len(suspicious_persistence)
        total_findings += persistence_count
        persistence_score = RiskAssessor._calculate_category_score(suspicious_persistence)
        score += persistence_score
        details["suspicious_persistence"] = {"count": persistence_count, "score": persistence_score}

        # IOC 命中
        ioc_hits = findings.get("ioc_hits", [])
        ioc_count = len(ioc_hits)
        total_findings += ioc_count
        ioc_score = RiskAssessor._calculate_category_score(ioc_hits)
        score += ioc_score
        details["ioc_hits"] = {"count": ioc_count, "score": ioc_score}

        # 限制分数在 0-100
        score = min(score, 100)

        # 确定风险等级
        risk_level = RiskAssessor._score_to_level(score)

        # 生成摘要
        summary = RiskAssessor._generate_summary(risk_level, score, total_findings, details)

        return {
            "risk_level": risk_level,
            "risk_score": score,
            "total_findings": total_findings,
            "summary": summary,
            "details": details,
        }

    @staticmethod
    def calculate_score(findings: dict) -> int:
        """计算风险分数.

        Args:
            findings: 发现字典.

        Returns:
            0-100 的风险分数.
        """
        return RiskAssessor.assess(findings)["risk_score"]

    @staticmethod
    def _calculate_category_score(items: list) -> int:
        """计算单类发现的分数.

        Args:
            items: 发现列表.

        Returns:
            该类别的分数.
        """
        score = 0
        for item in items:
            severity = item.get("severity", "info")
            score += RiskAssessor.SEVERITY_WEIGHTS.get(severity, 0)
        return min(score, 100)

    @staticmethod
    def _score_to_level(score: int) -> str:
        """将分数转换为风险等级.

        Args:
            score: 0-100 的分数.

        Returns:
            风险等级字符串.
        """
        for threshold, level in RiskAssessor.RISK_LEVELS:
            if score >= threshold:
                return level
        return "info"

    @staticmethod
    def _generate_summary(risk_level: str, score: int, total: int, details: dict) -> str:
        """生成风险评估摘要.

        Args:
            risk_level: 风险等级.
            score: 风险分数.
            total: 总发现数.
            details: 分类详情.

        Returns:
            摘要文字.
        """
        level_names = {
            "critical": "严重",
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "信息",
        }

        parts = [f"风险评估等级: {level_names.get(risk_level, risk_level)}（分数: {score}/100）"]
        parts.append(f"共发现 {total} 项安全问题。")

        detail_parts = []
        for category, info in details.items():
            if info["count"] > 0:
                category_names = {
                    "abnormal_processes": "异常进程",
                    "suspicious_connections": "可疑外连",
                    "suspicious_startup_items": "可疑启动项",
                    "suspicious_persistence": "可疑持久化",
                    "ioc_hits": "IOC 命中",
                }
                name = category_names.get(category, category)
                detail_parts.append(f"{name} {info['count']} 项")

        if detail_parts:
            parts.append("详情: " + "，".join(detail_parts) + "。")

        if risk_level in ("critical", "high"):
            parts.append("建议立即处置，隔离主机并进行深入调查。")
        elif risk_level == "medium":
            parts.append("建议尽快排查相关问题并采取处置措施。")
        elif risk_level == "low":
            parts.append("建议关注相关项，持续监控。")

        return " ".join(parts)
