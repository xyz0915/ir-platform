"""AI 异步任务管理服务.

管理 AI 分析任务的异步执行、进度跟踪、流式事件推送和取消操作.
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from app.models.ai_task import AiTask
from app.models.ai_analysis import AiAnalysisReport
from app.models.ai_config import AiConfigProfile, AiConfig
from app.models.host import Host
from app.shared.ai_constants import TaskStatus
from app.shared.ai_error_mapping import map_http_error
from app.services.prompt_builder import PromptBuilder
from app.services.audit_service import AuditService
from app.services.input_quality_service import InputQualityService
from app.services.knowledge_retriever import KnowledgeRetriever
from app.services.explainability_service import ExplainabilityService

logger = logging.getLogger(__name__)


class AiTaskService:
    """AI 异步分析任务服务.

    管理任务的完整生命周期：提交 → 执行 → 状态查询 → 流式推送 → 取消.

    内部维护两个进程级字典：
    - _task_streams: task_id → asyncio.Queue，用于 SSE 流式推送
    - _cancel_flags: task_id → asyncio.Event，用于取消控制
    """

    _task_streams: dict[str, asyncio.Queue] = {}
    _cancel_flags: dict[str, asyncio.Event] = {}

    @classmethod
    async def submit(
        cls,
        host_id: int,
        profile_id: Optional[int] = None,
        masked_mode: bool = False,
        mode: str = "standard",
        focus_area: Optional[str] = None,
        base_report_id: Optional[int] = None,
    ) -> dict:
        """提交 AI 分析任务并启动后台执行.

        Args:
            host_id: 主机 ID.
            profile_id: AI 配置 Profile ID（None 则使用激活配置）.
            masked_mode: 是否启用数据脱敏.

        Returns:
            任务字典（含 task_id 和初始状态）.

        Raises:
            ValueError: 该主机已有运行中的 AI 分析任务.
        """
        # 检查主机是否存在
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")

        # 检查是否已有运行中的任务
        existing = AiTask.get_running_by_host(host_id)
        if existing:
            raise ValueError("该主机正在进行AI分析，请等待完成后再提交")

        # 创建任务记录
        masked_int = 1 if masked_mode else 0
        task = AiTask.create(
            host_id=host_id,
            profile_id=profile_id,
            masked_mode=masked_int,
            mode=mode,
            focus_area=focus_area,
            base_report_id=base_report_id,
        )
        task_id_str = str(task["id"])
        logger.info("AI task %s created for host %d (mode=%s, focus_area=%s)", task_id_str, host_id, mode, focus_area)

        # 创建流队列和取消标志
        cls._task_streams[task_id_str] = asyncio.Queue()
        cls._cancel_flags[task_id_str] = asyncio.Event()

        # 启动后台执行
        asyncio.create_task(cls._execute_task(task_id=task["id"]))

        return task

    @staticmethod
    def _map_http_error(e: httpx.HTTPStatusError) -> str:
        """将 httpx.HTTPStatusError 映射为面向用户的中文友好提示.

        委托给共享模块 ``app.shared.ai_error_mapping.map_http_error``，
        保持类接口以便调用方与测试使用。

        Args:
            e: httpx 抛出的 HTTPStatusError.

        Returns:
            中文友好提示字符串.
        """
        return map_http_error(e)

    @classmethod
    async def _execute_task(cls, task_id: int) -> None:
        """后台执行 AI 分析任务（核心流程）.

        步骤：
        1. 更新状态 running(10%) — 组装数据
        2. 调用 PromptBuilder.build() 构建 prompts
        3. 更新状态 running(40%) — 调用 AI
        4. 流式调用 LLM，推送 chunk 到队列
        5. 解析 JSON 回复
        6. 保存 AiAnalysisReport
        7. 写入审计日志
        8. 更新状态 completed(100%) 或 failed

        Args:
            task_id: 任务 ID.
        """
        task_id_str = str(task_id)
        cancel_event = cls._cancel_flags.get(task_id_str)
        queue = cls._task_streams.get(task_id_str)

        start_time = time.time()
        model_name = ""
        profile_name = ""
        profile_id_val: Optional[int] = None
        host_id: int = 0
        host_name = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            # 检查取消
            if cancel_event and cancel_event.is_set():
                await cls._fail_task(task_id, "任务已被用户取消", TaskStatus.CANCELLED)
                return

            # 获取任务信息
            task = AiTask.get_by_id(task_id)
            if not task:
                logger.error("Task %d not found during execution", task_id)
                return

            host_id = task["host_id"]
            masked_mode = bool(task.get("masked_mode", 0))
            req_profile_id = task.get("profile_id")

            # 获取主机信息
            host = Host.get_by_id(host_id)
            if host:
                host_name = host.get("hostname", "")

            # 获取 AI 配置
            if req_profile_id:
                profile = AiConfigProfile.get_by_id(req_profile_id)
            else:
                profile = AiConfigProfile.get_active()

            if not profile:
                raise ValueError("未找到有效的AI配置，请先在设置中配置并激活")

            profile_id_val = profile["id"]
            profile_name = profile.get("profile_name", "")
            model_name = profile.get("model_name", "gpt-4o")

            # --- 阶段1: 组装数据 (10%) ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.RUNNING.value,
                progress=10,
                progress_message="正在组装分析数据...",
            )
            await cls._push_event(task_id_str, "progress", {
                "progress": 10,
                "message": "正在组装分析数据...",
                "stage": "assembling",
            })

            if cancel_event and cancel_event.is_set():
                await cls._fail_task(task_id, "任务已被用户取消", TaskStatus.CANCELLED)
                return

            # 构建 prompts
            # --- 子阶段: building (20%) ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.RUNNING.value,
                progress=20,
                progress_message="正在构建分析提示词...",
            )
            await cls._push_event(task_id_str, "progress", {
                "progress": 20,
                "message": "正在构建分析提示词...",
                "stage": "building",
            })

            mode = task.get("mode", "standard") if isinstance(task, dict) else "standard"
            focus_area = task.get("focus_area") if isinstance(task, dict) else None
            base_report_id = task.get("base_report_id") if isinstance(task, dict) else None

            if mode == "module" and focus_area:
                # 模块化分析：只发送该模块专属数据
                logger.info(
                    "Building module prompt for host=%d, module=%s",
                    host_id, focus_area,
                )
                prompts = PromptBuilder.build_module(
                    host_id=host_id,
                    module_type=focus_area,
                    masked=masked_mode,
                )
            elif mode == "overview":
                prompts = PromptBuilder.build_overview(host_id=host_id, masked=masked_mode)
            elif mode == "remediation":
                prompts = PromptBuilder.build_remediation(host_id=host_id, masked=masked_mode)
            else:
                prompts = PromptBuilder.build(host_id=host_id, masked=masked_mode)
            system_prompt = prompts["system_prompt"]
            user_prompt = prompts["user_prompt"]

            # --- 阶段2: 调用 AI (40%) ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.RUNNING.value,
                progress=40,
                progress_message="正在调用AI模型进行分析...",
            )
            await cls._push_event(task_id_str, "progress", {
                "progress": 40,
                "message": "正在调用AI模型进行分析...",
                "stage": "calling",
            })

            if cancel_event and cancel_event.is_set():
                await cls._fail_task(task_id, "任务已被用户取消", TaskStatus.CANCELLED)
                return

            # 解密 API Key
            from app.services.ai_service import AiService

            api_key = AiService.decrypt_api_key(profile["api_key"])
            api_base_url = profile["api_base_url"]
            max_tokens = profile.get("max_tokens", 4096)
            temperature = profile.get("temperature", 0.3)

            # 流式调用 LLM
            full_content = ""
            usage_info: dict = {}
            chunk_count = 0

            try:
                if mode == "deep_dive":
                    deep_context = AiService._build_deep_dive_context(
                        host_id=host_id,
                        mode=mode,
                        focus_area=focus_area,
                        base_report_id=base_report_id,
                    )
                    if deep_context:
                        system_prompt = f"{system_prompt}\n\n{deep_context}"

                async for chunk_data in AiService.call_llm_stream(
                    api_base_url=api_base_url,
                    api_key=api_key,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    if cancel_event and cancel_event.is_set():
                        await cls._fail_task(task_id, "任务已被用户取消", TaskStatus.CANCELLED)
                        return

                    content = chunk_data.get("content", "")
                    if content:
                        full_content += content
                        chunk_count += 1

                    # 推送 content chunk
                    await cls._push_event(task_id_str, "content", {
                        "content": content,
                        "chunk_index": chunk_count,
                    })

                    # usage 信息通常在最后一个 chunk
                    if "usage" in chunk_data:
                        usage_info = chunk_data["usage"]

            except Exception as e:
                # LLM 调用失败，但仍可能保存部分内容
                logger.error("LLM stream failed for task %d: %s", task_id, str(e))
                raise

            # --- 阶段3: 解析回复 (70%) ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.RUNNING.value,
                progress=70,
                progress_message="正在解析AI回复...",
            )
            await cls._push_event(task_id_str, "progress", {
                "progress": 70,
                "message": "正在解析AI回复...",
                "stage": "parsing",
            })

            # --- 阶段4: 保存报告 (80%) ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.RUNNING.value,
                progress=80,
                progress_message="正在保存分析报告...",
            )
            await cls._push_event(task_id_str, "progress", {
                "progress": 80,
                "message": "正在保存分析报告...",
                "stage": "saving",
            })

            # 解析 JSON 回复并做结构化兜底增强
            parsed = cls._parse_json_response(full_content)
            host_obj = Host.get_by_id(host_id)
            case_id = host_obj.get("case_id", 0) if host_obj else 0

            # Token 统计
            prompt_tokens = usage_info.get("prompt_tokens", 0)
            completion_tokens = usage_info.get("completion_tokens", 0)
            total_tokens = usage_info.get("total_tokens", 0)

            # ── overview / remediation 专属报告（任务②）──────────────
            if mode in ("overview", "remediation"):
                ai_payload: dict = {"mode": mode, "payload": parsed}
                if mode == "overview":
                    ai_payload["story_line"] = parsed.get("story_line", "")
                    ai_payload["key_events"] = parsed.get("key_events", [])
                else:
                    ai_payload["remediation_scripts"] = parsed.get("remediation_scripts", [])
                report = AiAnalysisReport.create(
                    host_id=host_id,
                    case_id=case_id,
                    risk_assessment=json.dumps({}),
                    threat_analysis=json.dumps({}),
                    timeline_analysis=json.dumps({}),
                    recommendations=json.dumps({}),
                    raw_response=full_content,
                    model_used=model_name,
                    tokens_used=total_tokens,
                    profile_id=profile_id_val,
                    masked_mode=1 if masked_mode else 0,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    analysis_type=mode,
                    module_type=None,
                    ai_payload=json.dumps(ai_payload, ensure_ascii=False),
                )
                logger.info(
                    "AI task %d 生成 %s 报告: report_id=%s", task_id, mode, report.get("id"),
                )
            else:
                # ── 标准 / 深挖 / 模块报告（既有逻辑）────────────────
                tiered_data = PromptBuilder._fetch_tiered_data(host_id)
                quality_context = InputQualityService.evaluate(tiered_data)
                structured_knowledge = KnowledgeRetriever.retrieve(
                    tiered_data,
                    limit=5,
                    structured=True,
                )
                # 记录检索模式：区分向量检索命中与关键词降级
                if structured_knowledge:
                    sources = set(item.get("source", "unknown") for item in structured_knowledge)
                    logger.info(
                        "Knowledge retrieval for task %d: %d items, sources=%s",
                        task_id, len(structured_knowledge), sources,
                    )
                else:
                    logger.warning(
                        "Knowledge retrieval for task %d: returned empty results",
                        task_id,
                    )
                explainability = ExplainabilityService.build_evidence_trace(
                    parsed_sections=parsed,
                    knowledge_items=structured_knowledge,
                    tiered_data=tiered_data,
                )

                risk_assessment = ExplainabilityService.normalize_section(parsed.get("risk_assessment", {}))
                threat_analysis = ExplainabilityService.normalize_section(parsed.get("threat_analysis", {}))
                timeline_analysis = ExplainabilityService.ensure_structured_timeline(
                    ExplainabilityService.normalize_section(parsed.get("timeline_analysis", {})),
                    tiered_data,
                )
                recommendations = ExplainabilityService.normalize_section(parsed.get("recommendations", {}))

                risk_assessment.setdefault("risk_level", tiered_data.get("analysis_result", {}).get("risk_level", "待确认"))
                risk_assessment.setdefault("risk_score", tiered_data.get("analysis_result", {}).get("risk_score", 0))
                risk_assessment["input_quality"] = quality_context["input_quality"]
                risk_assessment["coverage_gaps"] = quality_context["coverage_gaps"]
                risk_assessment["miss_risk"] = quality_context["miss_risk"]
                risk_assessment["evidence_insufficiency"] = quality_context["evidence_insufficiency"]

                threat_analysis["evidence_trace"] = explainability["evidence_trace"]
                recommendations["input_suggestions"] = quality_context["input_suggestions"]
                recommendations["recommended_questions"] = explainability["recommended_questions"]

                # 保存 AiAnalysisReport
                report = AiAnalysisReport.create(
                    host_id=host_id,
                    case_id=case_id,
                    risk_assessment=json.dumps(risk_assessment, ensure_ascii=False),
                    threat_analysis=json.dumps(threat_analysis, ensure_ascii=False),
                    timeline_analysis=json.dumps(timeline_analysis, ensure_ascii=False),
                    recommendations=json.dumps(recommendations, ensure_ascii=False),
                    raw_response=full_content,
                    model_used=model_name,
                    tokens_used=total_tokens,
                    profile_id=profile_id_val,
                    masked_mode=1 if masked_mode else 0,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    analysis_type="module" if (mode == "module" and focus_area) else "full",
                    module_type=focus_area if (mode == "module" and focus_area) else None,
                )

            # --- 阶段4: 审计日志 (90%) ---
            latency_ms = int((time.time() - start_time) * 1000)
            AuditService.log_call(
                host_id=host_id,
                host_name=host_name,
                profile_id=profile_id_val,
                profile_name=profile_name,
                model_name=model_name,
                status="success",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                masked_mode=1 if masked_mode else 0,
            )

            # --- 完成 ---
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.COMPLETED.value,
                progress=100,
                progress_message="分析完成",
                report_id=report["id"],
            )
            await cls._push_event(task_id_str, "complete", {
                "progress": 100,
                "message": "分析完成",
                "report_id": report["id"],
                "report": report,
            })
            logger.info(
                "AI task %d completed: model=%s, tokens=%d, latency=%dms",
                task_id, model_name, total_tokens, latency_ms,
            )

        except httpx.HTTPStatusError as e:
            # AI 服务商返回非 2xx（如 DeepSeek 402 Payment Required），
            # 转换为中文友好提示，避免把原始 HTTP 错误文本透传给前端。
            latency_ms = int((time.time() - start_time) * 1000)
            friendly_msg = cls._map_http_error(e)
            status_code = e.response.status_code
            logger.error(
                "AI task %d failed (HTTP %d): %s",
                task_id, status_code, friendly_msg,
            )

            # 更新任务为失败（友好提示）
            await cls._fail_task(task_id, friendly_msg, TaskStatus.FAILED)

            # 写入失败审计日志（失败原因使用友好提示）
            try:
                AuditService.log_call(
                    host_id=host_id,
                    host_name=host_name,
                    profile_id=profile_id_val,
                    profile_name=profile_name,
                    model_name=model_name,
                    status="failed",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    masked_mode=1 if (task and task.get("masked_mode")) else 0,
                    error_message=friendly_msg,
                )
            except Exception:
                logger.exception("Failed to write audit log for failed task %d", task_id)

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.exception("AI task %d failed: %s", task_id, error_msg)

            # 更新任务为失败
            await cls._fail_task(task_id, error_msg, TaskStatus.FAILED)

            # 写入失败审计日志
            try:
                AuditService.log_call(
                    host_id=host_id,
                    host_name=host_name,
                    profile_id=profile_id_val,
                    profile_name=profile_name,
                    model_name=model_name,
                    status="failed",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    masked_mode=1 if (task and task.get("masked_mode")) else 0,
                    error_message=error_msg,
                )
            except Exception:
                logger.exception("Failed to write audit log for failed task %d", task_id)

        finally:
            # 推送 done 事件通知 SSE 消费者
            await cls._push_event(task_id_str, "done", {"message": "stream ended"})
            # 延迟清理，确保 SSE 消费者有时间读取 done 事件
            # cleanup_task 仅移除 dict 中的引用，SSE 消费者仍持有的 queue 对象不会被回收
            await asyncio.sleep(1.0)
            cls.cleanup_task(task_id)
            logger.info("Task %d resources cleaned up", task_id)

    @classmethod
    async def _fail_task(cls, task_id: int, error_message: str, status: TaskStatus) -> None:
        """标记任务为失败/取消."""
        AiTask.update_status(
            task_id=task_id,
            status=status.value,
            progress_message=error_message,
            error_message=error_message,
        )
        await cls._push_event(str(task_id), "error", {
            "message": error_message,
            "status": status.value,
        })

    @classmethod
    async def _push_event(cls, task_id_str: str, event_type: str, data: dict) -> None:
        """推送事件到指定任务的流队列."""
        queue = cls._task_streams.get(task_id_str)
        if queue:
            try:
                queue.put_nowait({"event": event_type, "data": data})
            except asyncio.QueueFull:
                logger.warning("Event queue full for task %s", task_id_str)

    @staticmethod
    def get_status(task_id: int) -> dict:
        """查询任务状态.

        Args:
            task_id: 任务 ID.

        Returns:
            任务状态字典.

        Raises:
            ValueError: 任务不存在.
        """
        task = AiTask.get_by_id(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        return dict(task)

    @classmethod
    async def stream_events(cls, task_id: int) -> AsyncGenerator[dict, None]:
        """流式事件生成器 — 用于 SSE 推送.

        从任务队列中持续 yield 事件，直到收到 "done" 事件.
        支持取消检测.

        Args:
            task_id: 任务 ID.

        Yields:
            事件字典 {"event": str, "data": dict}.
        """
        task_id_str = str(task_id)
        queue = cls._task_streams.get(task_id_str)

        if queue is None:
            # 任务可能已经完成，直接检查状态
            task = AiTask.get_by_id(task_id)
            if task:
                if task["status"] == TaskStatus.COMPLETED.value:
                    yield {"event": "complete", "data": {
                        "progress": 100,
                        "message": "分析完成",
                        "report_id": task.get("report_id"),
                    }}
                elif task["status"] == TaskStatus.FAILED.value:
                    yield {"event": "error", "data": {
                        "message": task.get("error_message", "分析失败"),
                        "status": TaskStatus.FAILED.value,
                    }}
                elif task["status"] == TaskStatus.CANCELLED.value:
                    yield {"event": "error", "data": {
                        "message": "任务已被取消",
                        "status": TaskStatus.CANCELLED.value,
                    }}
            yield {"event": "done", "data": {"message": "stream ended"}}
            return

        cancel_event = cls._cancel_flags.get(task_id_str)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
                if event["event"] == "done":
                    break
            except asyncio.TimeoutError:
                # 检查是否已取消
                if cancel_event and cancel_event.is_set():
                    yield {"event": "error", "data": {
                        "message": "任务已被取消",
                        "status": TaskStatus.CANCELLED.value,
                    }}
                    yield {"event": "done", "data": {"message": "stream ended"}}
                    break
                # 发送心跳
                yield {"event": "heartbeat", "data": {"timestamp": time.time()}}

    @classmethod
    def cancel(cls, task_id: int) -> dict:
        """取消正在执行的 AI 分析任务.

        Args:
            task_id: 任务 ID.

        Returns:
            更新后的任务字典.

        Raises:
            ValueError: 任务不存在或状态不可取消.
        """
        task_id_str = str(task_id)

        # 设置取消标志
        cancel_event = cls._cancel_flags.get(task_id_str)
        if cancel_event:
            cancel_event.set()
            logger.info("Cancel flag set for task %d", task_id)

        # 更新数据库状态
        try:
            task = AiTask.cancel(task_id)
        except ValueError:
            # 任务可能已经不在 pending/running 状态
            task = AiTask.get_by_id(task_id)
            if not task:
                raise ValueError(f"任务 {task_id} 不存在")

        logger.info("Task %d cancelled", task_id)
        return task

    @classmethod
    def cleanup_task(cls, task_id: int) -> None:
        """清理任务的流队列和取消标志（任务完成后调用）.

        Args:
            task_id: 任务 ID.
        """
        task_id_str = str(task_id)
        cls._task_streams.pop(task_id_str, None)
        cls._cancel_flags.pop(task_id_str, None)

    @staticmethod
    def _parse_json_response(content: str) -> dict:
        """从 AI 回复中解析 JSON 格式的分析结果.

        尝试多种策略提取 JSON：
        1. 查找 ```json ... ``` 代码块
        2. 查找裸 JSON { ... }
        3. 回退：将整个内容作为 risk_assessment

        Args:
            content: AI 原始回复文本.

        Returns:
            解析后的四部分字典.
        """
        default_result: dict = {
            "risk_assessment": {},
            "threat_analysis": {},
            "timeline_analysis": {},
            "recommendations": {},
        }

        if not content:
            return default_result

        # 策略1：提取 ```json 代码块
        json_str: Optional[str] = None
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()

        # 策略2：查找花括号包裹的 JSON
        if not json_str:
            brace_start = content.find("{")
            brace_end = content.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                json_str = content[brace_start:brace_end + 1]

        # 尝试解析
        if json_str:
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    result: dict = {
                        "risk_assessment": parsed.get("risk_assessment", {}),
                        "threat_analysis": parsed.get("threat_analysis", {}),
                        "timeline_analysis": parsed.get("timeline_analysis", {}),
                        "recommendations": parsed.get("recommendations", {}),
                    }
                    # 保留 LLM 实际返回的顶层叙事/处置字段（任务② overview/remediation）。
                    # 作为独立顶层字段原样保留，不并入上述四段标准字段，
                    # 供调用方（ai_payload）原样透传 story_line / key_events / remediation_scripts。
                    for _extra_key in ("story_line", "key_events", "remediation_scripts"):
                        if _extra_key in parsed:
                            result[_extra_key] = parsed[_extra_key]
                    return result
            except json.JSONDecodeError:
                logger.warning("Failed to parse AI JSON response, using fallback")

        # 策略3：回退 — 把整个内容当作 risk_assessment
        default_result["risk_assessment"] = {"raw_analysis": content}
        return default_result
