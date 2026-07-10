"""AI 分析报告 PDF 导出服务.

使用 Jinja2 模板渲染 HTML，WeasyPrint 生成 PDF。
支持 Markdown 内容自动转为 HTML 嵌入。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.models.ai_analysis import AiAnalysisReport
from app.models.host import Host

logger = logging.getLogger(__name__)

# 尝试导入 markdown 库用于转换 AI 内容
try:
    import markdown as _md

    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False
    logger.warning("markdown library not available, AI content will be rendered as plain text")


# ---------------------------------------------------------------------------
# PDF 报告 Jinja2 模板（内联，简洁专业风格）
# ---------------------------------------------------------------------------

PDF_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AI 深度分析报告</title>
<style>
  @page {
    size: A4;
    margin: 2cm 1.5cm 2.5cm 1.5cm;
    @top-center {
      content: "AI 深度分析报告 — {{ hostname }} ({{ ip_address }})";
      font-size: 9pt;
      color: #666;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    }
    @bottom-center {
      content: "第 " counter(page) " 页";
      font-size: 9pt;
      color: #999;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    }
  }
  @page :first {
    @top-center {
      content: none;
    }
  }
  body {
    font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.8;
    color: #333;
  }
  .cover {
    text-align: center;
    padding: 80px 0 40px 0;
    border-bottom: 3px solid #1a73e8;
    margin-bottom: 40px;
  }
  .cover h1 {
    font-size: 26pt;
    color: #1a73e8;
    margin: 0 0 8px 0;
    letter-spacing: 2px;
  }
  .cover .subtitle {
    font-size: 14pt;
    color: #666;
    margin: 0 0 30px 0;
  }
  .cover .meta {
    font-size: 10pt;
    color: #555;
    line-height: 2.2;
  }
  .cover .meta span {
    display: inline-block;
    min-width: 80px;
    text-align: right;
    color: #888;
  }
  h2 {
    font-size: 16pt;
    color: #1a73e8;
    border-bottom: 2px solid #1a73e8;
    padding-bottom: 6px;
    margin: 30px 0 16px 0;
    page-break-before: always;
  }
  h2:first-of-type {
    page-break-before: avoid;
  }
  h3 {
    font-size: 13pt;
    color: #444;
    margin: 16px 0 8px 0;
  }
  p {
    margin: 6px 0;
  }
  .section-content {
    padding: 0 4px;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  .section-content ul, .section-content ol {
    padding-left: 20px;
  }
  .section-content li {
    margin: 4px 0;
  }
  .section-content pre {
    background: #f5f5f5;
    padding: 12px;
    border-radius: 4px;
    font-size: 9pt;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .section-content code {
    background: #f0f0f0;
    padding: 1px 4px;
    border-radius: 2px;
    font-size: 9pt;
  }
  .section-content table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
  }
  .section-content th, .section-content td {
    border: 1px solid #ddd;
    padding: 6px 8px;
    text-align: left;
    font-size: 9pt;
  }
  .section-content th {
    background: #e8f0fe;
    font-weight: 600;
  }
  .section-content blockquote {
    border-left: 3px solid #1a73e8;
    padding-left: 12px;
    color: #555;
    margin: 8px 0;
  }
  .footer-note {
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid #ddd;
    font-size: 9pt;
    color: #999;
    text-align: center;
  }
</style>
</head>
<body>

<div class="cover">
  <h1>AI 深度分析报告</h1>
  <p class="subtitle">Deep Analysis Report</p>
  <div class="meta">
    {% if hostname %}<p><span>主机名: </span>{{ hostname }}</p>{% endif %}
    {% if ip_address %}<p><span>IP 地址: </span>{{ ip_address }}</p>{% endif %}
    {% if os_type %}<p><span>操作系统: </span>{{ os_type }} {{ os_version or '' }}</p>{% endif %}
    <p><span>分析模型: </span>{{ model_used }}</p>
    <p><span>Token 消耗: </span>{{ tokens_used }}</p>
    <p><span>报告版本: </span>v{{ version }}</p>
    <p><span>生成时间: </span>{{ report_time }}</p>
  </div>
</div>

{% if risk_assessment %}
<h2>一、风险评估</h2>
<div class="section-content">{{ risk_assessment }}</div>
{% endif %}

{% if threat_analysis %}
<h2>二、威胁分析</h2>
<div class="section-content">{{ threat_analysis }}</div>
{% endif %}

{% if timeline_analysis %}
<h2>三、时间线解读</h2>
<div class="section-content">{{ timeline_analysis }}</div>
{% endif %}

{% if recommendations %}
<h2>四、处置建议</h2>
<div class="section-content">{{ recommendations }}</div>
{% endif %}

<div class="footer-note">
  本报告由 AI 模型自动生成，仅供参考 — 生成时间: {{ report_time }}
</div>

</body>
</html>"""


