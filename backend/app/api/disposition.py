from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.disposition import DispositionCreate
from app.services.disposition_service import add_disposition, get_dispositions
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/events", tags=["disposition"])


@router.post("/{event_id}/dispositions")
def create_disposition(
    event_id: str,
    body: DispositionCreate,
    current_user: dict = Depends(get_current_user),
):
    result = add_disposition(
        event_id,
        body.action,
        body.operator or current_user.get("username", ""),
        body.comment,
    )
    return {"code": 0, "data": result}


@router.get("/{event_id}/dispositions")
def list_dispositions(
    event_id: str,
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
):
    result = get_dispositions(event_id, limit, offset)
    return {"code": 0, "data": result}
