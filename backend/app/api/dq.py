"""数据质量监控 API（v2.1 DQMonitor 接口）.

端点:
  GET /api/dq/metrics         — 全局质量指标（含必填字段填充率）
  GET /api/dq/field-fill      — 指定主机必填字段填充率
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.services.auth_service import get_current_user
from app.services.dq_monitor import DQReconciler, check_field_fill, get_metrics

router = APIRouter()


@router.get("/metrics")
def dq_metrics(current_user: dict = Depends(get_current_user)):
    """全局数据质量指标（必填字段填充率等）。"""
    return {"code": 0, "data": get_metrics(), "message": "success"}


@router.get("/field-fill")
def dq_field_fill(
    host_id: int = Query(..., description="主机 ID"),
    current_user: dict = Depends(get_current_user),
):
    """指定主机的必填展示字段填充率。"""
    return {"code": 0, "data": check_field_fill(host_id), "message": "success"}


@router.get("/coverage")
def dq_coverage(
    host_id: int = Query(..., description="主机 ID"),
    current_user: dict = Depends(get_current_user),
):
    """原始数据覆盖率（已入表区块 / 总区块）。"""
    return {"code": 0, "data": DQReconciler.check_coverage(host_id), "message": "success"}


@router.get("/divergence")
def dq_divergence(
    host_id: int = Query(..., description="主机 ID"),
    current_user: dict = Depends(get_current_user),
):
    """AC vs CM 两端数据分歧检查。"""
    return {"code": 0, "data": DQReconciler.check_divergence(host_id), "message": "success"}


@router.get("/reconcile")
def dq_reconcile(
    host_id: int = Query(..., description="主机 ID"),
    current_user: dict = Depends(get_current_user),
):
    """触发全量对账：覆盖率 + 分歧 + 字段填充率。"""
    return {
        "code": 0,
        "data": {
            "coverage": DQReconciler.check_coverage(host_id),
            "divergence": DQReconciler.check_divergence(host_id),
            "field_fill": DQReconciler.check_field_fill(host_id),
        },
        "message": "success",
    }
