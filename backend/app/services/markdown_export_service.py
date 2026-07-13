"""Markdown 报告导出服务 — 导出 7 段式安全分析报告."""

import json
import logging
import re
from typing import Any, Optional

from app.database import get_connection
from app.models.host import Host
from app.models.ai_analysis import AiAnalysisReport

logger = logging.getLogger(__name__)


class MarkdownExportService:
    """Markdown 报告导出服务."""

    @staticmethod
    def export(report_id: int) -> Optional[str]:
        """导出 incident_report 为 Markdown 文本.

        Args:
            report_id: incident_reports 表的主键 ID.

        Returns:
            Markdown 文本字符串，失败返回 None.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM incident_reports WHERE id = ?", (report_id,),
            ).fetchone()
        if not row:
            logger.error("incident_report %d not found", report_id)
            return None
        report = dict(row)

        ai_report_id = report.get("ai_report_id")
        ai_report: Optional[dict] = None
        if ai_report_id:
            ai_report = AiAnalysisReport.get_by_id(ai_report_id)

        host = Host.get_by_id(report.get("host_id", 0)) if report.get("host_id") else None

        impact_scope = MarkdownExportService._safe_parse_json(report.get("impact_scope", "[]"))
        timeline_json = MarkdownExportService._safe_parse_json(report.get("timeline_json", "[]"))
        mitre_cover = MarkdownExportService._safe_parse_json(report.get("mitre_cover", "[]"))
        recommendations_raw = MarkdownExportService._safe_parse_json(report.get("recommendations", "{}"))
        confidence = MarkdownExportService._safe_parse_json(report.get("confidence_metadata", "{}"))

        lines: list[str] = []

        # ── 标题 ──
        title = report.get("title", "安全分析报告")
        lines.append(f"# {title}")
        lines.append("")
        lines.append(
            f"> **报告类型**: {report.get('report_type', 'N/A')}  |  "
            f"**状态**: {report.get('status', 'N/A')}  |  "
            f"**生成时间**: {report.get('created_at', '')}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # ── 段落1: 报告概要 ──
        lines.append("## 一、报告概要")
        lines.append("")
        summary = report.get("summary", "") or "暂无概要"
        lines.append(summary)
        lines.append("")

        # ── 段落2: 主机信息 ──
        lines.append("## 二、主机信息")
        lines.append("")
        if host:
            hostname = host.get("hostname", "N/A")
            ip = host.get("ip_address", "N/A")
            os_info = host.get("os_type", "N/A")
            os_ver = host.get("os_version", "")
            lines.append(f"- **主机名**: {hostname}")
            lines.append(f"- **IP 地址**: {ip}")
            lines.append(f"- **操作系统**: {os_info}" + (f" ({os_ver})" if os_ver else ""))
        else:
            lines.append("主机信息: N/A")
        lines.append("")

        # ── 段落3: 风险分析 ──
        lines.append("## 三、风险分析")
        lines.append("")
        risk_score = report.get("risk_score", 0)
        lines.append(f"- **风险评分**: {risk_score}/100")
        if isinstance(confidence, dict) and confidence.get("summary") is not None:
            lines.append(f"- **概要置信度**: {confidence['summary']}%")
        if isinstance(confidence, dict):
            conf_details = ", ".join(
                f"{k}: {v}%" for k, v in confidence.items() if isinstance(v, (int, float))
            )
            if conf_details:
                lines.append(f"- **段落置信度**: {conf_details}")
        lines.append("")

        # ── 段落4: 威胁分析 ──
        lines.append("## 四、威胁分析")
        lines.append("")

        if isinstance(impact_scope, list) and impact_scope:
            lines.append("### 影响系统")
            for item in impact_scope:
                if isinstance(item, dict):
                    sys_name = item.get("system", item.get("name", str(item)))
                    sys_desc = item.get("description", "")
                    line = f"- **{sys_name}**"
                    if sys_desc:
                        line += f": {sys_desc}"
                    lines.append(line)
                else:
                    lines.append(f"- {item}")
        else:
            lines.append("暂无影响范围数据")
        lines.append("")

        if isinstance(mitre_cover, list) and mitre_cover:
            lines.append("### ATT&CK 覆盖")
            lines.append("")
            lines.append("| 技术ID | 技术名称 | 战术 |")
            lines.append("|--------|----------|------|")
            for tech in mitre_cover:
                if isinstance(tech, dict):
                    tid = tech.get("id", tech.get("technique_id", ""))
                    tname = tech.get("name", tech.get("technique_name", ""))
                    tactic = tech.get("tactic", tech.get("kill_chain_phase", ""))
                    lines.append(f"| {tid} | {tname} | {tactic} |")
                else:
                    lines.append(f"| {tech} | | |")
            lines.append("")

        # ── 段落5: 时间线 ──
        lines.append("## 五、时间线")
        lines.append("")
        if isinstance(timeline_json, list) and timeline_json:
            lines.append("| 时间 | 事件 | 来源 |")
            lines.append("|------|------|------|")
            for event in timeline_json:
                if isinstance(event, dict):
                    ts = event.get("timestamp", event.get("time", ""))
                    desc = event.get("description", event.get("event", ""))
                    source = event.get("source", "")
                    # 转义 Markdown 表格中的竖线
                    desc_safe = str(desc).replace("|", "\\|")
                    lines.append(f"| {ts} | {desc_safe} | {source} |")
        else:
            lines.append("暂无时间线数据")
        lines.append("")

        # ── 段落6: 证据 ──
        lines.append("## 六、证据")
        lines.append("")
        evidence = report.get("evidence", "") or "暂无证据"
        evidence_clean = re.sub(r'\[🔗\]\([^)]+\)\s*', '', evidence)
        for ev_line in evidence_clean.split("\n"):
            stripped = ev_line.strip()
            if stripped:
                lines.append(f"- {stripped}")
        lines.append("")

        # ── 段落7: 处置建议 ──
        lines.append("## 七、处置建议")
        lines.append("")
        if isinstance(recommendations_raw, dict):
            items = recommendations_raw.get("items", recommendations_raw.get("recommendations", []))
            if isinstance(items, list) and items:
                for idx, rec in enumerate(items, 1):
                    if isinstance(rec, dict):
                        title_text = rec.get("title", rec.get("action", f"建议 {idx}"))
                        desc = rec.get("description", rec.get("detail", ""))
                        priority = rec.get("priority", "")
                        status_text = rec.get("status", "")

                        line = f"### {idx}. {title_text}"
                        if priority:
                            line += f" `[{priority}]`"
                        lines.append(line)
                        if desc:
                            lines.append("")
                            lines.append(f"  {desc}")
                            lines.append("")
                        if status_text:
                            lines.append(f"  **状态**: {status_text}")
                    else:
                        lines.append(f"{idx}. {rec}")
                    lines.append("")
            else:
                lines.append("暂无处置建议")
        else:
            lines.append("暂无处置建议")
        lines.append("")

        # ── 结束 ──
        lines.append("---")
        lines.append("")
        lines.append("*报告完*")

        return "\n".join(lines)

    @staticmethod
    def _safe_parse_json(val: Any) -> Any:
        """安全解析 JSON 字符串."""
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val
