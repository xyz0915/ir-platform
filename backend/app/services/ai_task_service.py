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
from app.models.agent_baseline import AgentBaseline
from app.shared.ai_constants import TaskStatus, AUDIENCE_DEFAULT, INPUT_QUALITY_THRESHOLD
from app.shared.ai_error_mapping import map_http_error
from app.services.prompt_builder import PromptBuilder
from app.services.audit_service import AuditService
from app.services.input_quality_service import InputQualityService
from app.services.knowledge_retriever import KnowledgeRetriever
from app.services.explainability_service import ExplainabilityService
from app.services.ai_parse_guard import normalize_and_guard
from app.database import get_connection

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
    # v1.3.0：前端透传的受众偏好（technical/executive/both），按 task_id 暂存
    _audience_map: dict[str, str] = {}

    @classmethod
    async def submit(
        cls,
        host_id: int,
        profile_id: Optional[int] = None,
        masked_mode: bool = False,
        mode: str = "standard",
        focus_area: Optional[str] = None,
        base_report_id: Optional[int] = None,
        audience: Optional[str] = None,
    ) -> dict:
        """提交 AI 分析任务并启动后台执行.

        Args:
            host_id: 主机 ID.
            profile_id: AI 配置 Profile ID（None 则使用激活配置）.
            masked_mode: 是否启用数据脱敏.
            audience: 受众偏好（technical/executive/both），v1.3.0 双受众透传.

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
        # v1.3.0：透传受众偏好（仅 both/technical/executive 合法）
        if audience in ("technical", "executive", "both"):
            cls._audience_map[task_id_str] = audience
        else:
            cls._audience_map[task_id_str] = AUDIENCE_DEFAULT

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
            audience = cls._audience_map.get(task_id_str, AUDIENCE_DEFAULT)

            # v1.3.0 支柱③：读取主机差分基线（R3-1），用于 Prompt 注入与解析层降噪
            baseline: Optional[dict] = None
            try:
                baseline_rec = AgentBaseline.get_latest_by_host(host_id)
                if baseline_rec:
                    baseline = baseline_rec.get("baseline")
            except Exception as exc:  # noqa: BLE001
                logger.debug("读取基线失败，跳过: %s", exc)

            # v1.3.0 支柱④：读取引擎攻击链命中（仅叙述，不重判）
            attack_chain_hits: list[dict] = []
            try:
                from app.rules.rule_engine import RuleEngine

                attack_chain_hits = RuleEngine.get_attack_chain_hits(host_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("读取攻击链命中失败，跳过: %s", exc)

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
                prompts = PromptBuilder.build_overview(host_id=host_id, masked=masked_mode, baseline=baseline)
            elif mode == "remediation":
                prompts = PromptBuilder.build_remediation(host_id=host_id, masked=masked_mode, baseline=baseline)
            else:
                prompts = PromptBuilder.build(host_id=host_id, masked=masked_mode, baseline=baseline)
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

            # ── 知识入库：提取 knowledge_suggestions 并写入草稿 ──────
            knowledge_suggestions = parsed.get("knowledge_suggestions", [])
            if knowledge_suggestions and isinstance(knowledge_suggestions, list):
                try:
                    from app.models.knowledge_draft import KnowledgeDraft

                    draft_count = 0
                    for suggestion in knowledge_suggestions:
                        if not isinstance(suggestion, dict):
                            continue
                        title = suggestion.get("title", "")
                        description = suggestion.get("description", "")
                        if not title or not description:
                            continue
                        KnowledgeDraft.create(
                            host_id=str(host_id),
                            analysis_report_id=None,  # 报告尚未创建，后续可关联
                            title=title,
                            description=description,
                            category=suggestion.get("category", "auto"),
                            severity=suggestion.get("severity", "medium"),
                            mitre_attack=suggestion.get("mitre_attack"),
                            pattern=suggestion.get("pattern"),
                            source="ai_suggest",
                            raw_ioc=suggestion.get("raw_ioc"),
                        )
                        draft_count += 1
                    if draft_count > 0:
                        logger.info(
                            "AI task %d generated %d knowledge draft(s) from analysis",
                            task_id, draft_count,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to create knowledge drafts for task %d: %s",
                        task_id, exc,
                    )

            # Token 统计
            prompt_tokens = usage_info.get("prompt_tokens", 0)
            completion_tokens = usage_info.get("completion_tokens", 0)
            total_tokens = usage_info.get("total_tokens", 0)

            # 若流式 API 未返回 usage（DeepSeek 第三方直连兼容性）
            if total_tokens == 0:
                try:
                    import tiktoken
                    enc = tiktoken.get_encoding("cl100k_base")
                    prompt_tokens = len(enc.encode(system_prompt + user_prompt))
                    completion_tokens = len(enc.encode(full_content))
                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(
                        "Tokens estimated via tiktoken: prompt=%d, completion=%d, total=%d",
                        prompt_tokens, completion_tokens, total_tokens,
                    )
                except Exception:
                    # tiktoken 不可用时粗略估算（1 字符 ≈ 0.3 token）
                    prompt_tokens = len(system_prompt + user_prompt) // 3
                    completion_tokens = len(full_content) // 3
                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(
                        "Tokens estimated via char-based: prompt=%d, completion=%d, total=%d",
                        prompt_tokens, completion_tokens, total_tokens,
                    )

            # ── overview / remediation 专属报告（任务②）──────────────
            if mode in ("overview", "remediation"):
                ai_payload: dict = {"mode": mode, "payload": parsed}
                if mode == "overview":
                    ai_payload["story_line"] = parsed.get("story_line", "")
                    ai_payload["key_events"] = parsed.get("key_events", [])
                else:
                    ai_payload["remediation_scripts"] = parsed.get("remediation_scripts", [])
                # v1.3.0 解析层守护（受众/ATT&CK/稀有 等列统一产出）
                guarded = normalize_and_guard(
                    parsed,
                    baseline=baseline,
                    attack_chain_hits=attack_chain_hits,
                    audience=audience,
                )
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
                    audience=json.dumps(guarded["audience"], ensure_ascii=False),
                    mitre_attack=json.dumps(guarded["mitre_attack"], ensure_ascii=False),
                    attack_chain_hits=json.dumps(guarded["attack_chain_hits"], ensure_ascii=False),
                    rare_high_signals=json.dumps(guarded["rare_high_signals"], ensure_ascii=False),
                )
                logger.info(
                    "AI task %d 生成 %s 报告: report_id=%s", task_id, mode, report.get("id"),
                )
                # T-02: AI → incident_reports 映射（overview/remediation）
                try:
                    cls._map_ai_to_incident_report(
                        parsed=parsed,
                        guarded=guarded,
                        host_id=host_id,
                        host_name=host_name,
                        case_id=case_id,
                        audience=audience,
                        mode=mode,
                        ai_report_id=report["id"],
                    )
                except Exception as exc:
                    logger.warning("AI→Report mapping failed for task %d: %s", task_id, exc)
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
                # v1.3.1 P0: 知识库 IOC 证据交叉校验
                structured_knowledge = cls._cross_validate_knowledge(
                    structured_knowledge, tiered_data,
                )
                confirmed_knowledge = [
                    k for k in structured_knowledge
                    if k.get("evidence_level") != "none"
                ]
                unconfirmed_knowledge = [
                    k for k in structured_knowledge
                    if k.get("evidence_level") == "none"
                ]
                # 所有知识库命中都无行为证据时的记录
                if not confirmed_knowledge and structured_knowledge:
                    quality_context["input_quality"]["knowledge_note"] = (
                        f"知识库命中 {len(structured_knowledge)} 条但无行为证据"
                    )
                # 无证据命中自动转为 data_gap 推荐采集
                knowledge_data_gaps: list[dict] = []
                for item in unconfirmed_knowledge:
                    title = item.get("title", item.get("rule_name", "知识库命中"))
                    iocs_desc_list = item.get("recommended_collection", [])
                    iocs_desc = (
                        "; ".join(iocs_desc_list)
                        if iocs_desc_list
                        else "需补采验证"
                    )
                    knowledge_data_gaps.append({
                        "category": "knowledge_unconfirmed",
                        "title": f"知识库命中无行为证据: {title}",
                        "severity": "medium",
                        "description": (
                            f"知识库命中「{title}」，但主机采集数据中未发现"
                            f"对应 IOC 的实际行为证据。{iocs_desc}"
                        ),
                        "suggestion": "补充相关维度的主机采集数据后重新分析",
                        "recommended_actions": [{
                            "action_type": "net_capture",
                            "target": title,
                            "command_or_api": "",
                            "priority": "P1",
                            "rationale": (
                                f"知识库命中「{title}」无行为证据，需补采验证"
                            ),
                            "auto_runnable": False,
                        }],
                    })
                explainability = ExplainabilityService.build_evidence_trace(
                    parsed_sections=parsed,
                    knowledge_items=confirmed_knowledge,
                    tiered_data=tiered_data,
                )

                risk_assessment = ExplainabilityService.normalize_section(parsed.get("risk_assessment", {}))
                threat_analysis = ExplainabilityService.normalize_section(parsed.get("threat_analysis", {}))
                timeline_analysis = ExplainabilityService.ensure_structured_timeline(
                    ExplainabilityService.normalize_section(parsed.get("timeline_analysis", {})),
                    tiered_data,
                )

                # ── V2-6: AI key_events 与原始 timeline_events 关联 ──
                source_event_ids: Optional[str] = None
                try:
                    from app.models.analysis import TimelineEvent
                    raw_events = TimelineEvent.list_by_host(host_id)
                    ai_key_events = timeline_analysis.get("key_events", [])
                    if ai_key_events and raw_events:
                        matched_events = ExplainabilityService.normalize_key_events(
                            ai_key_events, raw_events,
                        )
                        matched_ids = [
                            e.get("source_event_id") for e in matched_events
                            if e.get("source_event_id") is not None
                        ]
                        if matched_ids:
                            source_event_ids = json.dumps(matched_ids, ensure_ascii=False)
                            timeline_analysis["key_events"] = matched_events
                except Exception as exc:
                    logger.warning("normalize_key_events failed: %s", exc)
                recommendations = ExplainabilityService.normalize_section(parsed.get("recommendations", {}))

                risk_assessment.setdefault("risk_level", tiered_data.get("analysis_result", {}).get("risk_level", "待确认"))
                risk_assessment.setdefault("risk_score", tiered_data.get("analysis_result", {}).get("risk_score", 0))
                risk_assessment["input_quality"] = quality_context["input_quality"]
                risk_assessment["coverage_gaps"] = quality_context["coverage_gaps"]
                risk_assessment["miss_risk"] = quality_context["miss_risk"]
                risk_assessment["evidence_insufficiency"] = quality_context["evidence_insufficiency"]

                # v1.3.1 P2: 输入质量阈值 → 数据增强模式
                quality_score = quality_context.get("input_quality", {}).get("score", 100)
                if quality_score < INPUT_QUALITY_THRESHOLD:
                    risk_assessment["analysis_mode"] = "data_enhancement"
                    risk_assessment["data_enhancement_banner"] = (
                        f"⚠ 输入质量不足({quality_score}分)，"
                        f"以下结论基于不完整数据，建议补采后重算"
                    )
                else:
                    risk_assessment["analysis_mode"] = "full"
                # v1.3.1 P0: 注入知识库交叉验证生成的 data_gaps
                if knowledge_data_gaps:
                    existing_gaps = risk_assessment.get("data_gaps", [])
                    if isinstance(existing_gaps, list):
                        risk_assessment["data_gaps"] = (
                            existing_gaps + knowledge_data_gaps
                        )
                    else:
                        risk_assessment["data_gaps"] = knowledge_data_gaps

                threat_analysis["evidence_trace"] = explainability["evidence_trace"]
                recommendations["input_suggestions"] = quality_context["input_suggestions"]
                recommendations["recommended_questions"] = explainability["recommended_questions"]

                # v1.3.0 解析层统一守护：评分回落/置信兜底/缺口合并/基线降噪/ATT&CK校验/稀有提级/受众归一
                # BugFix: 透传 AI 返回的顶层 audience / mitre_attack，使 normalize_and_guard 能消费 AI 产出的双受众内容
                guarded = normalize_and_guard(
                    {
                        "risk_assessment": risk_assessment,
                        "threat_analysis": threat_analysis,
                        "recommendations": recommendations,
                        "audience": parsed.get("audience"),
                        "mitre_attack": parsed.get("mitre_attack"),
                    },
                    baseline=baseline,
                    attack_chain_hits=attack_chain_hits,
                    audience=audience,
                )
                risk_assessment = guarded["risk_assessment"]
                threat_analysis = guarded["threat_analysis"]
                recommendations = guarded["recommendations"]

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
                    audience=json.dumps(guarded["audience"], ensure_ascii=False),
                    mitre_attack=json.dumps(guarded["mitre_attack"], ensure_ascii=False),
                    attack_chain_hits=json.dumps(guarded["attack_chain_hits"], ensure_ascii=False),
                    rare_high_signals=json.dumps(guarded["rare_high_signals"], ensure_ascii=False),
                    source_event_id=source_event_ids,
                )

            # T-02: AI → incident_reports 映射（标准/深挖/模块模式）
            try:
                cls._map_ai_to_incident_report(
                    parsed=parsed,
                    guarded=guarded,
                    host_id=host_id,
                    host_name=host_name,
                    case_id=case_id,
                    audience=audience,
                    mode=mode,
                    ai_report_id=report["id"],
                )
            except Exception as exc:
                logger.warning("AI→Report mapping failed for task %d: %s", task_id, exc)

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
                prompt=user_prompt,
                response=full_content,
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

            # 若 token 为空，尝试估算（DeepSeek 流式兼容；system_prompt
            # 可能在极早异常时未定义，此时保持 0 亦属合理）
            if total_tokens == 0:
                try:
                    _sp = system_prompt  # noqa: F841
                    _up = user_prompt    # noqa: F841
                    _fc = full_content   # noqa: F841
                except NameError:
                    pass
                else:
                    try:
                        import tiktoken
                        enc = tiktoken.get_encoding("cl100k_base")
                        prompt_tokens = len(enc.encode(system_prompt + user_prompt))
                        completion_tokens = len(enc.encode(full_content))
                        total_tokens = prompt_tokens + completion_tokens
                    except Exception:
                        prompt_tokens = len(system_prompt + user_prompt) // 3
                        completion_tokens = len(full_content) // 3
                        total_tokens = prompt_tokens + completion_tokens

            # 写入失败审计日志（失败原因使用友好提示）
            try:
                _prompt = user_prompt
                _response = full_content
            except NameError:
                _prompt = ""
                _response = ""
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
                    prompt=_prompt,
                    response=_response,
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

            # 若 token 为空，尝试估算（DeepSeek 流式兼容）
            if total_tokens == 0:
                try:
                    _sp = system_prompt  # noqa: F841
                    _up = user_prompt    # noqa: F841
                    _fc = full_content   # noqa: F841
                except NameError:
                    pass
                else:
                    try:
                        import tiktoken
                        enc = tiktoken.get_encoding("cl100k_base")
                        prompt_tokens = len(enc.encode(system_prompt + user_prompt))
                        completion_tokens = len(enc.encode(full_content))
                        total_tokens = prompt_tokens + completion_tokens
                    except Exception:
                        prompt_tokens = len(system_prompt + user_prompt) // 3
                        completion_tokens = len(full_content) // 3
                        total_tokens = prompt_tokens + completion_tokens

            # 写入失败审计日志
            try:
                _prompt = user_prompt
                _response = full_content
            except NameError:
                _prompt = ""
                _response = ""
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
                    prompt=_prompt,
                    response=_response,
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
        cls._audience_map.pop(task_id_str, None)

    @staticmethod
    def _cross_validate_knowledge(
        knowledge_items: list[dict],
        tiered_data: dict,
    ) -> list[dict]:
        """v1.3.1 P0: 知识库 IOC 证据交叉校验.

        对每条 knowledge_item，提取其中提到的 IOC（IP、域名、文件hash、
        进程名等），在 tiered_data 中反查是否有实际行为证据：
        - 有证据 → evidence_level: "confirmed"
        - 无证据 → evidence_level: "none"，附带 recommended_collection 建议

        Args:
            knowledge_items: 知识库检索结果（structured=True）.
            tiered_data: 主机分层采集数据.

        Returns:
            校验后的 knowledge_items 列表（每项含 evidence_level）.
        """
        import re

        if not knowledge_items:
            return knowledge_items

        # ── 从 tiered_data 收集实际证据 ──
        all_ips: set[str] = set()
        all_domains: set[str] = set()
        all_hashes: set[str] = set()
        all_process_names: set[str] = set()
        all_file_paths: set[str] = set()

        for severity_key in (
            "suspicious_connections_high",
            "suspicious_connections_medium",
            "suspicious_connections_low",
        ):
            for conn in tiered_data.get(severity_key, []) or []:
                if not isinstance(conn, dict):
                    continue
                remote = str(conn.get("remote", ""))
                if ":" in remote:
                    ip_part = remote.split(":")[0]
                    all_ips.add(ip_part)
                    all_domains.add(ip_part)
                elif remote:
                    all_ips.add(remote)
                    all_domains.add(remote)
                proc = str(conn.get("process", "")).lower()
                if proc:
                    all_process_names.add(proc)

        for severity_key in (
            "abnormal_processes_high",
            "abnormal_processes_medium",
            "abnormal_processes_low",
        ):
            for proc in tiered_data.get(severity_key, []) or []:
                if not isinstance(proc, dict):
                    continue
                name = str(
                    proc.get("name", "") or proc.get("process_name", "")
                ).lower()
                path = str(
                    proc.get("path", "") or proc.get("process_path", "")
                ).lower()
                cmd = str(
                    proc.get("cmd", "") or proc.get("command_line", "")
                ).lower()
                if name:
                    all_process_names.add(name)
                if path:
                    all_file_paths.add(path)
                if cmd:
                    all_file_paths.add(cmd)

        for pers in tiered_data.get("persistence_suspicious", []) or []:
            if not isinstance(pers, dict):
                continue
            name = str(pers.get("name", "")).lower()
            loc = str(pers.get("location", "")).lower()
            cmd = str(pers.get("command", "")).lower()
            if name:
                all_process_names.add(name)
            if loc:
                all_file_paths.add(loc)
            if cmd:
                all_file_paths.add(cmd)

        for severity_key in (
            "ioc_hits_high", "ioc_hits_medium", "ioc_hits_low",
        ):
            for ioc in tiered_data.get(severity_key, []) or []:
                if not isinstance(ioc, dict):
                    continue
                value = str(ioc.get("value", ""))
                ioc_type = str(ioc.get("type", "")).lower()
                if not value:
                    continue
                if ioc_type in ("ip", "ipv4", "ipv6") or re.match(
                    r"^\d+\.\d+\.\d+\.\d+$", value,
                ):
                    all_ips.add(value)
                elif ioc_type in ("domain", "url"):
                    all_domains.add(value)
                elif ioc_type in ("hash", "md5", "sha1", "sha256"):
                    all_hashes.add(value)
                all_file_paths.add(value.lower())

        # ── 逐条校验 ──
        validated: list[dict] = []
        for item in knowledge_items:
            if not isinstance(item, dict):
                validated.append(item)
                continue

            item = dict(item)  # 浅拷贝，不污染原数据
            text_to_search = ""
            for key in (
                "formatted_text", "evidence_text", "summary",
                "description", "title", "rule_name",
            ):
                val = item.get(key)
                if isinstance(val, str):
                    text_to_search += " " + val

            text_lower = text_to_search.lower()

            # 提取 IOC
            ip_pattern = re.compile(
                r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
            )
            found_ips: set[str] = set(ip_pattern.findall(text_to_search))

            domain_pattern = re.compile(
                r"\b([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}\b",
            )
            found_domains: set[str] = (
                set(domain_pattern.findall(text_to_search)) - found_ips
            )

            hash_pattern = re.compile(r"\b([a-fA-F0-9]{32,64})\b")
            found_hashes: set[str] = set(hash_pattern.findall(text_to_search))

            # 交叉验证
            has_evidence = False
            evidence_sources: list[str] = []

            for ip in found_ips:
                if ip in all_ips:
                    has_evidence = True
                    evidence_sources.append(
                        f"IP {ip} 在主机网络连接证据中确认",
                    )

            for domain in found_domains:
                if domain.lower() in all_domains:
                    has_evidence = True
                    evidence_sources.append(
                        f"域名 {domain} 在主机网络连接证据中确认",
                    )

            for h in found_hashes:
                if h in all_hashes:
                    has_evidence = True
                    evidence_sources.append(
                        f"哈希 {h[:8]}... 在 IOC 命中中确认",
                    )

            if not has_evidence:
                for proc_name in all_process_names:
                    if len(proc_name) >= 4 and proc_name in text_lower:
                        has_evidence = True
                        evidence_sources.append(
                            f"进程 {proc_name} 在主机进程证据中确认",
                        )
                        break

            if not has_evidence:
                for file_path in all_file_paths:
                    if len(file_path) >= 5 and file_path in text_lower:
                        has_evidence = True
                        evidence_sources.append(
                            f"路径 {file_path} 在主机证据中确认",
                        )
                        break

            # 标记证据级别
            if has_evidence:
                item["evidence_level"] = "confirmed"
                item["evidence_sources"] = evidence_sources
            else:
                item["evidence_level"] = "none"
                iocs_found: list[str] = []
                for ip in found_ips:
                    iocs_found.append(f"IP {ip}")
                for domain in found_domains:
                    iocs_found.append(f"域名 {domain}")
                for h in found_hashes:
                    iocs_found.append(f"哈希 {h[:16]}...")
                if iocs_found:
                    item["recommended_collection"] = [
                        f"派发 Agent 补采网络连接日志以验证 IOC "
                        f"{', '.join(iocs_found[:3])}",
                    ]

            validated.append(item)

        logger.info(
            "_cross_validate_knowledge: total=%d confirmed=%d none=%d",
            len(validated),
            sum(1 for v in validated if isinstance(v, dict) and v.get("evidence_level") == "confirmed"),
            sum(1 for v in validated if isinstance(v, dict) and v.get("evidence_level") == "none"),
        )
        return validated

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
                        # v1.3.0 BugFix: 提取 AI 返回的顶层 audience / mitre_attack
                        "audience": parsed.get("audience"),
                        "mitre_attack": parsed.get("mitre_attack"),
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

    # ────────────────────────────────────────────────────────────
    # T-02 ~ T-04: AI → incident_reports 映射核心逻辑
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_timeline_events(key_events: list) -> list:
        """规范化时间线事件，兼容 AI 输出的各种字段名变体."""
        normalized = []
        for i, evt in enumerate(key_events if key_events else []):
            if not isinstance(evt, dict):
                continue
            normalized.append({
                "_key": f"ai_{evt.get('time', evt.get('timestamp', evt.get('ts', f'event_{i}'))):.20}_{i}",
                "time": evt.get("time", evt.get("timestamp", evt.get("ts", ""))),
                "severity": evt.get("severity", evt.get("level", evt.get("risk", "medium"))),
                "event": evt.get("event", evt.get("title", evt.get("name", ""))),
                "description": evt.get("description", evt.get("detail", evt.get("desc", ""))),
                # 保留原始有用字段以便前端跳转
                "pid": evt.get("pid"),
                "remote_ip": evt.get("remote_ip"),
                "remote_port": evt.get("remote_port"),
                "registry_key": evt.get("registry_key"),
            })
        return normalized

    @staticmethod
    def _normalize_recommendations(recs: dict) -> str:
        """规范化建议措施，确保字段一致."""
        items = recs.get("items", recs.get("recommendations", []))
        if not isinstance(items, list):
            return json.dumps({"items": []}, ensure_ascii=False)

        normalized = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            priority_raw = item.get("priority", item.get("level", "medium"))
            # 优先级映射
            priority_map = {
                "urgent": "high", "critical": "high", "高": "high", "1": "high",
                "medium": "medium", "中": "medium", "2": "medium",
                "low": "low", "低": "low", "3": "low",
            }
            priority = priority_map.get(str(priority_raw).lower(), "medium")

            normalized.append({
                "_key": f"ai_rec_{i}",
                "text": item.get("text", item.get("description", item.get("name", ""))),
                "priority": priority,
                "checked": False,
                "source": "ai",
            })

        return json.dumps({"items": normalized}, ensure_ascii=False)

    @classmethod
    def _map_ai_to_incident_report(
        cls,
        parsed: dict,
        guarded: dict,
        host_id: int,
        host_name: str,
        case_id: int,
        audience: str,
        mode: str,
        ai_report_id: int,
        sections: Optional[list[str]] = None,
    ) -> dict:
        """将 AI 分析结果映射到 incident_reports 表记录.

        支持全量（sections=None）和增量（sections=[...]）两种模式.

        Args:
            parsed: _parse_json_response 解析出的四段字典.
            guarded: normalize_and_guard 的守护输出.
            host_id: 主机 ID.
            host_name: 主机名.
            case_id: 案件 ID.
            audience: 受众偏好.
            mode: 分析模式（standard/overview/remediation）.
            ai_report_id: AiAnalysisReport 的 ID.
            sections: 仅更新的段落列表（None=全量）.

        Returns:
            创建的 incident_report 记录字典.
        """
        # 提取各段内容
        risk = parsed.get("risk_assessment", {})
        threat = parsed.get("threat_analysis", {})
        timeline = parsed.get("timeline_analysis", {})
        recs = parsed.get("recommendations", {})

        # risk_assessment.summary -> summary
        summary = ""
        if isinstance(risk, dict):
            summary = risk.get("summary", "") or ""

        # threat_analysis.affected_systems -> impact_scope
        impact_scope = "[]"
        if isinstance(threat, dict) and threat.get("affected_systems"):
            impact_scope = json.dumps(threat["affected_systems"], ensure_ascii=False)

        # timeline_analysis.key_events -> timeline_json
        timeline_json = "[]"
        if isinstance(timeline, dict) and timeline.get("key_events"):
            timeline_json = json.dumps(
                cls._normalize_timeline_events(timeline["key_events"]),
                ensure_ascii=False,
            )

        # guarded.mitre_attack -> mitre_cover
        mitre_cover = "[]"
        if guarded.get("mitre_attack"):
            mitre_cover = json.dumps(guarded["mitre_attack"], ensure_ascii=False)

        # risk_assessment.findings -> evidence（含证据链接标记 + evidence_meta 结构化索引）
        evidence = ""
        findings = []
        evidence_meta = {"processes": [], "connections": [], "registry": [], "iocs": [], "files": []}
        if isinstance(risk, dict):
            raw_findings = risk.get("findings", [])
            if isinstance(raw_findings, list):
                for idx, f in enumerate(raw_findings):
                    if isinstance(f, dict):
                        f_text = f.get("description", f.get("title", f.get("detail", "")))
                        f_type = f.get("type", "finding")
                        if f_type == "process":
                            f_id = f.get("pid", f.get("id", idx))
                            evidence_meta["processes"].append({
                                "pid": f.get("pid"), "name": f.get("name"), "path": f.get("path"),
                            })
                        elif f_type == "network":
                            f_id = f.get("remote_ip", f.get("id", idx))
                            evidence_meta["connections"].append({
                                "remote_ip": f.get("remote_ip"), "remote_port": f.get("remote_port"),
                                "protocol": f.get("protocol"),
                            })
                        elif f_type == "registry":
                            f_id = f.get("key", f.get("registry_key", f.get("id", idx)))
                            evidence_meta["registry"].append({
                                "key": f.get("key", f.get("registry_key")),
                            })
                        elif f_type == "ioc":
                            f_id = f.get("value", f.get("id", idx))
                            evidence_meta["iocs"].append({
                                "value": f.get("value"), "type": f.get("ioc_type"),
                            })
                        elif f_type == "file":
                            f_id = f.get("path", f.get("name", f.get("id", idx)))
                            evidence_meta["files"].append({
                                "path": f.get("path"), "name": f.get("name"),
                            })
                        else:
                            f_id = f.get("id", idx)
                        link_mark = f"[🔗](host://{f_type}/{f_id})"
                        findings.append(f"{link_mark} {f_text}")
                    elif isinstance(f, str):
                        findings.append(f)
        if not findings and isinstance(risk, dict):
            desc = risk.get("description", "")
            if desc:
                findings.append(desc)
        if findings:
            evidence = "\n".join(findings)

        evidence_meta_json = json.dumps(evidence_meta, ensure_ascii=False)

        # recommendations.items -> recommendations（规范化）
        recommendations_str = "{}"
        if isinstance(recs, dict):
            recommendations_str = cls._normalize_recommendations(recs)

        # 风险评分 & 风险等级
        risk_score = 0
        risk_level = ""
        if isinstance(risk, dict):
            risk_level = risk.get("risk_level", "") or ""
            risk_score = risk.get("risk_score", 0) or 0

        # 置信度元数据 (T-03)
        confidence = cls._build_confidence_metadata(
            parsed, guarded, risk, threat, recs, timeline,
        )

        # 报告类型 (T-04)
        findings_count = len(findings)
        report_type = cls._auto_detect_report_type(risk, mode, findings_count)

        # 标题（自动序号）
        existing_count = cls._count_existing_reports(host_id)
        suffix = f" #{existing_count + 1}" if existing_count > 0 else ""
        risk_prefix = f"[{risk.get('risk_level', '')}] " if isinstance(risk, dict) and risk.get("risk_level") else ""
        title = f"{risk_prefix}{host_name} 安全分析报告{suffix}"

        # ── 写入 incident_reports 表 ──
        from datetime import datetime

        now = datetime.now().isoformat()

        if sections is None:
            # 全量创建
            with get_connection() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO incident_reports
                        (title, report_type, audience, status, summary,
                         impact_scope, timeline_json, mitre_cover, evidence,
                         evidence_meta, recommendations, case_id, host_id, created_by,
                         risk_score, confidence_metadata, version,
                         ai_report_id, mode, created_at, updated_at)
                    VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        title, report_type, audience, summary,
                        impact_scope, timeline_json, mitre_cover, evidence,
                        evidence_meta_json, recommendations_str, case_id, host_id, "ai_auto",
                        risk_score, json.dumps(confidence, ensure_ascii=False),
                        ai_report_id, mode, now, now,
                    ),
                )
                report_id = cur.lastrowid
                conn.commit()
        else:
            # 增量更新
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id, version FROM incident_reports WHERE ai_report_id = ? ORDER BY version DESC LIMIT 1",
                    (ai_report_id,),
                ).fetchone()
                if not row:
                    return cls._map_ai_to_incident_report(
                        parsed, guarded, host_id, host_name,
                        case_id, audience, mode, ai_report_id,
                        sections=None,
                    )
                report_id = row["id"]
                new_version = row["version"] + 1

                updates = {"updated_at": now, "version": new_version}
                if "summary" in sections:
                    updates["summary"] = summary
                if "impact" in sections:
                    updates["impact_scope"] = impact_scope
                if "timeline" in sections:
                    updates["timeline_json"] = timeline_json
                if "mitre" in sections:
                    updates["mitre_cover"] = mitre_cover
                if "evidence" in sections:
                    updates["evidence"] = evidence
                    updates["evidence_meta"] = evidence_meta_json
                if "recommendations" in sections:
                    updates["recommendations"] = recommendations_str
                if "confidence" in sections:
                    updates["confidence_metadata"] = json.dumps(confidence, ensure_ascii=False)
                if "report_type" in sections:
                    updates["report_type"] = report_type

                set_clause = ", ".join(f"{k}=?" for k in updates)
                params = list(updates.values()) + [report_id]
                conn.execute(
                    f"UPDATE incident_reports SET {set_clause} WHERE id=?",
                    params,
                )
                conn.commit()

        # 读取并返回完整记录
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM incident_reports WHERE id = ?", (report_id,),
            ).fetchone()
            return dict(row) if row else {}

    @classmethod
    def _count_existing_reports(cls, host_id: int) -> int:
        """统计某主机已有的 incident_reports 数量."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM incident_reports WHERE host_id = ?",
                (host_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    @staticmethod
    def _auto_detect_report_type(
        risk_assessment: dict,
        mode: str,
        findings_count: int,
    ) -> str:
        """自动检测报告类型（T-04）.

        Args:
            risk_assessment: 风险评估段落.
            mode: 分析模式.
            findings_count: 发现项数量.

        Returns:
            报告类型: situation | forensic | emergency | compliance
        """
        if mode == "overview":
            return "situation"

        risk_level = ""
        risk_score = 0
        if isinstance(risk_assessment, dict):
            risk_level = (risk_assessment.get("risk_level") or "").strip()
            risk_score = risk_assessment.get("risk_score", 0) or 0

        if risk_level == "安全" or risk_score < 20:
            return "situation"

        if risk_level == "待确认" or "待确认" in risk_level:
            return "forensic"

        if risk_level in ("高危", "严重", "critical", "high") or risk_score >= 60:
            return "emergency"

        return "compliance"

    @staticmethod
    def _build_confidence_metadata(
        parsed: dict,
        guarded: dict,
        risk: dict,
        threat: dict,
        recs: dict,
        timeline: dict,
    ) -> dict:
        """构建各段落的置信度元数据（T-03）."""
        confidence: dict[str, int] = {}

        # summary
        has_rule_hits = bool(guarded.get("attack_chain_hits"))
        if has_rule_hits:
            confidence["summary"] = 95
        elif isinstance(risk, dict) and risk.get("risk_level"):
            confidence["summary"] = 70
        else:
            confidence["summary"] = 50

        # timeline
        if isinstance(timeline, dict):
            key_events = timeline.get("key_events", [])
            if key_events:
                event_count = len(key_events)
                if event_count >= 5:
                    confidence["timeline"] = 95
                elif event_count >= 3:
                    confidence["timeline"] = 80
                else:
                    confidence["timeline"] = 60
            else:
                confidence["timeline"] = 40
        else:
            confidence["timeline"] = 40

        # recommendations
        if isinstance(recs, dict):
            rec_items = recs.get("items", recs.get("recommendations", []))
            if isinstance(rec_items, list) and rec_items:
                item_count = len(rec_items)
                if item_count >= 5:
                    confidence["recommendations"] = 90
                elif item_count >= 3:
                    confidence["recommendations"] = 70
                else:
                    confidence["recommendations"] = 50
            else:
                confidence["recommendations"] = 40
        else:
            confidence["recommendations"] = 40

        # impact
        if isinstance(threat, dict):
            if threat.get("affected_systems"):
                confidence["impact"] = 85
            else:
                confidence["impact"] = 50
        else:
            confidence["impact"] = 50

        # evidence: 固定80
        confidence["evidence"] = 80

        return confidence

    @staticmethod
    def _score_to_level(score: int) -> str:
        """将分数转换为等级标签."""
        if score >= 80:
            return "high"
        elif score >= 60:
            return "medium"
        elif score >= 40:
            return "low"
        return "very_low"
