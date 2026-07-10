"""报告接口 — 生成和导出报告.

注意：报告接口不强制 JWT 认证，因为 HTML 报告通过 iframe 加载无法携带
Authorization Header。前端路由守卫已确保用户登录后才能访问报告页面.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.host_service import HostService
from app.services.report_service import ReportService
from app.models.remediation_checklist import RemediationChecklist

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/hosts/{host_id}/report")
def get_html_report(host_id: int, report_level: str = "technical"):
    """获取 HTML 报告（任务⑤ 支持 ?report_level=executive|technical）."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    try:
        html = ReportService.generate_html(host_id, report_level=report_level)
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
def get_pdf_report(host_id: int, report_level: str = "technical"):
    """下载 PDF 报告（任务⑤ 支持 ?report_level=executive|technical）."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    try:
        pdf_bytes = ReportService.generate_pdf(host_id, report_level=report_level)
        hostname = host.get("hostname", "host")
        filename = f"report_{hostname}_{host_id}_{report_level}.pdf"
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


class ChecklistItem(BaseModel):
    """处置清单单项."""

    id: str = ""
    text: str = ""
    checked: bool = False
    source: str = "manual"


class ChecklistUpdate(BaseModel):
    """处置清单更新请求（全量覆盖，决策⑨ 无需二次复核）."""

    items: list[ChecklistItem] = []


@router.get("/reports/{host_id}/checklist")
def get_checklist(host_id: int):
    """获取某主机的处置清单（任务⑤ 处置闭环）."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    record = RemediationChecklist.get_by_host(host_id)
    if not record:
        return {"host_id": host_id, "items": []}
    return {"host_id": host_id, "items": record["items"]}


@router.put("/reports/{host_id}/checklist")
def put_checklist(host_id: int, payload: ChecklistUpdate):
    """更新（全量覆盖）某主机的处置清单（任务⑤ 处置闭环）.

    前端勾选 checked 直接 PUT 落库，无需二次复核。
    """
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    case_id = host.get("case_id")
    items = [it.model_dump() for it in payload.items]
    record = RemediationChecklist.update_items(host_id, items)
    return {"host_id": host_id, "items": record["items"]}
