"""案件 CRUD 接口."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.schemas.case import CaseCreate, CaseUpdate
from app.services.auth_service import get_current_user
from app.services.case_service import CaseService
from app.services.purge_service import purge_case, preview_case_purge

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_cases(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="搜索关键词"),
    current_user: dict = Depends(get_current_user),
):
    """获取案件列表（分页 + 搜索）."""
    result = CaseService.list_cases(page=page, size=size, search=search)
    return {"code": 0, "data": result, "message": "success"}


@router.post("")
def create_case(
    case: CaseCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建案件."""
    try:
        result = CaseService.create_case(
            name=case.name,
            case_number=case.case_number,
            description=case.description,
            priority=case.priority,
        )
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


class PurgeRequest(BaseModel):
    """清空案件请求体."""

    case_id: int = Field(..., description="目标案件的数字主键 ID（精确匹配，禁模糊）")
    confirm_text: str = Field(..., description="二次确认文本，须等于案件 ID 的字符串形式")
    export_snapshot: bool = Field(True, description="删除前是否导出 JSON 快照（默认开启）")


@router.get("/purge-preview/{case_id}")
def purge_preview(case_id: int, current_user: dict = Depends(get_current_user)):
    """预览清案影响面：返回各表预估删除行数（仅管理员可看）."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可执行清空案件操作",
        )
    data = preview_case_purge(case_id)
    return {"code": 0, "data": data, "message": "success"}


@router.post("/purge")
def purge(req: PurgeRequest, request: Request,
           current_user: dict = Depends(get_current_user)):
    """清空指定案件及其全部级联数据（仅管理员，需手输 ID 二次确认）."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可执行清空案件操作",
        )
    client_ip = request.client.host if request.client else ""
    result = purge_case(
        case_id=req.case_id,
        confirm_text=req.confirm_text,
        operator=current_user,
        export_snapshot=req.export_snapshot,
        client_ip=client_ip,
    )
    return {"code": 0, "data": result, "message": "案件已清空"}


@router.get("/{case_id}/summary")
def get_case_summary(case_id: int, current_user: dict = Depends(get_current_user)):
    """获取案件详情聚合态势（告警/资产/处置/取证/IOC/TTP/AI/时间线）.

    应急研判一站式数据，避免前端多次往返。详见 app.services.case_summary。
    """
    from app.services.case_summary import get_case_summary as build_summary

    case = CaseService.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    data = build_summary(case_id)
    return {"code": 0, "data": data, "message": "success"}


@router.get("/{case_id}")
def get_case(case_id: int, current_user: dict = Depends(get_current_user)):
    """获取案件详情."""
    case = CaseService.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    return {"code": 0, "data": case, "message": "success"}


@router.put("/{case_id}")
def update_case(
    case_id: int,
    case: CaseUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新案件."""
    existing = CaseService.get_case(case_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    result = CaseService.update_case(
        case_id,
        name=case.name,
        description=case.description,
        status=case.status,
        priority=case.priority,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.delete("/{case_id}")
def delete_case(case_id: int, current_user: dict = Depends(get_current_user)):
    """删除案件."""
    existing = CaseService.get_case(case_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    CaseService.delete_case(case_id)
    return {"code": 0, "data": {"success": True}, "message": "success"}
