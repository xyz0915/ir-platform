"""AI分析路由 — 完整重写：多Profile管理、异步任务、报告版本管理、审计日志、统计.

统一响应格式: {code: 0|1, data: any|null, message: str}
"""

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, Response

from app.database import get_connection
from app.models.ai_config import AiConfigProfile, AiConfig, AiPromptVersion
from app.models.ai_analysis import AiAnalysisReport
from app.models.ai_task import AiTask
from app.models.host import Host
from app.models.analysis import AnalysisResult
from app.schemas.ai import (
    AiConfigProfileCreate,
    AiConfigProfileUpdate,
    AiToggleRequest,
    AiChatRequest,
    AiChatResponse,
    CompareRequest,
    PromptOptimizeRequest,
    DispatchReadonlyRequest,
)
from app.services.auth_service import get_current_user
from app.services.ai_service import AiService
from app.services.ai_task_service import AiTaskService
from app.services.audit_service import AuditService
from app.services.dispatch_service import DispatchService
from app.services.pdf_export_service import PdfExportService
from app.services.token_stats_service import TokenStatsService

logger = logging.getLogger(__name__)
router = APIRouter()


# ================================================================
# 辅助函数
# ================================================================


def _mask_profile(profile: dict) -> dict:
    """对 Profile 中的 api_key 进行脱敏处理."""
    result = dict(profile)
    key = result.get("api_key", "")
    if key:
        result["api_key_masked"] = AiService.mask_api_key(key)
        del result["api_key"]
    else:
        result["api_key_masked"] = "****"
    return result


def _ok(data: Any = None, message: str = "success") -> dict:
    """构造成功响应."""
    return {"code": 0, "data": data, "message": message}


def _fail(message: str, data: Any = None) -> dict:
    """构造失败响应."""
    return {"code": 1, "data": data, "message": message}


# ================================================================
# Profile 管理（6端点）
# ================================================================


@router.get("/profiles")
def list_profiles(user: dict = Depends(get_current_user)):
    """获取所有 AI 配置 Profile 列表."""
    try:
        profiles = AiConfigProfile.list_all()
        active = AiConfigProfile.get_active()
        return _ok({
            "items": [_mask_profile(p) for p in profiles],
            "total": len(profiles),
            "active_id": active["id"] if active else None,
        })
    except Exception as e:
        logger.exception("list_profiles error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles")
