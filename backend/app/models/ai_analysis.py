"""AI分析报告模型 — ai_analysis_reports 表 CRUD 操作（版本管理支持）."""

import hashlib
import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiAnalysisReport:
    """AI分析报告模型 — 支持版本管理.

    报告创建不再删除旧记录，而是采用版本号递增 + is_latest 标记：
    - 同 host 的旧报告 is_latest 置为 0
    - 新报告 version = 上一个最大 version + 1，is_latest = 1
    """

    @staticmethod
    def create(
        host_id: int,
        case_id: int,
        risk_assessment: str = "",
        threat_analysis: str = "",
        timeline_analysis: str = "",
        recommendations: str = "",
        raw_response: str = "",
        model_used: str = "",
        tokens_used: int = 0,
        profile_id: Optional[int] = None,
        masked_mode: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        conversation_id: Optional[str] = None,
        data_hash: Optional[str] = None,
        cached_at: Optional[str] = None,
        input_quality: Optional[dict[str, Any]] = None,
        coverage_gaps: Optional[dict[str, Any]] = None,
        explainability: Optional[dict[str, Any]] = None,
        deep_dive: Optional[dict[str, Any]] = None,
    ) -> dict:
        """创建AI分析报告（新版本）.

        同主机的旧报告标记 is_latest=0，新报告 version 递增.

        Args:
            host_id: 主机ID.
            case_id: 案件ID.
            risk_assessment: 风险评估内容.
            threat_analysis: 威胁分析内容.
            timeline_analysis: 时间线解读内容.
            recommendations: 处置建议内容.
            raw_response: AI原始返回内容.
            model_used: 使用的模型名称.
            tokens_used: 总token消耗.
            profile_id: 使用的AI配置Profile ID.
            masked_mode: 是否脱敏模式.
            prompt_tokens: 输入token数.
            completion_tokens: 输出token数.

        Returns:
            创建的报告字典.
        """
        with get_connection() as conn:
            # 获取当前 host 的最大 version
            max_ver_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) as max_ver FROM ai_analysis_reports WHERE host_id = ?",
                (host_id,),
            ).fetchone()
            new_version = max_ver_row["max_ver"] + 1

            # 将同 host 的所有旧报告标记为非最新
            conn.execute(
                "UPDATE ai_analysis_reports SET is_latest = 0 WHERE host_id = ?",
                (host_id,),
            )

            # 插入新报告
            cursor = conn.execute(
                """
                INSERT INTO ai_analysis_reports
                (host_id, case_id, risk_assessment, threat_analysis,
                 timeline_analysis, recommendations, raw_response,
                 model_used, tokens_used, version, profile_id,
                 is_latest, masked_mode, prompt_tokens, completion_tokens,
                 conversation_id, data_hash, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id, case_id, risk_assessment, threat_analysis,
                    timeline_analysis, recommendations, raw_response,
                    model_used, tokens_used, new_version, profile_id,
                    masked_mode, prompt_tokens, completion_tokens,
                    conversation_id, data_hash, cached_at,
                ),
            )
            report_id = cursor.lastrowid

        return AiAnalysisReport.get_by_id(report_id)

    @staticmethod
    def get_by_id(report_id: int) -> Optional[dict]:
        """根据ID获取AI分析报告."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_analysis_reports WHERE id = ?", (report_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_host(host_id: int) -> Optional[dict]:
        """获取主机最新的AI分析报告（is_latest=1）."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM ai_analysis_reports
                   WHERE host_id = ? AND is_latest = 1
                   ORDER BY created_at DESC LIMIT 1""",
                (host_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_versions(host_id: int) -> list[dict]:
        """列出主机的所有AI分析报告版本."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, host_id, version, model_used, tokens_used,
                   is_latest, masked_mode, created_at
                   FROM ai_analysis_reports
                   WHERE host_id = ?
                   ORDER BY version DESC""",
                (host_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_by_version(host_id: int, version: int) -> Optional[dict]:
        """获取主机的特定版本AI分析报告."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM ai_analysis_reports
                   WHERE host_id = ? AND version = ?""",
                (host_id, version),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机所有AI分析报告."""
        with get_connection() as conn:
            conn.execute("DELETE FROM ai_analysis_reports WHERE host_id = ?", (host_id,))

    @staticmethod
    def export_for_pdf(report_id: int) -> Optional[dict]:
        """获取报告完整数据用于PDF导出."""
        report = AiAnalysisReport.get_by_id(report_id)
        if not report:
            return None

        # 获取关联的主机信息
        from app.models.host import Host
        host = Host.get_by_id(report.get("host_id", 0))

        result = dict(report)
        if host:
            result["hostname"] = host.get("hostname", "")
            result["ip_address"] = host.get("ip_address", "")
            result["os_type"] = host.get("os_type", "")

        return result

    @staticmethod
    def get_cached_report(host_id: int, data_hash: str) -> Optional[dict]:
        """检查缓存：hash 匹配 + 24h 内的报告直接返回.

        Args:
            host_id: 主机ID.
            data_hash: 数据指纹.

        Returns:
            缓存报告或 None.
        """
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM ai_analysis_reports
                   WHERE host_id = ? AND data_hash = ? AND is_latest = 1
                     AND cached_at > datetime('now', '-1 day')
                   ORDER BY created_at DESC LIMIT 1""",
                (host_id, data_hash),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_completed_by_case(case_id: int, exclude_host_id: Optional[int] = None, limit: int = 3) -> list[dict]:
        """获取同案件下已完成的AI分析报告.

        Args:
            case_id: 案件ID.
            exclude_host_id: 排除的主机ID.
            limit: 返回数量上限.

        Returns:
            报告列表.
        """
        with get_connection() as conn:
            if exclude_host_id is not None:
                rows = conn.execute(
                    """SELECT a.*, h.hostname, h.ip_address
                       FROM ai_analysis_reports a
                       JOIN hosts h ON a.host_id = h.id
                       WHERE a.case_id = ? AND a.host_id != ? AND a.is_latest = 1
                       ORDER BY a.created_at DESC LIMIT ?""",
                    (case_id, exclude_host_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT a.*, h.hostname, h.ip_address
                       FROM ai_analysis_reports a
                       JOIN hosts h ON a.host_id = h.id
                       WHERE a.case_id = ? AND a.is_latest = 1
                       ORDER BY a.created_at DESC LIMIT ?""",
                    (case_id, limit),
                ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_by_risk_level(risk_level: str, exclude_host_id: Optional[int] = None, limit: int = 3) -> list[dict]:
        """按风险等级获取已完成报告.

        Args:
            risk_level: 风险等级（高危/中危/低危/安全）.
            exclude_host_id: 排除的主机ID.
            limit: 返回数量上限.

        Returns:
            报告列表.
        """
        with get_connection() as conn:
            if exclude_host_id is not None:
                rows = conn.execute(
                    """SELECT a.*, h.hostname, h.ip_address
                       FROM ai_analysis_reports a
                       JOIN hosts h ON a.host_id = h.id
                       WHERE a.risk_assessment LIKE ? AND a.host_id != ? AND a.is_latest = 1
                       ORDER BY a.created_at DESC LIMIT ?""",
                    (f"%{risk_level}%", exclude_host_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT a.*, h.hostname, h.ip_address
                       FROM ai_analysis_reports a
                       JOIN hosts h ON a.host_id = h.id
                       WHERE a.risk_assessment LIKE ? AND a.is_latest = 1
                       ORDER BY a.created_at DESC LIMIT ?""",
                    (f"%{risk_level}%", limit),
                ).fetchall()
            return [dict(row) for row in rows]
