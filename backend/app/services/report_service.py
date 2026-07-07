"""报告服务 — 生成 HTML 和 PDF 报告."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models.analysis import (
    AnalysisResult, HostProfile, AbnormalProcess, SuspiciousConnection,
    SuspiciousStartupItem, PersistenceItem, TimelineEvent, IocHit,
)
from app.models.host import Host
from app.models.case import Case
from app.models.ai_analysis import AiAnalysisReport
from app.utils.pdf_converter import html_to_pdf

logger = logging.getLogger(__name__)


class ReportService:
    """报告生成服务."""

    @staticmethod
    def generate_html(host_id: int) -> str:
        """生成 HTML 报告.

        Args:
            host_id: 主机 ID.

        Returns:
            HTML 报告字符串.

        Raises:
            ValueError: 主机不存在或未分析.
        """
        # 获取数据
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")

        case = Case.get_by_id(host["case_id"]) if host.get("case_id") else None
        analysis = AnalysisResult.get_by_host(host_id)
        profile = HostProfile.get_by_host(host_id)
        abnormal_processes = AbnormalProcess.list_by_host(host_id)
        suspicious_connections = SuspiciousConnection.list_by_host(host_id)
        suspicious_startup = SuspiciousStartupItem.list_by_host(host_id)
        persistence_items = PersistenceItem.list_by_host(host_id)
        timeline_events = TimelineEvent.list_by_host(host_id)
        ioc_hits = IocHit.list_by_host(host_id)

        # AI 分析报告
        ai_report = AiAnalysisReport.get_by_host(host_id)

        # 解析 JSON 字段
        report_data: dict[str, Any] = {
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case": case,
            "host": host,
            "analysis": analysis,
            "profile": ReportService._parse_profile(profile),
            "abnormal_processes": abnormal_processes,
            "suspicious_connections": suspicious_connections,
            "suspicious_startup": suspicious_startup,
            "persistence_items": persistence_items,
            "timeline_events": timeline_events[:100],  # 限制时间线数量
            "ioc_hits": ioc_hits,
            "stats": {
                "abnormal_process_count": len(abnormal_processes),
                "suspicious_connection_count": len(suspicious_connections),
                "suspicious_startup_count": len(suspicious_startup),
                "persistence_count": len(persistence_items),
                "suspicious_persistence_count": sum(1 for p in persistence_items if p.get("is_suspicious")),
                "ioc_hit_count": len(ioc_hits),
                "timeline_event_count": len(timeline_events),
            },
            "ai_report": ai_report,
        }

        # 添加处置建议
        report_data["recommendations"] = ReportService._generate_recommendations(report_data)

        # Jinja2 渲染
        templates_dir = Path(settings.TEMPLATES_DIR)
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("report.html")

        # 读取内联样式
        css_path = templates_dir / "report_style.css"
        css_content = ""
        if css_path.exists():
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()

        html = template.render(data=report_data, css=css_content)
        return html

    @staticmethod
    def generate_pdf(host_id: int) -> bytes:
        """生成 PDF 报告.

        Args:
            host_id: 主机 ID.

        Returns:
            PDF 文件字节内容.

        Raises:
            ValueError: 报告生成失败.
        """
        html = ReportService.generate_html(host_id)
        pdf_bytes = html_to_pdf(html)
        if pdf_bytes is None:
            raise ValueError("PDF 生成失败，WeasyPrint 可能未正确安装")
        return pdf_bytes

    @staticmethod
    def _parse_profile(profile: Optional[dict]) -> Optional[dict]:
        """解析主机画像中的 JSON 字段."""
        if not profile:
            return None
        result = dict(profile)
        for field in ["cpu_info", "memory_info", "disk_info", "network_info",
                       "installed_software", "user_accounts", "security_products",
                       "system_summary"]:
            value = result.get(field)
            if isinstance(value, str):
                try:
                    result[field] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    @staticmethod
    def _generate_recommendations(data: dict) -> list:
        """根据分析结果生成处置建议."""
        recommendations = []
        analysis = data.get("analysis", {})
        risk_level = analysis.get("risk_level", "info") if analysis else "info"

        if risk_level in ("critical", "high"):
            recommendations.append("立即隔离主机，断开网络连接，防止横向移动。")
            recommendations.append("保留内存和磁盘镜像用于取证分析。")

        if data.get("stats", {}).get("abnormal_process_count", 0) > 0:
            recommendations.append("检查异常进程列表，终止可疑进程并分析其来源。")

        if data.get("stats", {}).get("suspicious_connection_count", 0) > 0:
            recommendations.append("检查可疑外连列表，在防火墙阻断恶意 IP 和域名。")

        if data.get("stats", {}).get("suspicious_persistence_count", 0) > 0:
            recommendations.append("清除可疑持久化痕迹，防止恶意程序重启后自动运行。")

        if data.get("stats", {}).get("ioc_hit_count", 0) > 0:
            recommendations.append(" IOC 命中表明主机可能已被入侵，建议进行深度取证分析。")

        if risk_level in ("medium", "low"):
            recommendations.append("持续监控主机状态，定期复查安全配置。")

        if not recommendations:
            recommendations.append("当前未发现明显安全问题，建议保持常规安全监控。")

        return recommendations