def create_profile(data: AiConfigProfileCreate, user: dict = Depends(get_current_user)):
    """创建新的 AI 配置 Profile."""
    try:
        api_key = data.api_key or ""
        if api_key:
            api_key = AiService.encrypt_api_key(api_key)
        profile = AiConfigProfile.create(
            profile_name=data.profile_name,
            provider=data.provider,
            api_base_url=data.api_base_url,
            api_key=api_key,
            model_name=data.model_name,
            max_tokens=data.max_tokens,
            temperature=data.temperature,
            system_prompt=data.system_prompt,
        )
        return _ok(_mask_profile(profile), "Profile 创建成功")
    except Exception as e:
        logger.exception("create_profile error")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, data: AiConfigProfileUpdate, user: dict = Depends(get_current_user)):
    """更新指定的 AI 配置 Profile."""
    try:
        existing = AiConfigProfile.get_by_id(profile_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Profile {profile_id} 不存在")

        update_kwargs: dict[str, Any] = {}
        if data.profile_name is not None:
            update_kwargs["profile_name"] = data.profile_name
        if data.provider is not None:
            update_kwargs["provider"] = data.provider
        if data.api_base_url is not None:
            update_kwargs["api_base_url"] = data.api_base_url
        if data.api_key is not None and data.api_key != "":
            update_kwargs["api_key"] = AiService.encrypt_api_key(data.api_key)
        if data.model_name is not None:
            update_kwargs["model_name"] = data.model_name
        if data.max_tokens is not None:
            update_kwargs["max_tokens"] = data.max_tokens
        if data.temperature is not None:
            update_kwargs["temperature"] = data.temperature
        if data.system_prompt is not None:
            update_kwargs["system_prompt"] = data.system_prompt

        profile = AiConfigProfile.update(profile_id, **update_kwargs)
        return _ok(_mask_profile(profile), "Profile 更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_profile error")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(get_current_user)):
    """删除指定的 AI 配置 Profile."""
    try:
        profile = AiConfigProfile.get_by_id(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile {profile_id} 不存在")

        AiConfigProfile.delete(profile_id)
        return _ok(None, "Profile 已删除")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("delete_profile error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}/activate")
def activate_profile(profile_id: int, user: dict = Depends(get_current_user)):
    """将指定 Profile 设为活跃状态."""
    try:
        profile = AiConfigProfile.set_active(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile {profile_id} 不存在")
        return _ok(_mask_profile(profile), "Profile 已激活")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("activate_profile error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_connection(request: Request, user: dict = Depends(get_current_user)):
    """测试 AI 服务连接（直接传参方式）.

    优先使用请求体中的 profile_id 测试已保存的配置；
    也支持直接传入 api_base_url + api_key + model_name 进行临时测试。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 格式")

    profile_id = body.get("profile_id")
    api_base_url = body.get("api_base_url", "").strip()
    api_key_plain = body.get("api_key", "").strip()
    model_name = body.get("model_name", "gpt-4o").strip()

    # 如果指定了 profile_id，使用已保存的配置
    if profile_id is not None:
        result = AiConfigProfile.test_connection(int(profile_id))
        return _ok(result)

    # 否则使用直接传入的参数
    if not api_base_url:
        return _fail("API 地址不能为空")
    if not api_key_plain:
        return _fail("API Key 不能为空")

    try:
        api_base_url = api_base_url.rstrip("/")
        await AiService.call_llm(
            api_base_url=api_base_url,
            api_key=api_key_plain,
            model=model_name,
            system_prompt="ping",
            user_prompt="ping",
            max_tokens=1,
            temperature=0.0,
        )
        return _ok({"success": True, "message": "连接成功！API 服务可达",
                     "models": None}, "测试通过")
    except Exception as e:
        error_msg = str(e)
        if "ConnectError" in type(e).__name__ or "connect" in error_msg.lower():
            return _fail("无法连接 API 服务器，请检查地址和网络")
        if "401" in error_msg or "Unauthorized" in error_msg or "auth" in error_msg.lower():
            return _fail("认证失败（API Key 无效）")
        if "Timeout" in type(e).__name__ or "timeout" in error_msg.lower():
            return _fail("连接超时，请检查 API 地址")
        return _fail(f"连接测试失败: {error_msg[:200]}")


# ================================================================
# AI 分析（5端点）
# ================================================================


@router.post("/analyze/compare")
async def compare_hosts(
    data: CompareRequest,
    user: dict = Depends(get_current_user),
):
    """多主机对比分析 — 提交异步对比任务.

    对 2-5 台主机进行四维度（风险/威胁/攻击路径/处置建议）对比.
    返回 task_id，后续通过 SSE 流式获取结果.
    """
    try:
        from app.services.compare_service import CompareService

        result = CompareService.compare_hosts(data.host_ids)
        task = await result  # compare_hosts is async
        return _ok(task, "对比分析任务已提交")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("compare_hosts error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze/compare/{task_id}/stream")
async def stream_compare_events(task_id: int, user: dict = Depends(get_current_user)):
    """SSE 流式推送对比分析事件."""
    from app.services.compare_service import CompareService

    task = AiTask.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    async def event_generator():
        try:
            async for event in CompareService.stream_events(task_id):
                evt_type = event.get("event", "message")
                evt_data = event.get("data", event)
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type == "done":
                    break
        except asyncio.CancelledError:
            logger.info("Compare SSE stream cancelled for task %d", task_id)
        except Exception as e:
            logger.exception("Compare SSE stream error for task %d", task_id)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'message': 'stream ended'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/analyze/{host_id}")
async def submit_analysis(
    host_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """提交 AI 分析任务（异步）.

    Query params:
        masked_mode: 0=不脱敏, 1=脱敏（默认 1）

    返回 task_id 供后续查询.
    """
    masked_mode = 1
    mode = "standard"
    focus_area: Optional[str] = None
    base_report_id: Optional[int] = None
    audience: Optional[str] = None
    try:
        params = request.query_params
        if "masked_mode" in params:
            masked_mode = int(params["masked_mode"])
        if "mode" in params:
            mode = params["mode"] or "standard"
        if "focus_area" in params:
            focus_area = params["focus_area"] or None
        if "base_report_id" in params:
            base_report_id = int(params["base_report_id"])
        if "audience" in params:
            audience = params["audience"] or None
    except (ValueError, TypeError):
        pass

    # 校验 mode 合法性（含新增 overview / remediation）
    from app.shared.ai_constants import AIMode
    if mode not in AIMode.values():
        raise HTTPException(
            status_code=400,
            detail=f"非法 mode: {mode!r}，合法值：{AIMode.values()}",
        )

    try:
        task = await AiTaskService.submit(
            host_id=host_id,
            profile_id=None,
            masked_mode=bool(masked_mode),
            mode=mode,
            focus_area=focus_area,
            base_report_id=base_report_id,
            audience=audience,
        )
        return _ok({
            "task_id": task["id"],
            "host_id": host_id,
            "status": task["status"],
            "progress": task.get("progress", 0),
            "progress_message": task.get("progress_message", "任务已提交"),
            "created_at": task.get("created_at", ""),
            "mode": task.get("mode", mode),
            "focus_area": task.get("focus_area", focus_area),
            "base_report_id": task.get("base_report_id", base_report_id),
        }, "AI 分析任务已提交")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("submit_analysis error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/{host_id}/dispatch-readonly")
async def dispatch_readonly(
    host_id: int,
    data: DispatchReadonlyRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """R2-3 派发只读采集（绝不自动处置）.

    仅接受 ``auto_runnable=true`` 的只读采集命令；子进程执行 ``timeout=120s``，
    超时即中断；全程经审计；结果回填 ``ai_evidence_refills``。**不触发 AI 重算、
    绝不 kill / 隔离 / 改配**。

    返回 ``task_id`` 供前端轮询 ``GET /dispatch/{task_id}``。
    """
    host = Host.get_by_id(host_id)
    if not host:
        raise HTTPException(status_code=404, detail=f"主机 {host_id} 不存在")
    try:
        task = await DispatchService.dispatch_readonly(
            host_id=host_id,
            action_type=data.action_type,
            target=data.target,
            command_or_api=data.command_or_api,
            auto_runnable=data.auto_runnable,
            user=user,
        )
        return _ok({
            "task_id": task["task_id"],
            "host_id": host_id,
            "status": task["status"],
            "action_type": task["action_type"],
            "created_at": task["created_at"],
        }, "只读采集已派发")
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("dispatch_readonly error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dispatch/{task_id}")
def get_dispatch_status(task_id: str, user: dict = Depends(get_current_user)):
    """轮询只读派发任务状态（含采集证据）."""
    task = DispatchService.get_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"派发任务 {task_id} 不存在")
    return _ok(task)


@router.post("/dispatch/{task_id}/cancel")
def cancel_dispatch(task_id: str, user: dict = Depends(get_current_user)):
    """取消正在执行的只读派发（仅中断采集，绝不 kill/隔离主机）."""
    ok = DispatchService.cancel(task_id)
    if not ok:
        return _fail("任务不存在或已结束，无法取消")
    return _ok({"task_id": task_id, "status": "cancelled"}, "派发已取消")


@router.get("/tasks/{task_id}")
def get_task_status(task_id: int, user: dict = Depends(get_current_user)):
    """查询 AI 分析任务状态."""
    try:
        task = AiTaskService.get_status(task_id)
        return _ok({
            "id": task["id"],
            "host_id": task["host_id"],
            "profile_id": task.get("profile_id"),
            "status": task["status"],
            "progress": task.get("progress", 0),
            "progress_message": task.get("progress_message", ""),
            "report_id": task.get("report_id"),
            "error_message": task.get("error_message"),
            "masked_mode": task.get("masked_mode", 0),
            "created_at": task.get("created_at", ""),
            "updated_at": task.get("updated_at", ""),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_task_status error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/stream")
async def stream_task_events(task_id: int, user: dict = Depends(get_current_user)):
    """SSE 流式推送 AI 分析任务的事件."""
    # 确认任务存在
    task = AiTask.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    async def event_generator():
        try:
            async for event in AiTaskService.stream_events(task_id):
                evt_type = event.get("event", "message")
                evt_data = event.get("data", event)
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type == "done":
                    break
        except asyncio.CancelledError:
            logger.info("SSE stream cancelled for task %d", task_id)
        except Exception as e:
            logger.exception("SSE stream error for task %d", task_id)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'message': 'stream ended'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int, user: dict = Depends(get_current_user)):
    """取消正在执行或等待中的 AI 分析任务."""
    try:
        task = AiTaskService.cancel(task_id)
        return _ok({
            "task_id": task["id"],
            "status": task["status"],
            "message": "任务已取消",
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("cancel_task error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
def list_tasks(
    host_id: Optional[int] = Query(default=None, description="按主机ID筛选"),
    user: dict = Depends(get_current_user),
):
    """列出所有 AI 分析任务（支持按 host_id 筛选）."""
    try:
        if host_id is not None:
            tasks = AiTask.get_by_host(host_id, limit=100)
        else:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_tasks ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
                tasks = [dict(row) for row in rows]

        items = []
        for t in tasks:
            items.append({
                "id": t["id"],
                "host_id": t["host_id"],
                "profile_id": t.get("profile_id"),
                "status": t["status"],
                "progress": t.get("progress", 0),
                "progress_message": t.get("progress_message", ""),
                "report_id": t.get("report_id"),
                "error_message": t.get("error_message"),
                "masked_mode": t.get("masked_mode", 0),
                "created_at": t.get("created_at", ""),
                "updated_at": t.get("updated_at", ""),
                "started_at": t.get("started_at"),
                "completed_at": t.get("completed_at"),
            })
        return _ok({"items": items, "total": len(items)})
    except Exception as e:
        logger.exception("list_tasks error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# 报告（6端点）
# ================================================================


def _enrich_report(report: Optional[dict], host_id: int) -> Optional[dict]:
    """为 AI 报告补充主机信息和分析发现."""
    if not report:
        return None
    result = dict(report)

    # 补充主机信息
    host = Host.get_by_id(host_id)
    if host:
        result["hostname"] = host.get("hostname", "")
        result["ip_address"] = host.get("ip_address", "")
        result["os_type"] = host.get("os_type", "")

    # 补充分析发现概要
    analysis = AnalysisResult.get_by_host(host_id)
    if analysis:
        result["findings"] = {
            "risk_level": analysis.get("risk_level", ""),
            "risk_score": analysis.get("risk_score", 0),
            "total_findings": analysis.get("total_findings", 0),
            "summary": analysis.get("summary", ""),
        }

    # 解析 overview / remediation 的 ai_payload（任务②）
    ai_payload_raw = report.get("ai_payload")
    if ai_payload_raw:
        try:
            result["ai_payload"] = json.loads(ai_payload_raw)
        except (json.JSONDecodeError, TypeError):
            result["ai_payload"] = None

    # v1.3.0 作战化新列：解析为结构化对象返回前端（向后兼容旧库为空）
    for col in ("audience", "mitre_attack", "attack_chain_hits", "rare_high_signals"):
        raw = report.get(col)
        if isinstance(raw, str) and raw.strip():
            try:
                result[col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result[col] = raw
        else:
            result[col] = raw if raw is not None else None
    # v1.3.0 BugFix: 从 risk_assessment JSON 中提取 data_gaps 作为顶层字段
    # 便于前端 DataGapActionCard 直接取用，无需二次解析 risk_assessment
    ra_raw = report.get("risk_assessment")
    if isinstance(ra_raw, str) and ra_raw.strip():
        try:
            ra_parsed = json.loads(ra_raw)
            if isinstance(ra_parsed, dict) and "data_gaps" in ra_parsed:
                result["data_gaps"] = ra_parsed["data_gaps"]
        except (json.JSONDecodeError, TypeError):
            pass
    return result


@router.get("/report/{host_id}")
def get_ai_report(host_id: int, user: dict = Depends(get_current_user)):
    """获取主机最新的 AI 分析报告（向后兼容 + 自动补充分析发现）."""
    try:
        report = AiAnalysisReport.get_by_host(host_id)
        if not report:
            return _ok(None, "该主机尚未进行 AI 分析")
        enriched = _enrich_report(report, host_id)
        return _ok(enriched)
    except Exception as e:
        logger.exception("get_ai_report error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{host_id}/versions")
def list_report_versions(host_id: int, user: dict = Depends(get_current_user)):
    """获取主机的所有 AI 分析报告版本列表."""
    try:
        versions = AiAnalysisReport.list_versions(host_id)
        return _ok({"items": versions, "total": len(versions)})
    except Exception as e:
        logger.exception("list_report_versions error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{host_id}/versions/{version}")
def get_report_version(host_id: int, version: int, user: dict = Depends(get_current_user)):
    """获取主机指定版本的 AI 分析报告."""
    try:
        report = AiAnalysisReport.get_by_version(host_id, version)
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"主机 {host_id} 的版本 {version} 报告不存在",
            )
        enriched = _enrich_report(report, host_id)
        return _ok(enriched)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_report_version error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{host_id}/diff")
def diff_report_versions(
    host_id: int,
    v1: int = Query(..., description="版本号1"),
    v2: int = Query(..., description="版本号2"),
    user: dict = Depends(get_current_user),
):
    """对比两个版本的 AI 分析报告差异.

    返回逐字段差异列表: [{field, v1_content, v2_content}]
    """
    try:
        report1 = AiAnalysisReport.get_by_version(host_id, v1)
        report2 = AiAnalysisReport.get_by_version(host_id, v2)

        if not report1:
            raise HTTPException(status_code=404, detail=f"版本 {v1} 报告不存在")
        if not report2:
            raise HTTPException(status_code=404, detail=f"版本 {v2} 报告不存在")

        # 需要对比的字段
        compare_fields = [
            "risk_assessment",
            "threat_analysis",
            "timeline_analysis",
            "recommendations",
        ]
        diffs = []
        for field in compare_fields:
            c1 = report1.get(field, "") or ""
            c2 = report2.get(field, "") or ""
            if c1 != c2:
                diffs.append({
                    "field": field,
                    "v1_content": c1[:500],
                    "v2_content": c2[:500],
                })

        return _ok({
            "v1": v1,
            "v2": v2,
            "diffs": diffs,
            "changed_fields": len(diffs),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("diff_report_versions error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{host_id}/pdf")
async def export_report_pdf(host_id: int, user: dict = Depends(get_current_user)):
    """导出 AI 分析报告为 PDF."""
    try:
        pdf_bytes = PdfExportService.export(host_id)
        if pdf_bytes is None:
            raise HTTPException(status_code=500, detail="PDF 生成失败，请确认 WeasyPrint 已正确安装")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=ai_report_host_{host_id}.pdf",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_report_pdf error")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/report/{host_id}")
def delete_ai_report(host_id: int, user: dict = Depends(get_current_user)):
    """删除主机的所有 AI 分析报告."""
    try:
        AiAnalysisReport.delete_by_host(host_id)
        return _ok(None, "AI 分析报告已删除")
    except Exception as e:
        logger.exception("delete_ai_report error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# 审计日志（2端点）
# ================================================================


@router.get("/audit-logs")
def list_audit_logs(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    host_id: Optional[int] = Query(default=None, description="按主机ID筛选"),
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    user: dict = Depends(get_current_user),
):
    """分页查询审计日志."""
    try:
        result = AuditService.query_logs(
            page=page,
            page_size=page_size,
            host_id=host_id,
            status=status,
            days=90,
        )
        return _ok(result)
    except Exception as e:
        logger.exception("list_audit_logs error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit-logs/{log_id}")
def get_audit_log_detail(log_id: int, user: dict = Depends(get_current_user)):
    """获取单条审计日志详情."""
    try:
        log = AuditService.get_detail(log_id)
        return _ok(log)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_audit_log_detail error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# 统计（2端点）
# ================================================================


@router.get("/stats/tokens")
def get_token_stats(
    days: int = Query(default=30, ge=1, le=365, description="统计天数"),
    user: dict = Depends(get_current_user),
):
    """Token 消耗统计（按日期聚合）."""
    try:
        stats = TokenStatsService.get_daily_stats(days=days)
        return _ok({
            "items": stats,
            "days": days,
        })
    except Exception as e:
        logger.exception("get_token_stats error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/summary")
def get_stats_summary(user: dict = Depends(get_current_user)):
    """获取 AI 功能汇总统计卡片数据."""
    try:
        summary = TokenStatsService.get_summary()
        return _ok(summary)
    except Exception as e:
        logger.exception("get_stats_summary error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# 配置管理（向后兼容 — 委托给 Profile）
# ================================================================


@router.get("/config")
def get_ai_config(user: dict = Depends(get_current_user)):
    """获取当前活跃的 AI 配置（向后兼容，委托给 Profile）."""
    try:
        config = AiService.get_config()
        result = {
            "config": config if config else None,
            "provider_options": [
                {"value": "openai", "label": "OpenAI (ChatGPT/GPT-4)"},
                {"value": "azure", "label": "Azure OpenAI"},
                {"value": "anthropic", "label": "Anthropic (Claude)"},
                {"value": "ollama", "label": "Ollama (本地模型)", "api_base_url_hint": "http://localhost:11434/v1"},
                {"value": "deepseek", "label": "DeepSeek"},
                {"value": "zhipu", "label": "智谱 (GLM)"},
                {"value": "qwen", "label": "通义千问"},
                {"value": "moonshot", "label": "Moonshot (Kimi)"},
                {"value": "custom", "label": "自定义兼容接口"},
            ],
        }
        if not config:
            return _ok(result, "尚未配置 AI 参数")
        return _ok(result)
    except Exception as e:
        logger.exception("get_ai_config error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/provider-options")
def get_provider_options(user: dict = Depends(get_current_user)):
    """获取支持的 AI Provider 选项列表."""
    return _ok([
        {"value": "openai", "label": "OpenAI (ChatGPT/GPT-4)"},
        {"value": "azure", "label": "Azure OpenAI"},
        {"value": "anthropic", "label": "Anthropic (Claude)"},
        {"value": "ollama", "label": "Ollama (本地模型)", "api_base_url_hint": "http://localhost:11434/v1"},
        {"value": "deepseek", "label": "DeepSeek"},
        {"value": "zhipu", "label": "智谱 (GLM)"},
        {"value": "qwen", "label": "通义千问"},
        {"value": "moonshot", "label": "Moonshot (Kimi)"},
        {"value": "custom", "label": "自定义兼容接口"},
    ])


@router.post("/config")
def save_ai_config(data: dict, user: dict = Depends(get_current_user)):
    """保存 AI 配置（向后兼容，委托给 Profile）."""
    try:
        config = AiService.save_config(data)
        return _ok(config, "AI 配置已保存")
    except Exception as e:
        logger.exception("save_ai_config error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle")
def toggle_ai(data: AiToggleRequest, user: dict = Depends(get_current_user)):
    """开启/关闭 AI 功能（检查活跃 Profile 完整性）."""
    try:
        config = AiService.toggle_enabled(data.enabled)
        status_text = "已开启" if data.enabled == 1 else "已关闭"
        return _ok(config, f"AI 分析功能{status_text}")
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("toggle_ai error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# P2-01: 多轮对话
# ================================================================


@router.post("/analyze/{host_id}/chat")
async def chat_with_ai(
    host_id: int,
    data: AiChatRequest,
    user: dict = Depends(get_current_user),
):
    """多轮对话 — 带上下文的 AI 聊天.

    接受 message + conversation_id，返回 AI 回复。
    历史对话限制最近 5 轮（10 条消息）.
    """
    try:
        host = Host.get_by_id(host_id)
        if not host:
            raise HTTPException(status_code=404, detail=f"主机 {host_id} 不存在")

        # conversation_history 格式: [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}]
        history: list[dict] = []
        if data.conversation_id:
            # 尝试从最近的报告中获取对话历史（暂用简单方式）
            pass

        result = await AiService.chat_with_ai(
            host_id=host_id,
            message=data.message,
            conversation_history=history,
            mode=data.mode,
            focus_area=data.focus_area,
            base_report_id=data.base_report_id,
        )
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("chat_with_ai error")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# P2-06: 提示词自动优化
# ================================================================


@router.post("/prompt/optimize")
async def optimize_prompt(
    data: PromptOptimizeRequest,
    user: dict = Depends(get_current_user),
):
    """自动优化提示词 — 调用 LLM 基于反馈优化 system_prompt.

    优化结果保存到 ai_prompt_versions 表，最多保留 5 个历史版本.
    """
    try:
        from app.services.prompt_optimizer import PromptOptimizer

        result = await PromptOptimizer.optimize(
            current_prompt=data.prompt,
            feedback=data.feedback,
            profile_id=data.profile_id,
        )
        return _ok(result, "提示词优化完成")
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("optimize_prompt error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompt/versions/{profile_id}")
def list_prompt_versions(profile_id: int, user: dict = Depends(get_current_user)):
    """获取指定 Profile 的提示词历史版本列表."""
    try:
        profile = AiConfigProfile.get_by_id(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile {profile_id} 不存在")

        versions = AiPromptVersion.list_by_profile(profile_id, limit=5)
        items = [
            {
                "id": v["id"],
                "version": v["version"],
                "content": v.get("content", ""),
                "created_at": v.get("created_at", ""),
            }
            for v in versions
        ]
        return _ok({"items": items, "total": len(items)})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("list_prompt_versions error")
        raise HTTPException(status_code=500, detail=str(e))


