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

# ── 加载 DDL 确保 incident_reports 表存在 ──
import app.database as db
import sqlite3

_REPORT_TABLE = """
CREATE TABLE IF NOT EXISTS incident_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    report_type     TEXT DEFAULT 'emergency',
    audience        TEXT DEFAULT 'leader',
    status          TEXT DEFAULT 'draft',
    summary         TEXT DEFAULT '',
    impact_scope    TEXT DEFAULT '{}',
    timeline_json   TEXT DEFAULT '[]',
    mitre_cover     TEXT DEFAULT '[]',
    evidence        TEXT DEFAULT '',
    recommendations TEXT DEFAULT '{}',
    case_id         INTEGER,
    host_id         INTEGER,
    created_by      TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""
try:
    with db.get_connection() as conn:
        conn.execute(_REPORT_TABLE)
        conn.commit()
except Exception:
    pass


# ── 报告 CRUD ──

@router.get("/reports")
def list_reports(status: str = "all", page: int = 1, page_size: int = 50):
    """报告列表."""
    try:
        with db.get_connection() as conn:
            conditions = ["1=1"]
            params = []
            if status != "all":
                conditions.append("status=?")
                params.append(status)
            where = " AND ".join(conditions)
            total = conn.execute(f"SELECT COUNT(*) FROM incident_reports WHERE {where}", params).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM incident_reports WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            return {"success": True, "data": {"items": [dict(r) for r in rows], "total": total}}
    except Exception as e:
        logger.error("list_reports failed: %s", e)
        return {"success": False, "data": {"items": [], "total": 0}}


@router.get("/reports/grouped-by-host")
def list_reports_grouped_by_host(status: str = "all"):
    """报告列表 — 按 host_id 分组（T-05）.

    - host_id=0 作为案件级报告，单独分组置顶
    - 其他 host_id 按组返回
    """
    try:
        with db.get_connection() as conn:
            conditions = ["1=1"]
            params: list = []
            if status != "all":
                conditions.append("status=?")
                params.append(status)
            where = " AND ".join(conditions)

            rows = conn.execute(
                f"SELECT * FROM incident_reports WHERE {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()

            case_reports: list[dict] = []
            host_groups: dict[int, list[dict]] = {}

            for r in rows:
                d = dict(r)
                hid = d.get("host_id", 0) or 0
                if hid == 0:
                    case_reports.append(d)
                else:
                    host_groups.setdefault(hid, []).append(d)

            groups: list[dict] = []
            if case_reports:
                groups.append({
                    "host_id": 0,
                    "host_name": "案件级报告",
                    "reports": case_reports,
                    "count": len(case_reports),
                })
            for hid, reports in sorted(host_groups.items()):
                groups.append({
                    "host_id": hid,
                    "host_name": f"主机 {hid}",
                    "reports": reports,
                    "count": len(reports),
                })

            return {"success": True, "data": {"groups": groups, "total": len(rows)}}
    except Exception as e:
        logger.error("list_reports_grouped_by_host failed: %s", e)
        return {"success": False, "data": {"groups": [], "total": 0}}


@router.get("/reports/{report_id}")
def get_report(report_id: int):
    """报告详情."""
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM incident_reports WHERE id=?", [report_id]).fetchone()
            if not row:
                raise HTTPException(404, "报告不存在")
            return {"success": True, "data": dict(row)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_report failed: %s", e)
        raise HTTPException(500, "查询失败")


@router.post("/reports")
def create_report(title: str = "未命名报告", report_type: str = "emergency",
                   audience: str = "leader", case_id: int = 0, host_id: int = 0,
                   created_by: str = ""):
    """新建报告."""
    try:
        from datetime import datetime
        now = datetime.now().isoformat()
        with db.get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO incident_reports (title, report_type, audience, status,
                   case_id, host_id, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?)""",
                [title, report_type, audience, case_id or None, host_id or None, created_by, now, now]
            )
            conn.commit()
            return {"success": True, "data": {"id": cur.lastrowid}}
    except Exception as e:
        logger.error("create_report failed: %s", e)
        raise HTTPException(500, "创建失败")


