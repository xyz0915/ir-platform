"""AI分析服务 — 大模型API调用与报告生成.

提供 API Key 加解密、LLM 调用（同步+流式）、AI 配置管理、
JSON 响应解析等功能。旧版 analyze_with_ai 保留向后兼容。
"""

import hashlib
import json
import logging
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Optional

import httpx

from app.config import settings
from app.models.ai_config import AiConfig, AiConfigProfile
from app.shared.ai_error_mapping import map_http_error
from app.models.ai_analysis import AiAnalysisReport
from app.models.host import Host
from app.models.analysis import AnalysisResult
from app.services.explainability_service import ExplainabilityService
from app.services.input_quality_service import InputQualityService
from app.services.knowledge_retriever import KnowledgeRetriever
from app.services.prompt_builder import PromptBuilder
from app.services.ai_parse_guard import normalize_and_guard

logger = logging.getLogger(__name__)

# 默认系统提示词（旧版兼容，新版由 PromptBuilder 生成）
DEFAULT_SYSTEM_PROMPT = """你是一个专业的网络安全应急响应分析专家。基于提供的主机取证数据和分析结果，你需要：
1. 评估主机的安全风险等级和可能的威胁类型
2. 分析攻击者的可能入侵路径和手法
3. 对攻击时间线进行专业解读
4. 给出针对性的处置建议和加固方案
请用中文输出，结构化格式，包含以下四个部分（每个部分用明确的标题标注）：

## 风险评估
综合评估风险等级、威胁类型和严重程度。

## 威胁分析
分析可能的入侵路径、攻击手法、恶意行为特征。

## 时间线解读
按时间顺序解读关键事件，串联攻击链路。

## 处置建议
给出具体的处置步骤、清除方案和安全加固建议。"""


