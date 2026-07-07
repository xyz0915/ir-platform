"""Agent 下载接口."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.services.agent_service import AgentService
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/download/{os_type}")
def download_agent(
    os_type: str,
    current_user: dict = Depends(get_current_user),
):
    """下载对应平台的 Agent 二进制文件."""
    if os_type not in ("windows", "linux"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的平台类型，请选择 windows 或 linux",
        )

    file_path = AgentService.get_agent_file(os_type)
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 文件不存在，请先构建 {os_type} 版本 Agent",
        )

    filename = AgentService.get_agent_filename(os_type)
    media_type = "application/octet-stream"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )
