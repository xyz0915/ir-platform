"""AI分析路由 — AI配置管理、一键分析、报告查看."""

import logging

from fastapi import APIRouter, Depends

from app.schemas.ai import AiConfigCreate, AiToggleRequest, AiAnalysisResponse
from app.services.auth_service import get_current_user
from app.services.ai_service import AiService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config")
def get_ai_config(user: dict = Depends(get_current_user)):
    """获取AI配置（API Key脱敏）."""
    config = AiService.get_config()
    if not config:
        return {"code": 0, "data": None, "message": "尚未配置AI参数"}
    return {"code": 0, "data": config, "message": "success"}


@router.post("/config")
def save_ai_config(data: dict, user: dict = Depends(get_current_user)):
    """保存AI配置."""
    validated = AiConfigCreate.model_validate(data)
    config = AiService.save_config(validated.model_dump())
    return {"code": 0, "data": config, "message": "AI配置已保存"}


@router.post("/toggle")
def toggle_ai(data: AiToggleRequest, user: dict = Depends(get_current_user)):
    """开启/关闭AI功能.

    开启时会检查配置完整性，防止误操作导致数据泄露.
    """
    try:
        config = AiService.toggle_enabled(data.enabled)
        status = "开启" if data.enabled == 1 else "关闭"
        return {"code": 0, "data": config, "message": f"AI分析功能已{status}"}
    except ValueError as e:
        return {"code": 1, "data": None, "message": str(e)}


@router.post("/analyze/{host_id}")
async def ai_analyze(host_id: int, user: dict = Depends(get_current_user)):
    """一键AI分析 — 调用大模型对主机数据进行深度分析.

    注意: AI分析默认关闭，需手动开启后才能调用。
    开启AI意味着将主机取证数据发送至外部AI服务，请确保授权合规。
    """
    try:
        report = await AiService.analyze_with_ai(host_id)
        return {"code": 0, "data": report, "message": "AI分析完成"}
    except ValueError as e:
        return {"code": 1, "data": None, "message": str(e)}


@router.get("/report/{host_id}")
def get_ai_report(host_id: int, user: dict = Depends(get_current_user)):
    """获取主机的AI分析报告."""
    report = AiService.get_report(host_id)
    if not report:
        return {"code": 0, "data": None, "message": "该主机尚未进行AI分析"}
    return {"code": 0, "data": report, "message": "success"}


@router.delete("/report/{host_id}")
def delete_ai_report(host_id: int, user: dict = Depends(get_current_user)):
    """删除主机的AI分析报告."""
    AiService.delete_report(host_id)
    return {"code": 0, "data": None, "message": "AI分析报告已删除"}