@router.put("/reports/{report_id}")
def update_report(report_id: int, title: str = None, summary: str = None,
                   evidence: str = None, report_type: str = None, audience: str = None,
                   status: str = None, impact_scope: str = None,
                   timeline_json: str = None, mitre_cover: str = None,
                   recommendations: str = None):
    """更新报告."""
    try:
        from datetime import datetime
        updates = {}
        if title is not None: updates["title"] = title
        if summary is not None: updates["summary"] = summary
        if evidence is not None: updates["evidence"] = evidence
        if report_type is not None: updates["report_type"] = report_type
        if audience is not None: updates["audience"] = audience
        if status is not None: updates["status"] = status
        if impact_scope is not None: updates["impact_scope"] = impact_scope
        if timeline_json is not None: updates["timeline_json"] = timeline_json
        if mitre_cover is not None: updates["mitre_cover"] = mitre_cover
        if recommendations is not None: updates["recommendations"] = recommendations
        if not updates:
            return {"success": True}
        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [report_id]
        with db.get_connection() as conn:
            conn.execute(f"UPDATE incident_reports SET {set_clause} WHERE id=?", params)
            conn.commit()
            return {"success": True}
    except Exception as e:
        logger.error("update_report failed: %s", e)
        raise HTTPException(500, "更新失败")


@router.delete("/reports/{report_id}")
def delete_report(report_id: int):
    """删除报告."""
    try:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM incident_reports WHERE id=?", [report_id])
            conn.commit()
            return {"success": True}
    except Exception as e:
        logger.error("delete_report failed: %s", e)
        raise HTTPException(500, "删除失败")


@router.post("/reports/{report_id}/submit")
def submit_report(report_id: int):
    """草稿→待审."""
    return update_report(report_id, status="review")


@router.post("/reports/{report_id}/publish")
def publish_report(report_id: int):
    """待审→已发."""
    return update_report(report_id, status="published")


# ── T-10: 导出端点 ──


@router.get("/reports/{report_id}/export/json")
def export_report_json(report_id: int):
    """导出报告为 JSON 格式."""
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM incident_reports WHERE id = ?", (report_id,),
            ).fetchone()
        if not row:
            raise HTTPException(404, "报告不存在")
        return {"success": True, "data": dict(row)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export_report_json failed: %s", e)
        raise HTTPException(500, "导出失败")


@router.get("/reports/{report_id}/export/docx")
def export_report_docx(report_id: int):
    """导出报告为 DOCX 文件."""
    try:
        from app.services.docx_export_service import DocxExportService

        docx_bytes = DocxExportService.export(report_id)
        if docx_bytes is None:
            raise HTTPException(404, "报告不存在或导出失败")
        from fastapi.responses import Response
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=report_{report_id}.docx",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export_report_docx failed: %s", e)
        raise HTTPException(500, "DOCX 导出失败")


@router.get("/reports/{report_id}/export/markdown")
def export_report_markdown(report_id: int):
    """导出报告为 Markdown 文本."""
    try:
        from app.services.markdown_export_service import MarkdownExportService

        md_text = MarkdownExportService.export(report_id)
        if md_text is None:
            raise HTTPException(404, "报告不存在或导出失败")
        from fastapi.responses import Response
        return Response(
            content=md_text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=report_{report_id}.md",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export_report_markdown failed: %s", e)
        raise HTTPException(500, "Markdown 导出失败")


# ── T-11: 审计日志 API ──


@router.get("/reports/{report_id}/audit-logs")
def list_report_audit_logs(
    report_id: int,
    page: int = 1,
    page_size: int = 50,
):
    """查询报告的审计日志历史（T-11）."""
    try:
        with db.get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM incident_report_audit WHERE report_id = ?",
                (report_id,),
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                """SELECT * FROM incident_report_audit
                   WHERE report_id = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (report_id, page_size, offset),
            ).fetchall()
            return {
                "success": True,
                "data": {
                    "items": [dict(r) for r in rows],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                },
            }
    except Exception as e:
        logger.error("list_report_audit_logs failed: %s", e)
        return {"success": False, "data": {"items": [], "total": 0}}


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
