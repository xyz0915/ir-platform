"""AI分析报告模型 — ai_analysis_reports 表 CRUD 操作."""

import json
import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiAnalysisReport:
    """AI分析报告模型."""

    @staticmethod
    def create(host_id: int, case_id: int, risk_assessment: str,
               threat_analysis: str, timeline_analysis: str,
               recommendations: str, raw_response: str,
               model_used: str, tokens_used: int) -> dict:
        """创建AI分析报告."""
        with get_connection() as conn:
            # 先删除该主机的旧AI报告
            conn.execute("DELETE FROM ai_analysis_reports WHERE host_id = ?", (host_id,))
            cursor = conn.execute(
                """
                INSERT INTO ai_analysis_reports
                (host_id, case_id, risk_assessment, threat_analysis,
                 timeline_analysis, recommendations, raw_response,
                 model_used, tokens_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (host_id, case_id, risk_assessment, threat_analysis,
                 timeline_analysis, recommendations, raw_response,
                 model_used, tokens_used),
            )
            report_id = cursor.lastrowid
        return AiAnalysisReport.get_by_host(host_id)

    @staticmethod
    def get_by_host(host_id: int) -> Optional[dict]:
        """获取主机的AI分析报告."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_analysis_reports WHERE host_id = ? ORDER BY created_at DESC LIMIT 1",
                (host_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的AI分析报告."""
        with get_connection() as conn:
            conn.execute("DELETE FROM ai_analysis_reports WHERE host_id = ?", (host_id,))
