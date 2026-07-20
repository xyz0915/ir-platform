"""数据导入接口."""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.services.auth_service import get_current_user
from app.services.host_service import HostService
from app.services.import_service import ImportService
from app.models.import_record import ImportRecord

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/hosts/{host_id}/import")
async def import_agent_json(
    host_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """导入 Agent JSON 文件."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )

    file_content = await file.read()
    try:
        record = await asyncio.get_event_loop().run_in_executor(
            None,  # 默认线程池
            ImportService.import_json,
            host_id,
            file_content,
            file.filename or "upload.json",
        )
        return {"code": 0, "data": record, "message": "success"}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/hosts/{host_id}/import-records")
def list_import_records(
    host_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取主机的导入记录列表."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    records = ImportRecord.list_by_host(host_id)
    return {"code": 0, "data": records, "message": "success"}
