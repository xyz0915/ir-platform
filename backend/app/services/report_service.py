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
from app.models.remediation_checklist import RemediationChecklist
from app.services.report_template_service import ReportTemplateService
from app.services.data_masking import apply as mask_data
from app.utils.pdf_converter import html_to_pdf

logger = logging.getLogger(__name__)


def _svg_escape(text: Any) -> str:
    """转义 SVG/XML 文本中的特殊字符，避免破坏内联标签。"""
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class ReportService:
    """报告生成服务."""

    @staticmethod
    def generate_html(
        host_id: int,
        report_level: str = "technical",
        template_config: Optional[dict] = None,
    ) -> str:
        """生成 HTML 报告（任务⑤ 支持 executive / technical 双版本）.

        Args:
            host_id: 主机 ID。
            report_level: ``executive``（管理层/脱敏/图表）或 ``technical``（含处置清单）。
            template_config: 可选报告模板配置；缺省从 ReportTemplateService 读取。

        Returns:
            HTML 报告字符串。

        Raises:
            ValueError: 主机不存在或未分析.
        """
        report_level = (report_level or "technical").lower()
        if report_level not in ("executive", "technical"):
            report_level = "technical"

        template_cfg = template_config or ReportTemplateService.get_template()

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

        # v1.3.0 作战化：解析 AI 报告的 ATT&CK / 攻击链 / 稀有 / 受众新列
        ops = ReportService._parse_ops_columns(ai_report)

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

        # 读取内联样式
        css_path = templates_dir / "report_style.css"
        css_content = ""
        if css_path.exists():
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()

        if report_level == "executive":
            # 管理层视图：完全脱敏 + 内联 SVG 图表（决策⑧）
            masked_data = mask_data(report_data)
            masked_data["chart_svg"] = ReportService._build_summary_svg(report_data["stats"])
            # v1.3.0 作战化：管理层仅看 ATT&CK 统计（脱敏，不展开技术细节）
            masked_data["attck_summary"] = {
                "technique_count": len(ops.get("mitre_attack") or []),
                "chain_count": len(ops.get("attack_chain_hits") or []),
                "rare_count": len(ops.get("rare_high_signals") or []),
            }
            masked_data["template"] = template_cfg
            template = env.get_template("report_executive.html")
            html = template.render(data=masked_data, css=css_content)
            return html

        # 技术视图：末尾嵌入处置清单复选框（决策⑨）
        checklist_cfg = (template_cfg.get("technical") or {})
        if checklist_cfg.get("include_checklist", True):
            checklist = RemediationChecklist.get_by_host(host_id)
            report_data["checklist"] = checklist["items"] if checklist else []
        else:
            report_data["checklist"] = []

        # v1.3.0 作战化：技术报告注入 ATT&CK 矩阵 SVG + 攻击链叙述数据
        report_data["attck_matrix_svg"] = ReportService._build_attck_matrix_svg(
            ops.get("mitre_attack") or [],
            ops.get("attack_chain_hits") or [],
        )
        report_data["attack_chain_hits"] = ops.get("attack_chain_hits") or []
        report_data["rare_high_signals"] = ops.get("rare_high_signals") or []

        template = env.get_template("report.html")
        html = template.render(data=report_data, css=css_content)
        return html

    @staticmethod
    def _build_summary_svg(stats: dict) -> str:
        """根据统计概览生成内联 SVG 概要柱状图（决策⑧ 后端内联）.

        仅使用计数类指标，不包含任何敏感值。
        """
        items = [
            ("异常进程", stats.get("abnormal_process_count", 0)),
            ("可疑外连", stats.get("suspicious_connection_count", 0)),
            ("可疑持久化", stats.get("suspicious_persistence_count", 0)),
            ("IOC 命中", stats.get("ioc_hit_count", 0)),
        ]
        max_val = max((v for _, v in items), default=1) or 1
        width = 460
        row_h = 34
        height = row_h * len(items) + 20
        bar_max_w = 320
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="安全态势分布">'
        ]
        for idx, (label, val) in enumerate(items):
            y = 10 + idx * row_h
            bar_w = int(bar_max_w * (val / max_val)) if max_val else 0
            bar_w = max(bar_w, 2 if val else 0)
            svg_parts.append(
                f'<text x="0" y="{y + 16}" font-size="13" fill="#333">{label}</text>'
            )
            svg_parts.append(
                f'<rect x="110" y="{y + 4}" width="{bar_w}" height="18" rx="3" fill="#c0392b"/>'
            )
            svg_parts.append(
                f'<text x="{110 + bar_w + 6}" y="{y + 18}" font-size="13" fill="#333">{val}</text>'
            )
        svg_parts.append("</svg>")
        return "".join(svg_parts)

    @staticmethod
    def _parse_ops_columns(ai_report: Optional[dict]) -> dict:
        """解析 AI 报告作战化新列（audience/mitre_attack/attack_chain_hits/rare_high_signals）。

        旧库无这些列时返回空结构，保证向后兼容。
        """
        result: dict[str, Any] = {
            "audience": None,
            "mitre_attack": [],
            "attack_chain_hits": [],
            "rare_high_signals": [],
        }
        if not ai_report:
            return result
        for col in ("audience", "mitre_attack", "attack_chain_hits", "rare_high_signals"):
            raw = ai_report.get(col)
            if isinstance(raw, str) and raw.strip():
                try:
                    result[col] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    result[col] = []
            elif isinstance(raw, (list, dict)):
                result[col] = raw
        return result

    @staticmethod
    def _build_attck_matrix_svg(mitre_attack: list[dict], attack_chain_hits: list[dict]) -> str:
        """生成 ATT&CK 技术矩阵内联 SVG（v1.3.0 支柱④）。

        按战术（tactic）分组展示技术点；命中攻击链的战术以红色高亮；
        顶部注明攻击链命中数，便于技术读者快速定位。

        Args:
            mitre_attack: 已查表的技术点列表（含 id/name/tactic/tactic_id/known）。
            attack_chain_hits: 攻击链命中列表（仅用于标注，不重判）。

        Returns:
            内联 SVG 字符串；无技术点时返回占位说明。
        """
        techs = [t for t in (mitre_attack or []) if isinstance(t, dict)]
        if not techs:
            return (
                '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="60" '
                'viewBox="0 0 680 60" role="img" aria-label="ATT&CK 矩阵">'
                '<text x="0" y="34" font-size="14" fill="#888">'
                '本次分析未产出 ATT&amp;CK 技术点覆盖</text></svg>'
            )

        # 攻击链命中的技术 ID 集合（用于高亮）
        chain_ids: set[str] = set()
        for hit in (attack_chain_hits or []):
            if not isinstance(hit, dict):
                continue
            for step in hit.get("steps", []):
                if isinstance(step, dict) and step.get("technique_id"):
                    chain_ids.add(str(step["technique_id"]))

        # 按战术分组
        grouped: dict[str, list[dict]] = {}
        for t in techs:
            tac = t.get("tactic") or "未分类"
            grouped.setdefault(tac, []).append(t)

        # 布局参数
        label_w = 130
        chip_w = 150
        chip_h = 46
        gap_x = 10
        gap_y = 10
        header_h = 26
        per_row = max(1, (680 - label_w) // (chip_w + gap_x))
        svg_parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="680" '
        ]
        # 高度待定，先占位，最后包裹
        body: list[str] = []
        y = header_h
        for tactic, items in grouped.items():
            rows = (len(items) + per_row - 1) // per_row
            block_h = rows * (chip_h + gap_y)
            # 战术标签
            body.append(
                f'<text x="0" y="{y + chip_h // 2}" font-size="13" font-weight="bold" '
                f'fill="#222">{_svg_escape(tactic)}</text>'
            )
            for i, t in enumerate(items):
                r = i // per_row
                c = i % per_row
                x = label_w + c * (chip_w + gap_x)
                yy = y + r * (chip_h + gap_y)
                tid = str(t.get("id", ""))
                in_chain = tid in chain_ids
                fill = "#c0392b" if in_chain else "#2c6fbb"
                known = t.get("known", True)
                name = _svg_escape(str(t.get("name", tid))[:18])
                label = f"{_svg_escape(tid)}"
                body.append(
                    f'<rect x="{x}" y="{yy}" width="{chip_w}" height="{chip_h}" rx="5" '
                    f'fill="{fill}" opacity="{0.92 if known else 0.6}"/>'
                )
                body.append(
                    f'<text x="{x + 8}" y="{yy + 18}" font-size="12" fill="#fff" '
                    f'font-weight="bold">{label}</text>'
                )
                body.append(
                    f'<text x="{x + 8}" y="{yy + 36}" font-size="11" fill="#f0f0f0">{name}</text>'
                )
            y += block_h + gap_y

        total_h = y + 10
        svg_parts[0] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{total_h}" '
            f'viewBox="0 0 680 {total_h}" role="img" aria-label="ATT&CK 技术矩阵">'
        )
        svg_parts.append(
            f'<text x="0" y="16" font-size="13" fill="#333">'
            f'ATT&amp;CK 技术覆盖：{len(techs)} 项 / 攻击链命中 {len(attack_chain_hits or [])} 条'
            f'（红色=命中攻击链）</text>'
        )
        svg_parts.extend(body)
        svg_parts.append("</svg>")
        return "".join(svg_parts)

    @staticmethod
    def generate_pdf(
        host_id: int,
        report_level: str = "technical",
        template_config: Optional[dict] = None,
    ) -> bytes:
        """生成 PDF 报告.

        Args:
            host_id: 主机 ID。
            report_level: ``executive`` 或 ``technical``。
            template_config: 可选报告模板配置。

        Returns:
            PDF 文件字节内容。

        Raises:
            ValueError: 报告生成失败.
        """
        html = ReportService.generate_html(
            host_id, report_level=report_level, template_config=template_config
        )
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
