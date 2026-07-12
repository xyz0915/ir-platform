"""实时告警管理 API."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.models.alert import Alert
from app.services.alert_ws import alert_ws_manager
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/alerts")
def list_alerts(
    host_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    rule_name: Optional[str] = Query(None),
    case_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
):
    """列出告警（支持多条件筛选）. """
    items = Alert.list(host_id=host_id, severity=severity, status=status,
                       rule_name=rule_name, case_id=case_id,
                       date_from=date_from, date_to=date_to, search=search,
                       limit=limit, offset=offset)
    return {"success": True, "data": items}


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, current_user: dict = Depends(get_current_user)):
    alert = Alert.get_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    return {"success": True, "data": alert}


@router.put("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, current_user: dict = Depends(get_current_user)):
    ok = Alert.acknowledge(alert_id, user=current_user.get("username", "system"))
    return {"success": ok}


@router.put("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, current_user: dict = Depends(get_current_user)):
    ok = Alert.resolve(alert_id)
    return {"success": ok}


@router.put("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, reason: str = "", current_user: dict = Depends(get_current_user)):
    ok = Alert.dismiss(alert_id, reason)
    return {"success": ok}


@router.get("/alerts/stats/summary")
def alert_stats(
    host_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    rule_name: Optional[str] = Query(None),
    case_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": Alert.get_stats(
        host_id=host_id, severity=severity, status=status,
        rule_name=rule_name, case_id=case_id,
        date_from=date_from, date_to=date_to, search=search,
    )}


@router.get("/alerts/stats/trend")
def alert_trend(hours: int = 24, current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": Alert.get_trend(hours=hours)}


@router.websocket("/ws/alerts")
async def alert_websocket(websocket: WebSocket):
    """实时告警推送 WebSocket."""
    # 从查询参数取 token
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001)
        return
    # 简单 JWT 解码获取 user_id（生产环境用正式认证）
    import jwt
    from app.config import settings
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id", 0)
    except Exception:
        await websocket.close(code=4001)
        return

    await alert_ws_manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        alert_ws_manager.disconnect(user_id, websocket)
    except Exception:
        alert_ws_manager.disconnect(user_id, websocket)