class AiService:
    """AI分析服务."""

    # ================================================================
    # API Key 加解密（不变）
    # ================================================================

    @staticmethod
    def encrypt_api_key(key: str) -> str:
        """加密API Key（使用Fernet对称加密）."""
        from cryptography.fernet import Fernet

        fernet_key = settings.AI_ENCRYPTION_KEY
        f = Fernet(fernet_key)
        return f.encrypt(key.encode()).decode()

    @staticmethod
    def decrypt_api_key(encrypted: str) -> str:
        """解密API Key."""
        from cryptography.fernet import Fernet

        fernet_key = settings.AI_ENCRYPTION_KEY
        f = Fernet(fernet_key)
        return f.decrypt(encrypted.encode()).decode()

    @staticmethod
    def mask_api_key(key: str) -> str:
        """脱敏API Key（仅显示最后4位）."""
        if not key or len(key) <= 4:
            return "****"
        return "****" + key[-4:]

    # ================================================================
    # 配置管理（委托给 AiConfigProfile）
    # ================================================================

    @staticmethod
    def get_config() -> Optional[dict]:
        """获取AI配置（API Key脱敏）.

        优先从 AiConfigProfile.get_active() 获取，回退到旧 AiConfig.
        """
        profile = AiConfigProfile.get_active()
        if profile:
            masked_key = AiService.mask_api_key(profile.get("api_key", ""))
            result = dict(profile)
            result["api_key_masked"] = masked_key
            result["enabled"] = 1  # 激活的Profile即表示enabled
            del result["api_key"]
            return result

        # 回退：旧 AiConfig
        config = AiConfig.get()
        if not config:
            return None
        masked_key = AiService.mask_api_key(config.get("api_key", ""))
        result = dict(config)
        result["api_key_masked"] = masked_key
        del result["api_key"]
        return result

    @staticmethod
    def save_config(data: dict) -> dict:
        """保存AI配置（加密API Key后存储）.

        委托给 AiConfigProfile 或旧 AiConfig.
        """
        api_key_plain = data.get("api_key", "")
        encrypted_key = AiService.encrypt_api_key(api_key_plain) if api_key_plain else ""

        # 优先使用新 Profile 模型
        active = AiConfigProfile.get_active()
        if active:
            update_kwargs: dict = {}
            if data.get("api_base_url"):
                update_kwargs["api_base_url"] = data["api_base_url"]
            if encrypted_key:
                update_kwargs["api_key"] = encrypted_key
            if data.get("model_name"):
                update_kwargs["model_name"] = data["model_name"]
            if "max_tokens" in data:
                update_kwargs["max_tokens"] = data["max_tokens"]
            if "temperature" in data:
                update_kwargs["temperature"] = data["temperature"]
            if "system_prompt" in data:
                update_kwargs["system_prompt"] = data.get("system_prompt", "")
            if update_kwargs:
                AiConfigProfile.update(active["id"], **update_kwargs)
            if data.get("enabled") == 1:
                AiConfigProfile.set_active(active["id"])
        else:
            # 回退：旧 AiConfig
            config = AiConfig.save(
                api_base_url=data.get("api_base_url", ""),
                api_key_encrypted=encrypted_key,
                model_name=data.get("model_name", "gpt-4o"),
                enabled=data.get("enabled", 0),
                max_tokens=data.get("max_tokens", 4096),
                temperature=data.get("temperature", 0.3),
                system_prompt=data.get("system_prompt", ""),
            )

        return AiService.get_config()

    @staticmethod
    def toggle_enabled(enabled: int) -> dict:
        """开启/关闭AI功能.

        检查激活的 Profile 配置是否完整（api_base_url 和 api_key 不为空）.
        """
        if enabled == 1:
            profile = AiConfigProfile.get_active()
            if not profile:
                # 回退旧 config
                config = AiConfig.get()
                if not config:
                    raise ValueError("请先配置AI参数（API地址和密钥）")
                if not config.get("api_base_url") or not config.get("api_key"):
                    raise ValueError("API地址和密钥不能为空")
            else:
                if not profile.get("api_base_url") or not profile.get("api_key"):
                    raise ValueError("当前激活的配置缺少API地址或密钥")
        result = AiConfig.update_enabled(enabled)
        return AiService.get_config()

    # ================================================================
    # LLM 调用（同步 + 流式）
    # ================================================================

    @staticmethod
    async def call_llm(
        api_base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """调用 OpenAI-compatible 格式的 LLM API（非流式）.

        兼容部分新模型/代理网关对 token 参数名的差异：
        - 传统 chat completions: max_tokens
        - 新接口/部分网关: max_output_tokens

        Args:
            api_base_url: API 基础 URL.
            api_key: API Key（已解密）.
            model: 模型名称.
            system_prompt: 系统提示词.
            user_prompt: 用户提示词.
            max_tokens: 最大生成 token 数.
            temperature: 生成温度.

        Returns:
            LLM API 原始响应 JSON.

        Raises:
            httpx.HTTPStatusError: API 返回非 200.
            httpx.TimeoutException: 请求超时.
            httpx.ConnectError: 连接失败.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        url = api_base_url.rstrip("/") + "/chat/completions"
        logger.info("Calling LLM API: %s, model: %s", url, model)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 400:
                body_text = resp.text
                if "Unsupported parameter: max_output_tokens" in body_text:
                    retry_payload = dict(payload)
                    retry_payload.pop("max_tokens", None)
                    retry_payload["max_output_tokens"] = max_tokens
                    logger.warning(
                        "LLM gateway rejected max_output_tokens expectation mismatch; retrying with max_output_tokens"
                    )
                    resp = await client.post(url, headers=headers, json=retry_payload)
                elif "Unsupported parameter: max_tokens" in body_text:
                    retry_payload = dict(payload)
                    retry_payload.pop("max_tokens", None)
                    retry_payload["max_output_tokens"] = max_tokens
                    logger.warning("LLM gateway rejected max_tokens; retrying with max_output_tokens")
                    resp = await client.post(url, headers=headers, json=retry_payload)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def call_llm_stream(
        api_base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator[dict, None]:
        """流式调用 OpenAI-compatible 格式的 LLM API.

        使用 httpx.AsyncClient.stream() 处理 SSE 事件流。
        每个 yield 的 dict 包含：
        - content: str — 本次 chunk 的文本内容
        - usage: dict | None — token 使用统计（仅在最后一个 chunk）

        Args:
            api_base_url: API 基础 URL.
            api_key: API Key（已解密）.
            model: 模型名称.
            system_prompt: 系统提示词.
            user_prompt: 用户提示词.
            max_tokens: 最大生成 token 数.
            temperature: 生成温度.

        Yields:
            包含 content 和 usage 的字典.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        url = api_base_url.rstrip("/") + "/chat/completions"
        logger.info("Calling LLM API (stream): %s, model: %s", url, model)

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse SSE line: %s", data_str[:100])
                        continue

                    choices = data.get("choices", [])
                    usage = data.get("usage")

                    content = ""
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")

                    yield {
                        "content": content,
                        "usage": usage,
                    }

    # ================================================================
    # 新旧分析入口
    # ================================================================

    @staticmethod
    async def analyze_with_ai(host_id: int) -> dict:
        """【已弃用】一键AI分析 — 组装数据、调用LLM、保存报告.

        保留此方法用于向后兼容。新代码请使用 analyze_with_ai_json() 和 AiTaskService.

        Args:
            host_id: 主机ID.

        Returns:
            AI分析报告字典.

        Raises:
            ValueError: AI功能未开启或配置不完整.
        """
        warnings.warn(
            "analyze_with_ai() is deprecated, use analyze_with_ai_json() or AiTaskService.submit()",
            DeprecationWarning,
            stacklevel=2,
        )

        # 1. 检查AI是否开启
        config = AiConfig.get()
        if not config or config.get("enabled") != 1:
            raise ValueError("AI分析功能未开启，请在AI设置中手动开启")
        if not config.get("api_base_url") or not config.get("api_key"):
            raise ValueError("API配置不完整")

        # 2. 检查主机状态
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")
        if host.get("status") not in ("imported", "analyzed"):
            raise ValueError("请先导入采集数据并完成本地分析")

        # 3. 解密API Key
        api_key = AiService.decrypt_api_key(config["api_key"])
        api_base_url = config["api_base_url"]
        model_name = config["model_name"]
        max_tokens = config.get("max_tokens", 4096)
        temperature = config.get("temperature", 0.3)
        system_prompt = config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

        # 4. 构建prompt（旧方式）
        user_prompt = AiService._build_analysis_prompt(host_id)

        # 5. 调用LLM
        logger.info("Starting AI analysis for host %d with model %s", host_id, model_name)
        try:
            llm_response = await AiService.call_llm(
                api_base_url=api_base_url,
                api_key=api_key,
                model=model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except httpx.HTTPStatusError as e:
            logger.error("LLM API error: %s %s", e.response.status_code, e.response.text)
            raise ValueError(map_http_error(e))
        except httpx.TimeoutException:
            raise ValueError("AI服务调用超时（120秒），请检查API地址是否正确")
        except httpx.ConnectError:
            raise ValueError("无法连接AI服务，请检查API地址是否正确")

        # 6. 解析AI回复
        choices = llm_response.get("choices", [])
        if not choices:
            raise ValueError("AI服务返回空结果")

        ai_content = choices[0].get("message", {}).get("content", "")
        tokens_used = llm_response.get("usage", {}).get("total_tokens", 0)

        # 7. 按结构化格式提取各部分
        risk_assessment = AiService._extract_section(ai_content, "风险评估")
        threat_analysis = AiService._extract_section(ai_content, "威胁分析")
        timeline_analysis = AiService._extract_section(ai_content, "时间线解读")
        recommendations = AiService._extract_section(ai_content, "处置建议")

        # 8. 保存报告
        case_id = host.get("case_id", 0)
        report = AiAnalysisReport.create(
            host_id=host_id,
            case_id=case_id,
            risk_assessment=risk_assessment or ai_content[:500],
            threat_analysis=threat_analysis,
            timeline_analysis=timeline_analysis,
            recommendations=recommendations,
            raw_response=ai_content,
            model_used=model_name,
            tokens_used=tokens_used,
        )

        logger.info(
            "AI analysis completed for host %d: model=%s, tokens=%d",
            host_id, model_name, tokens_used,
        )
        return report

    @staticmethod
    async def analyze_with_ai_json(host_id: int) -> dict:
        """AI分析 — 使用 PromptBuilder + JSON 格式输出.

        推荐的分析入口，使用分层 Prompt 构建器，强制 AI 返回 JSON 格式。
        如果 AI 配置开启了自定义 system_prompt，优先使用自定义的。
        支持分析缓存：相同数据 hash + 24h 内直接返回缓存结果。

        Args:
            host_id: 主机 ID.

        Returns:
            AI 分析报告字典.

        Raises:
            ValueError: AI 功能未开启或配置不完整.
        """
        # 1. 检查配置
        config = AiConfig.get()
        if not config or config.get("enabled") != 1:
            # 也检查新的 Profile
            profile = AiConfigProfile.get_active()
            if not profile:
                raise ValueError("AI分析功能未开启，请在AI设置中手动开启")
            config = AiConfig.get()
            if not config:
                raise ValueError("AI分析功能未开启，请在AI设置中手动开启")

        if not config.get("api_base_url") or not config.get("api_key"):
            raise ValueError("API配置不完整")

        # 2. 检查主机
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")

        # 3. 使用 PromptBuilder 构建结构化 prompt
        prompts = PromptBuilder.build(host_id=host_id, masked=False)
        system_prompt = prompts["system_prompt"]
        user_prompt = prompts["user_prompt"]

        # P2-09: 缓存检查 — 计算 data_hash，查24h内缓存
        data_hash = AiService._compute_data_hash(host_id)
        cached_report = AiAnalysisReport.get_cached_report(host_id, data_hash)
        if cached_report:
            logger.info(
                "Cache hit for host %d (hash=%s...), returning cached report",
                host_id, data_hash[:12],
            )
            return cached_report

        # 如果用户配置了自定义 system_prompt，使用自定义的
        custom_sp = config.get("system_prompt", "")
        if custom_sp:
            system_prompt = custom_sp
            logger.info("Using custom system_prompt for host %d", host_id)

        # 4. 解密 API Key
        api_key = AiService.decrypt_api_key(config["api_key"])
        api_base_url = config["api_base_url"]
        model_name = config["model_name"]
        max_tokens = config.get("max_tokens", 4096)
        temperature = config.get("temperature", 0.3)

        # 5. 调用 LLM（非流式，使用 response_format: json_object）
        logger.info("Starting AI JSON analysis for host %d with model %s", host_id, model_name)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        url = api_base_url.rstrip("/") + "/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                llm_response = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("LLM API error: %s %s", e.response.status_code, e.response.text)
            raise ValueError(map_http_error(e))
        except httpx.TimeoutException:
            raise ValueError("AI服务调用超时（120秒），请检查API地址是否正确")
        except httpx.ConnectError:
            raise ValueError("无法连接AI服务，请检查API地址是否正确")

        # 6. 解析 JSON 回复
        choices = llm_response.get("choices", [])
        if not choices:
            raise ValueError("AI服务返回空结果")

        ai_content = choices[0].get("message", {}).get("content", "")
        usage = llm_response.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)

        # 解析四部分并做本地增强兜底
        parsed = AiService.parse_json_response(ai_content)
        prompts_without_knowledge = PromptBuilder._fetch_tiered_data(host_id)
        quality_context = InputQualityService.evaluate(prompts_without_knowledge)
        structured_knowledge = KnowledgeRetriever.retrieve(
            prompts_without_knowledge,
            limit=5,
            structured=True,
        )
        explainability = ExplainabilityService.build_evidence_trace(
            parsed_sections=parsed,
            knowledge_items=structured_knowledge,
            tiered_data=prompts_without_knowledge,
        )

        risk_assessment = ExplainabilityService.normalize_section(parsed.get("risk_assessment", {}))
        threat_analysis = ExplainabilityService.normalize_section(parsed.get("threat_analysis", {}))
        timeline_analysis = ExplainabilityService.ensure_structured_timeline(
            ExplainabilityService.normalize_section(parsed.get("timeline_analysis", {})),
            prompts_without_knowledge,
        )
        recommendations = ExplainabilityService.normalize_section(parsed.get("recommendations", {}))

        risk_assessment.setdefault("risk_level", prompts_without_knowledge.get("analysis_result", {}).get("risk_level", "待确认"))
        risk_assessment.setdefault("risk_score", prompts_without_knowledge.get("analysis_result", {}).get("risk_score", 0))
        risk_assessment["input_quality"] = quality_context["input_quality"]
        risk_assessment["coverage_gaps"] = quality_context["coverage_gaps"]
        risk_assessment["miss_risk"] = quality_context["miss_risk"]
        risk_assessment["evidence_insufficiency"] = quality_context["evidence_insufficiency"]

        threat_analysis["evidence_trace"] = explainability["evidence_trace"]
        recommendations["input_suggestions"] = quality_context["input_suggestions"]
        recommendations["recommended_questions"] = explainability["recommended_questions"]

        # 7. 保存报告（含缓存字段 + v1.3.0 作战化新列）
        case_id = host.get("case_id", 0)
        cached_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # v1.3.0 BugFix: 从 parsed (已 _guard_parsed 增强) 提取作战化新字段
        guarded_audience = parsed.get("audience", "both")
        guarded_mitre = parsed.get("mitre_attack", [])
        guarded_rare = parsed.get("rare_high_signals", [])
        guarded_escalation = parsed.get("escalation_conditions", [])
        guarded_ach = parsed.get("attack_chain_hits", [])
        report = AiAnalysisReport.create(
            host_id=host_id,
            case_id=case_id,
            risk_assessment=json.dumps(risk_assessment, ensure_ascii=False),
            threat_analysis=json.dumps(threat_analysis, ensure_ascii=False),
            timeline_analysis=json.dumps(timeline_analysis, ensure_ascii=False),
            recommendations=json.dumps(recommendations, ensure_ascii=False),
            raw_response=ai_content,
            model_used=model_name,
            tokens_used=total_tokens,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            data_hash=data_hash,
            cached_at=cached_at,
            audience=json.dumps(guarded_audience, ensure_ascii=False) if not isinstance(guarded_audience, str) else guarded_audience,
            mitre_attack=json.dumps(guarded_mitre, ensure_ascii=False),
            attack_chain_hits=json.dumps(guarded_ach, ensure_ascii=False),
            rare_high_signals=json.dumps(guarded_rare, ensure_ascii=False),
        )

        logger.info(
            "AI JSON analysis completed for host %d: model=%s, tokens=%d, hash=%s",
            host_id, model_name, total_tokens, data_hash[:12],
        )
        return report

    @staticmethod
    def parse_json_response(content: str) -> dict:
        """从 JSON 格式 AI 回复中提取四部分分析内容.

        尝试多种策略：
        1. 直接 JSON.parse 整个响应
        2. 提取 ```json ``` 代码块
        3. 回退 Markdown 节提取

        Args:
            content: AI 原始回复文本.

        Returns:
            包含 risk_assessment, threat_analysis, timeline_analysis, recommendations 的字典.
        """
        default_result: dict = {
            "risk_assessment": {},
            "threat_analysis": {},
            "timeline_analysis": {},
            "recommendations": {},
        }

        if not content:
            return default_result

        # 策略1：整个文本作为 JSON 解析
        json_str: Optional[str] = None
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            json_str = content[brace_start:brace_end + 1]

        # 策略2：提取 ```json 代码块
        if not json_str and "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
        elif not json_str and "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()

        # 尝试 JSON 解析
        if json_str:
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    parsed_sections = {
                        "risk_assessment": parsed.get("risk_assessment", {}),
                        "threat_analysis": parsed.get("threat_analysis", {}),
                        "timeline_analysis": parsed.get("timeline_analysis", {}),
                        "recommendations": parsed.get("recommendations", {}),
                        # v1.3.0 BugFix: 提取 AI 返回的顶层新字段
                        "audience": parsed.get("audience"),
                        "mitre_attack": parsed.get("mitre_attack"),
                    }
                    return AiService._guard_parsed(parsed_sections)
            except json.JSONDecodeError:
                logger.warning("Failed to parse AI JSON response, falling back to Markdown extraction")

        # 策略3：回退 Markdown 节提取（旧方式）
        parsed = {
            "risk_assessment": {"raw_analysis": AiService._extract_section(content, "风险评估") or content[:500]},
            "threat_analysis": {"raw_analysis": AiService._extract_section(content, "威胁分析") or ""},
            "timeline_analysis": {"raw_analysis": AiService._extract_section(content, "时间线解读") or ""},
            "recommendations": {"raw_analysis": AiService._extract_section(content, "处置建议") or ""},
        }
        return AiService._guard_parsed(parsed)

    @staticmethod
    def _guard_parsed(parsed: dict) -> dict:
        """T17：解析层统一守护委托。

        对 risk/threat/recommendations 应用 ``normalize_and_guard`` 的一致性纠正
        （评分回落、置信兜底、缺口合并、基线降噪、ATT&CK 校验、稀有提级、受众归一），
        同时保留 timeline_analysis 不被评分逻辑改动，并附带作战化新字段。
        """
        try:
            guarded = normalize_and_guard({
                "risk_assessment": parsed.get("risk_assessment", {}),
                "threat_analysis": parsed.get("threat_analysis", {}),
                "recommendations": parsed.get("recommendations", {}),
                # v1.3.0 BugFix: 透传 AI 返回的顶层新字段给 normalize_and_guard
                "audience": parsed.get("audience"),
                "mitre_attack": parsed.get("mitre_attack"),
            })
            merged = dict(parsed)
            merged["risk_assessment"] = guarded["risk_assessment"]
            merged["threat_analysis"] = guarded["threat_analysis"]
            merged["recommendations"] = guarded["recommendations"]
            merged["data_gaps"] = guarded["data_gaps"]
            merged["mitre_attack"] = guarded["mitre_attack"]
            merged["rare_high_signals"] = guarded["rare_high_signals"]
            merged["escalation_conditions"] = guarded["escalation_conditions"]
            merged["audience"] = guarded["audience"]
            merged["attack_chain_hits"] = guarded["attack_chain_hits"]
            return merged
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析层守护失败，降级返回原始解析: %s", exc)
            return parsed

    # ================================================================
    # P2-01: 多轮对话
    # ================================================================

    @staticmethod
    async def chat_with_ai(
        host_id: int,
        message: str,
        conversation_history: Optional[list[dict]] = None,
        mode: str = "follow_up",
        focus_area: Optional[str] = None,
        base_report_id: Optional[int] = None,
    ) -> dict:
        """多轮对话聊天 — 带上下文历史的 AI 对话.

        构建 messages 数组 = system + history（限5轮） + 新问题，
        调用 LLM 获取回复。

        Args:
            host_id: 主机ID（用于 system prompt 中的主机上下文）.
            message: 用户消息内容.
            conversation_history: 历史对话列表 [{"role":"user","content":"..."}, ...].

        Returns:
            {"reply": str, "conversation_id": str, "model_used": str, "tokens_used": int}

        Raises:
            ValueError: AI 配置不完整或调用失败.
        """
        # 1. 获取配置
        profile = AiConfigProfile.get_active()
        if not profile:
            config = AiConfig.get()
            if not config:
                raise ValueError("AI分析功能未开启")
            api_base_url = config["api_base_url"]
            api_key = AiService.decrypt_api_key(config["api_key"])
            model_name = config["model_name"]
            max_tokens = config.get("max_tokens", 4096)
            temperature = config.get("temperature", 0.3)
            system_prompt = config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        else:
            api_base_url = profile["api_base_url"]
            api_key = AiService.decrypt_api_key(profile["api_key"])
            model_name = profile.get("model_name", "gpt-4o")
            max_tokens = profile.get("max_tokens", 4096)
            temperature = profile.get("temperature", 0.3)
            system_prompt = profile.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

        deep_context = AiService._build_deep_dive_context(
            host_id=host_id,
            mode=mode,
            focus_area=focus_area,
            base_report_id=base_report_id,
        )
        if deep_context:
            system_prompt = f"{system_prompt}\n\n{deep_context}"

        if not api_base_url or not api_key:
            raise ValueError("API配置不完整")

        # 2. 构建 messages
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]

        # 历史对话 — 最近5轮（每轮 user+assistant = 2条，共10条）
        if conversation_history:
            recent = conversation_history[-10:]
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # 当前用户问题
        messages.append({"role": "user", "content": message})

        # 3. 调用 LLM
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        url = api_base_url.rstrip("/") + "/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                llm_response = resp.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(map_http_error(e))
        except httpx.TimeoutException:
            raise ValueError("AI服务调用超时")
        except httpx.ConnectError:
            raise ValueError("无法连接AI服务")

        # 4. 解析回复
        choices = llm_response.get("choices", [])
        if not choices:
            raise ValueError("AI服务返回空结果")

        reply = choices[0].get("message", {}).get("content", "")
        tokens_used = llm_response.get("usage", {}).get("total_tokens", 0)

        conv_id = str(uuid.uuid4())[:8]

        logger.info("Chat completed: host=%d, model=%s, tokens=%d", host_id, model_name, tokens_used)
        return {
            "reply": reply,
            "conversation_id": conv_id,
            "model_used": model_name,
            "tokens_used": tokens_used,
            "mode": mode,
            "focus_area": focus_area,
        }

    @staticmethod
    def _build_deep_dive_context(
        host_id: int,
        mode: str,
        focus_area: Optional[str],
        base_report_id: Optional[int],
    ) -> str:
        """构建深挖/追问模式的附加上下文.

        deep_dive：基于已有分析报告深挖。
        follow_up：补充当前会话对应的原始模块/全量数据，让 AI 能回答「这些启动项是干嘛的」类问题。
        """
        context_lines: list[str] = []

        # 1. 反查 base_report 对应的 host_id + module_type
        resolved_host_id = host_id
        resolved_module: Optional[str] = None
        report = None
        if base_report_id:
            report = AiAnalysisReport.get_by_id(base_report_id)
        if report is None and host_id:
            report = AiAnalysisReport.get_by_host(host_id)
        if report:
            resolved_host_id = report.get("host_id", host_id)
            mt = report.get("module_type")
            if mt:
                resolved_module = mt
        # 追问链路前端可能没传 focus_area，从报告补
        if not focus_area and resolved_module:
            focus_area = resolved_module

        if mode == "deep_dive":
            context_lines.append("当前任务为 deep_dive 深挖模式，请基于已有分析继续收敛重点问题。")
        elif mode == "follow_up":
            context_lines.append("当前为追问模式，请基于下方提供的原始取证数据和已有分析回答用户问题。")
        else:
            return ""

        if focus_area:
            context_lines.append(f"本次分析重点领域：{focus_area}。")

        # 2. 拉该模块/全量原始数据塞进上下文
        try:
            # PromptBuilder 的常量是模块级，方法需实例化
            from app.services.prompt_builder import PromptBuilder, MODULE_DATA_MAP
            builder = PromptBuilder()
            if resolved_module and resolved_module in MODULE_DATA_MAP:
                # 模块追问：只拉该模块数据
                prompts = builder.build_module(
                    host_id=resolved_host_id,
                    module_type=resolved_module,
                    masked=True,
                )
                data_block = prompts.get("user_prompt", "")
            else:
                # 全量追问：拉全量（但不开知识库，避免重复干扰）
                prompts = builder.build(
                    host_id=resolved_host_id, masked=True, include_knowledge=False,
                )
                data_block = prompts.get("user_prompt", "")

            # 截断到 6000 字符，避免 token 爆炸
            if data_block:
                context_lines.append(
                    "## 原始取证数据（来自本主机，限参考前 6000 字符）\n"
                    + data_block[:6000]
                )
        except Exception as exc:
            logger.warning("Failed to build data context: %s", exc)

        # 3. 追加已有分析报告的基线
        if report:
            context_lines.append("## 已有分析基线（请避免重复描述，重点补充新论证）")
            context_lines.append(f"- 风险评估：{str(report.get('risk_assessment', ''))[:500]}")
            context_lines.append(f"- 威胁分析：{str(report.get('threat_analysis', ''))[:500]}")
            context_lines.append(f"- 时间线：{str(report.get('timeline_analysis', ''))[:500]}")

        if mode == "deep_dive":
            context_lines.append("请输出更细粒度证据解释、剩余疑点和下一步排查建议。")
        else:  # follow_up
            context_lines.append("请直接回答用户问题，引用上方数据中具体字段名/值。")

        return "\n\n".join(context_lines)

    # ================================================================
    # P2-09: 分析缓存
    # ================================================================

    @staticmethod
    def _compute_data_hash(host_id: int) -> str:
        """计算主机分析数据的 MD5 指纹 — 用于缓存.

        将 PromptBuilder 构建的数据序列化后计算 MD5，
        相同数据返回相同 hash，用于判断是否可以复用缓存.

        Args:
            host_id: 主机 ID.

        Returns:
            MD5 十六进制字符串.
        """
        from app.services.prompt_builder import PromptBuilder

        try:
            prompts = PromptBuilder.build(host_id=host_id, masked=False, include_knowledge=False)
            data_text = prompts.get("user_prompt", "")
        except Exception:
            data_text = ""

        if not data_text:
            host = Host.get_by_id(host_id)
            data_text = json.dumps({
                "hostname": host.get("hostname", "") if host else "",
                "ip": host.get("ip_address", "") if host else "",
            })

        return hashlib.md5(data_text.encode("utf-8")).hexdigest()

    # ================================================================
    # 旧版辅助方法（保留向后兼容）
    # ================================================================

    @staticmethod
    def _build_analysis_prompt(host_id: int) -> str:
        """【已弃用】构建发送给AI的分析数据prompt.

        新代码请使用 PromptBuilder.build().
        """
        from app.models.analysis import (
            HostProfile, AbnormalProcess, SuspiciousConnection,
            PersistenceItem, TimelineEvent, IocHit,
        )

        warnings.warn(
            "_build_analysis_prompt() is deprecated, use PromptBuilder.build()",
            DeprecationWarning,
            stacklevel=2,
        )

        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")

        analysis_data: dict = {
            "host_basic": {
                "hostname": host.get("hostname", ""),
                "ip_address": host.get("ip_address", ""),
                "os_type": host.get("os_type", ""),
                "os_version": host.get("os_version", ""),
            },
        }

        profile = HostProfile.get_by_host(host_id)
        if profile:
            analysis_data["profile"] = {
                "system_summary": profile.get("system_summary", ""),
                "cpu_info": profile.get("cpu_info", ""),
                "memory_info": profile.get("memory_info", ""),
                "security_products": profile.get("security_products", ""),
            }

        analysis = AnalysisResult.get_by_host(host_id)
        if analysis:
            analysis_data["analysis_result"] = {
                "risk_level": analysis.get("risk_level", ""),
                "risk_score": analysis.get("risk_score", 0),
                "total_findings": analysis.get("total_findings", 0),
                "summary": analysis.get("summary", ""),
            }

        processes = AbnormalProcess.list_by_host(host_id)
        if processes:
            analysis_data["abnormal_processes"] = [
                {
                    "name": p.get("process_name"), "path": p.get("process_path"),
                    "cmd": p.get("command_line"), "reason": p.get("reason"),
                    "severity": p.get("severity"),
                }
                for p in processes[:20]
            ]

        connections = SuspiciousConnection.list_by_host(host_id)
        if connections:
            analysis_data["suspicious_connections"] = [
                {
                    "remote": f"{p.get('remote_address')}:{p.get('remote_port')}",
                    "process": p.get("process_name"), "reason": p.get("reason"),
                    "severity": p.get("severity"),
                }
                for p in connections[:20]
            ]

        persistence = PersistenceItem.list_by_host(host_id)
        if persistence:
            analysis_data["persistence_items"] = [
                {
                    "type": p.get("type"), "name": p.get("name"),
                    "command": p.get("command"), "suspicious": p.get("is_suspicious"),
                    "reason": p.get("reason"),
                }
                for p in persistence[:20]
            ]

        ioc_hits = IocHit.list_by_host(host_id)
        if ioc_hits:
            analysis_data["ioc_hits"] = [
                {
                    "type": p.get("ioc_type"), "value": p.get("ioc_value"),
                    "context": p.get("context"), "severity": p.get("severity"),
                }
                for p in ioc_hits[:20]
            ]

        timeline = TimelineEvent.list_by_host(host_id)
        if timeline:
            analysis_data["timeline"] = [
                {
                    "time": p.get("timestamp"), "type": p.get("event_type"),
                    "desc": p.get("description"), "severity": p.get("severity"),
                }
                for p in timeline[:30]
            ]

        prompt = f"""请基于以下主机取证数据和分析结果进行专业安全分析：

主机基础信息：
- 主机名: {host.get('hostname', 'N/A')}
- IP: {host.get('ip_address', 'N/A')}
- 操作系统: {host.get('os_type', 'N/A')} {host.get('os_version', 'N/A')}
- 本地风险评级: {analysis.get('risk_level', 'N/A')} (分数: {analysis.get('risk_score', 0)}/100)
- 本地分析摘要: {analysis.get('summary', '无')}

详细分析数据（JSON格式）：
{json.dumps(analysis_data, ensure_ascii=False, indent=2)}

请对以上数据进行全面的安全应急响应分析。"""

        return prompt

    @staticmethod
    def _extract_section(text: str, section_name: str) -> str:
        """【已弃用】从AI回复中提取指定章节内容.

        新代码请使用 parse_json_response().
        """
        import re

        patterns = [
            rf"##\s*{section_name}\s*\n(.*?)(?=\n##|\n###|\Z)",
            rf"###\s*{section_name}\s*\n(.*?)(?=\n##|\n###|\Z)",
            rf"\*\*{section_name}\*\*\s*\n(.*?)(?=\n\*\*|\Z)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""

    # ================================================================
    # 报告查询
    # ================================================================

    @staticmethod
    def get_report(host_id: int) -> Optional[dict]:
        """获取主机的AI分析报告."""
        return AiAnalysisReport.get_by_host(host_id)

    @staticmethod
    def delete_report(host_id: int) -> None:
        """删除主机的AI分析报告."""
        AiAnalysisReport.delete_by_host(host_id)
