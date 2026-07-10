"""差分基线 API（v1.3.0 支柱③ R3-1）— 上传/读取/删除主机基线.

存储 v1.2.0 --save-baseline 产物（known_items / diff_new / collection_health），
供 PromptBuilder 注入与解析层 R3-3 降噪使用。仅落库与读取，不涉及 AI 重算。
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.models.agent_baseline import AgentBaseline
from app.models.host import Host
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _ok(data: Any = None, message: str = "success") -> dict:
    return {"code": 0, "data": data, "message": message}


def _fail(message: str, data: Any = None) -> dict:
    return {"code": 1, "data": data, "message": message}


@router.post("/{host_id}")
def upload_baseline(
    host_id: int,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """上传/覆盖主机差分基线（R3-1）.

    body: { "baseline_json": {...}, "source": "uploaded"|"agent_auto", "note": "..." }
    """
    try:
        host = Host.get_by_id(host_id)
        if not host:
            raise HTTPException(status_code=404, detail=f"主机 {host_id} 不存在")

        baseline_json = payload.get("baseline_json")
        if not isinstance(baseline_json, dict) or not baseline_json:
            raise HTTPException(status_code=400, detail="baseline_json 必须为非空对象")

        source = payload.get("source", "uploaded")
        note = payload.get("note")
        rec = AgentBaseline.create(
            host_id=host_id,
            baseline_json=baseline_json,
            source=source,
            note=note,
        )
        return _ok(rec, "基线已保存")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("upload_baseline error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{host_id}")
def read_baseline(host_id: int, user: dict = Depends(get_current_user)):
    """读取主机最新一条基线（R3-1 读取接口）."""
    try:
        rec = AgentBaseline.get_latest_by_host(host_id)
        if not rec:
            return _ok(None, "该主机暂无基线")
        return _ok(rec)
    except Exception as e:
        logger.exception("read_baseline error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{host_id}/list")
def list_baselines(host_id: int, user: dict = Depends(get_current_user)):
    """列出主机的所有基线记录."""
    try:
        items = AgentBaseline.list_by_host(host_id)
        return _ok({"items": items, "total": len(items)})
    except Exception as e:
        logger.exception("list_baselines error")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{baseline_id}")
def delete_baseline(baseline_id: int, user: dict = Depends(get_current_user)):
    """删除指定基线记录."""
    try:
        AgentBaseline.delete(baseline_id)
        return _ok(None, "基线已删除")
    except Exception as e:
        logger.exception("delete_baseline error")
        raise HTTPException(status_code=500, detail=str(e))
