"""HTML → PDF 转换工具（WeasyPrint）."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def html_to_pdf(html_str: str) -> Optional[bytes]:
    """将 HTML 字符串转换为 PDF.

    使用 WeasyPrint 进行转换。如果 WeasyPrint 不可用，返回 None.

    Args:
        html_str: HTML 字符串.

    Returns:
        PDF 字节内容，失败时返回 None.
    """
    try:
        from weasyprint import HTML

        pdf = HTML(string=html_str).write_pdf()
        logger.info("PDF generated successfully")
        return pdf
    except ImportError:
        logger.error("WeasyPrint is not installed. PDF generation not available.")
        return None
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        return None
