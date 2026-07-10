"""历史案例匹配器 — 为 PromptBuilder 提供同案件/相似案件上下文.

从 ai_analysis_reports 中检索：同案件最近完成的报告摘要 + 跨案件同风险级别的报告.
"""

import logging
from typing import Optional

from app.models.ai_analysis import AiAnalysisReport
from app.models.host import Host
from app.models.analysis import AnalysisResult

logger = logging.getLogger(__name__)


class CaseMatcher:
    """历史案例匹配器.

    提供两类检索：
    - 同案件上下文：同一 case_id 下其他主机的 AI 分析摘要
    - 相似案例：跨案件同风险等级的报告
    """

    @staticmethod
    def get_same_case_context(host_id: int, case_id: int, limit: int = 2) -> str:
        """获取同案件下最近完成的 AI 分析报告摘要.

        Args:
            host_id: 当前主机ID（用于排除自身）.
            case_id: 案件ID.
            limit: 最多返回条数.

        Returns:
            格式化的上下文文本，没有则返回空字符串.
        """
        try:
            reports = AiAnalysisReport.get_completed_by_case(
                case_id=case_id,
                exclude_host_id=host_id,
                limit=limit,
            )
        except Exception as e:
            logger.warning("get_same_case_context failed: %s", e)
            return ""

        if not reports:
            return ""

        parts: list[str] = []
        for i, report in enumerate(reports, 1):
            hostname = report.get("hostname", f"主机{report.get('host_id', '?')}")
            ip_addr = report.get("ip_address", "")
            ra = (report.get("risk_assessment") or "")[:200]
            ta = (report.get("threat_analysis") or "")[:200]
            model = report.get("model_used", "")
            created = report.get("created_at", "")

            parts.append(
                f"案例{i}: {hostname} ({ip_addr})\n"
                f"  模型: {model} | 时间: {created}\n"
                f"  风险评估: {ra}\n"
                f"  威胁分析: {ta}"
            )

        return "\n\n".join(parts)

    @staticmethod
    def get_similar_cases(host_id: int, risk_level: str, limit: int = 3) -> str:
        """获取跨案件同风险级别的历史报告摘要.

        Args:
            host_id: 当前主机ID（用于排除自身）.
            risk_level: 风险等级（高危/中危/低危）.
            limit: 最多返回条数.

        Returns:
            格式化的上下文文本，没有则返回空字符串.
        """
        if not risk_level:
            return ""

        try:
            reports = AiAnalysisReport.get_by_risk_level(
                risk_level=risk_level,
                exclude_host_id=host_id,
                limit=limit,
            )
        except Exception as e:
            logger.warning("get_similar_cases failed: %s", e)
            return ""

        if not reports:
            return ""

        parts: list[str] = []
        for i, report in enumerate(reports, 1):
            hostname = report.get("hostname", f"主机{report.get('host_id', '?')}")
            ip_addr = report.get("ip_address", "")
            ra = (report.get("risk_assessment") or "")[:200]
            recs = (report.get("recommendations") or "")[:200]
            model = report.get("model_used", "")
            created = report.get("created_at", "")

            parts.append(
                f"相似案例{i}: {hostname} ({ip_addr})\n"
                f"  模型: {model} | 时间: {created}\n"
                f"  风险评估: {ra}\n"
                f"  处置建议: {recs}"
            )

        return "\n\n".join(parts)
