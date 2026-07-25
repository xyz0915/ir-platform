"""护栏门禁 API — F8 运行时护栏（§3，P0）.

独立模块，严禁复用 /api/policies（检测策略语义不同，见 §3.4）。
注册：app.include_router(agent_guardrails.router, prefix="/api/agent-guardrails")。

端点：
  GET    /policies            策略列表
  POST   /policies            新增策略
  PUT    /policies/{id}       更新策略
  DELETE /policies/{id}       删除策略
  POST   /evaluate            计算护栏结果（记 Hit）
  GET    /hits                命中记录（M1 护栏拦截数）
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.models.guardrail import GuardrailHit, GuardrailPolicy
from app.services.auth_service import get_current_user
from app.services.guardrail.evaluator import GuardrailEvaluator

logger = logging.getLogger(__name__)
router = APIRouter()


class PolicyCreate(BaseModel):
    """新增策略请求体。"""
    name: str
    action_pattern: str
    whitelist: list[str] = []
    risk_level: str = "medium"
    require_confirm: bool = False
    rollback_plan: str = ""
    enabled: bool = True


class PolicyUpdate(BaseModel):
    """更新策略请求体（全可选）。"""
    name: Optional[str] = None
    action_pattern: Optional[str] = None
    whitelist: Optional[list[str]] = None
    risk_level: Optional[str] = None
    require_confirm: Optional[bool] = None
    rollback_plan: Optional[str] = None
    enabled: Optional[bool] = None


class EvaluateRequest(BaseModel):
    """evaluate 请求体。"""
    action: str
    context: dict = {}


@router.get("/policies")
def list_policies(user: dict = Depends(get_current_user)):
    """获取全部护栏策略。"""
    return {"code": 0, "data": GuardrailPolicy.get_all(), "message": "success"}


@router.post("/policies")
def create_policy(data: PolicyCreate, user: dict = Depends(get_current_user)):
    """新增护栏策略。"""
    try:
        policy = GuardrailPolicy.create(
            name=data.name,
            action_pattern=data.action_pattern,
            whitelist=data.whitelist,
            risk_level=data.risk_level,
            require_confirm=data.require_confirm,
            rollback_plan=data.rollback_plan,
            enabled=data.enabled,
        )
        return {"code": 0, "data": policy, "message": "策略已创建"}
    except Exception as exc:
        logger.exception("create_guardrail_policy error")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: str, data: PolicyUpdate, user: dict = Depends(get_current_user)
):
    """更新护栏策略。"""
    policy = GuardrailPolicy.update(
        policy_id,
        name=data.name,
        action_pattern=data.action_pattern,
        whitelist=data.whitelist,
        risk_level=data.risk_level,
        require_confirm=data.require_confirm,
        rollback_plan=data.rollback_plan,
        enabled=data.enabled,
    )
    if not policy:
        raise HTTPException(status_code=404, detail=f"策略 {policy_id} 不存在")
    return {"code": 0, "data": policy, "message": "策略已更新"}


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: str, user: dict = Depends(get_current_user)):
    """删除护栏策略。"""
    ok = GuardrailPolicy.delete(policy_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"策略 {policy_id} 不存在")
    return {"code": 0, "data": None, "message": "策略已删除"}


@router.post("/evaluate")
def evaluate(data: EvaluateRequest, user: dict = Depends(get_current_user)):
    """计算护栏结果（命中即记 GuardrailHit）。"""
    try:
        result = GuardrailEvaluator.evaluate(data.action, data.context)
        return {"code": 0, "data": result, "message": "success"}
    except Exception as exc:
        logger.exception("guardrail_evaluate error")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/hits")
def list_hits(user: dict = Depends(get_current_user)):
    """获取护栏命中记录（供 M1 护栏拦截数聚合）。"""
    return {"code": 0, "data": GuardrailHit.list_all(), "message": "success"}
