"""报告接口 — 生成和导出报告.

注意：报告接口不强制 JWT 认证，因为 HTML 报告通过 iframe 加载无法携带
Authorization Header。前端路由守卫已确保用户登录后才能访问报告页面.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.services.host_service import HostService
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/hosts/{host_id}/report")
def get_html_report(host_id: int):
    """获取 HTML 报告."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    try:
        html = ReportService.generate_html(host_id)
        return Response(content=html, media_type="text/html")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Report generation failed for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"报告生成失败: {exc}",
        )


@router.get("/hosts/{host_id}/report/pdf")
def get_pdf_report(host_id: int):
    """下载 PDF 报告."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    try:
        pdf_bytes = ReportService.generate_pdf(host_id)
        hostname = host.get("hostname", "host")
        filename = f"report_{hostname}_{host_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("PDF generation failed for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF 生成失败: {exc}",
        )
