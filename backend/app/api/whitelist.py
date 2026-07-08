"""白名单接口 — 白名单 CRUD API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.whitelist import WhitelistModel
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/whitelist")
def list_whitelist(
    category: Optional[str] = Query(None, description="按类别筛选（path/process_name/signature）"),
    current_user: dict = Depends(get_current_user),
):
    """获取白名单列表."""
    items = WhitelistModel.list_all(category)
    return {"code": 0, "data": items, "message": "success"}


@router.post("/whitelist")
def create_whitelist(data: dict, current_user: dict = Depends(get_current_user)):
    """创建白名单项.

    Request body 需包含:
    - category: 类别（path / process_name / signature）
    - pattern: 匹配值
    - description: 描述（可选）
    """
    category = data.get("category")
    pattern = data.get("pattern")
    if not category or not pattern:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="category 和 pattern 为必填字段",
        )
    item = {
        "category": category,
        "pattern": pattern,
        "source": "user",
        "description": data.get("description", ""),
        "enabled": True,
    }
    WhitelistModel.batch_create([item])
    return {"code": 0, "data": None, "message": "success"}


@router.put("/whitelist/{id}")
def update_whitelist(id: int, data: dict, current_user: dict = Depends(get_current_user)):
    """更新白名单项.

    采用删除旧记录 + 插入新记录的方式实现更新，
    保留原有 source 字段。
    """
    existing = WhitelistModel.get_by_id(id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="白名单项不存在",
        )
    WhitelistModel.delete_by_id(id)
    WhitelistModel.batch_create([
        {
            "category": data.get("category", existing.get("category", "path")),
            "pattern": data.get("pattern", existing.get("pattern", "")),
            "source": existing.get("source", "user"),
            "description": data.get("description", existing.get("description", "")),
            "enabled": data.get("enabled", True),
        }
    ])
    return {"code": 0, "data": None, "message": "success"}


@router.delete("/whitelist/{id}")
def delete_whitelist(id: int, current_user: dict = Depends(get_current_user)):
    """删除白名单项."""
    success = WhitelistModel.delete_by_id(id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="白名单项不存在",
        )
    return {"code": 0, "data": None, "message": "success"}
