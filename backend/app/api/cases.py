"""案件 CRUD 接口."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.case import CaseCreate, CaseUpdate
from app.services.auth_service import get_current_user
from app.services.case_service import CaseService

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
