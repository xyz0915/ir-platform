"""规则覆盖率与质量看板 API（T-P1-3）."""

import logging

from fastapi import APIRouter, Depends

from app.services.attack_technique_service import AttackTechniqueService
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/rules/coverage")
def get_rules_coverage(
    current_user: dict = Depends(get_current_user),
):
    """获取规则覆盖率聚合数据.

    返回 ATT&CK 覆盖率、命中 Top 10、误报率、抑制比率等看板数据。
    """
    try:
        stats = AttackTechniqueService.get_coverage_stats()
        return {"code": 0, "data": stats, "message": "success"}
    except Exception as e:
        logger.error("获取覆盖率数据失败: %s", e)
        return {"code": -1, "data": None, "message": str(e)}