class PdfExportService:
    """AI 分析报告 PDF 导出服务.

    使用 Jinja2 模板 + WeasyPrint 生成专业格式的 PDF 报告.
    """

    @staticmethod
    def export(host_id: int, version: Optional[int] = None) -> Optional[bytes]:
        """导出主机 AI 分析报告为 PDF.

        Args:
            host_id: 主机 ID.
            version: 指定版本号，None 则导出最新版本.

        Returns:
            PDF 文件字节内容，失败返回 None.

        Raises:
            ValueError: 主机不存在或报告不存在.
        """
        # 获取主机信息
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")

        # 获取报告
        if version is not None:
            report = AiAnalysisReport.get_by_version(host_id, version)
        else:
            report = AiAnalysisReport.get_by_host(host_id)

        if not report:
            raise ValueError(f"主机 {host_id} 没有 AI 分析报告")

        # 将 Markdown/JSON 内容转为 HTML
        risk_html = PdfExportService._content_to_html(report.get("risk_assessment", ""))
        threat_html = PdfExportService._content_to_html(report.get("threat_analysis", ""))
        timeline_html = PdfExportService._content_to_html(report.get("timeline_analysis", ""))
        rec_html = PdfExportService._content_to_html(report.get("recommendations", ""))

        # 准备模板数据
        template_data = {
            "hostname": host.get("hostname", ""),
            "ip_address": host.get("ip_address", ""),
            "os_type": host.get("os_type", ""),
            "os_version": host.get("os_version", ""),
            "model_used": report.get("model_used", "Unknown"),
            "tokens_used": report.get("tokens_used", 0),
            "version": report.get("version", 1),
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "risk_assessment": risk_html,
            "threat_analysis": threat_html,
            "timeline_analysis": timeline_html,
            "recommendations": rec_html,
        }

        # Jinja2 渲染
        html_str = PdfExportService._render_template(template_data)

        # WeasyPrint 生成 PDF
        pdf_bytes = PdfExportService._html_to_pdf(html_str)
        if pdf_bytes is None:
            raise ValueError("PDF 生成失败，请确认 WeasyPrint 已正确安装")

        logger.info(
            "PDF report exported for host %d (v%d), model=%s, size=%d bytes",
            host_id,
            template_data["version"],
            template_data["model_used"],
            len(pdf_bytes),
        )
        return pdf_bytes

    @staticmethod
    def _content_to_html(content: str) -> str:
        """将 AI 分析内容转为 HTML.

        内容可能是 JSON 字符串（旧格式）或 Markdown 文本。
        优先使用 markdown 库转换，回退为纯文本 + 换行处理.
        """
        if not content:
            return ""

        # 尝试解析 JSON（旧格式存储的是 JSON 序列化的 dict）
        text = content
        if content.strip().startswith("{"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    # 展平 dict 为可读文本
                    parts = []
                    for key, value in parsed.items():
                        if isinstance(value, str):
                            parts.append(value)
                        elif isinstance(value, list):
                            parts.append("\n".join(str(v) for v in value))
                        else:
                            parts.append(str(value))
                    text = "\n\n".join(parts)
            except (json.JSONDecodeError, TypeError):
                text = content

        # Markdown → HTML
        if _HAS_MARKDOWN:
            try:
                html = _md.markdown(
                    text,
                    extensions=["extra", "codehilite", "tables", "nl2br"],
                )
                return html
            except Exception:
                logger.warning("Markdown conversion failed, using plain text")

        # 回退：简单 HTML 转义 + 换行处理
        escaped = (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n\n", "</p><p>")
            .replace("\n", "<br>")
        )
        return f"<p>{escaped}</p>"

    @staticmethod
    def _render_template(data: dict) -> str:
        """使用 Jinja2 渲染 PDF 报告模板.

        Args:
            data: 模板数据字典.

        Returns:
            渲染后的 HTML 字符串.
        """
        from jinja2 import Environment

        env = Environment()
        template = env.from_string(PDF_REPORT_TEMPLATE)
        return template.render(**data)

    @staticmethod
    def _html_to_pdf(html_str: str) -> Optional[bytes]:
        """使用 WeasyPrint 将 HTML 转为 PDF.

        Args:
            html_str: HTML 字符串.

        Returns:
            PDF 字节内容，失败返回 None.
        """
        try:
            from weasyprint import HTML

            pdf = HTML(string=html_str).write_pdf()
            return pdf
        except ImportError:
            logger.error("WeasyPrint is not installed. PDF generation not available.")
            return None
        except Exception as exc:
            logger.error("WeasyPrint PDF generation failed: %s", exc)
            return None
