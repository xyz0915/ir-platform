"""规则抑制 API."""

import logging
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.models.rule_suppression import RuleSuppression

logger = logging.getLogger(__name__)
router = APIRouter()


class SuppressRequest(BaseModel):
    rule_name: str
    host_id: int = 0
    duration_days: int = 7
    reason: str = ""


class RemoveSuppressRequest(BaseModel):
    rule_name: str
    host_id: int = 0


@router.post("/api/rules/suppress")
def suppress_rule(req: SuppressRequest):
    ok = RuleSuppression.suppress(req.rule_name, req.host_id, req.duration_days, req.reason)
    return {"success": ok}


@router.get("/api/rules/suppress")
def list_suppressions(host_id: Optional[int] = Query(None)):
    items = RuleSuppression.list_suppressed(host_id)
    return {"success": True, "items": items}


@router.delete("/api/rules/suppress")
def remove_suppression(req: RemoveSuppressRequest):
    ok = RuleSuppression.remove(req.rule_name, req.host_id)
    return {"success": ok}
