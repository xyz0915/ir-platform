"""AI分析服务 — 大模型API调用与报告生成."""

import json
import logging
import base64
from typing import Any, Optional

import httpx

from app.config import settings
from app.models.ai_config import AiConfig
from app.models.ai_analysis import AiAnalysisReport
from app.models.host import Host
from app.models.analysis import (
    AnalysisResult, HostProfile, AbnormalProcess,
    SuspiciousConnection, PersistenceItem, TimelineEvent, IocHit,
)

logger = logging.getLogger(__name__)

# 默认系统提示词
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

    @staticmethod
    def get_config() -> Optional[dict]:
        """获取AI配置（API Key脱敏）."""
        config = AiConfig.get()
        if not config:
            return None
        # 脱敏API Key
        masked_key = AiService.mask_api_key(config.get("api_key", ""))
        result = dict(config)
        result["api_key_masked"] = masked_key
        # 不返回原始api_key
        del result["api_key"]
        return result

    @staticmethod
    def save_config(data: dict) -> dict:
        """保存AI配置（加密API Key后存储）."""
        api_key_plain = data.get("api_key", "")
        encrypted_key = AiService.encrypt_api_key(api_key_plain) if api_key_plain else ""
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
        """开启/关闭AI功能."""
        if enabled == 1:
            # 开启前检查配置是否完整
            config = AiConfig.get()
            if not config:
                raise ValueError("请先配置AI参数（API地址和密钥）")
            if not config.get("api_base_url") or not config.get("api_key"):
                raise ValueError("API地址和密钥不能为空")
        result = AiConfig.update_enabled(enabled)
        return AiService.get_config()

    @staticmethod
    def _build_analysis_prompt(host_id: int) -> str:
        """构建发送给AI的分析数据prompt."""
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")

        # 组装分析数据
        analysis_data = {
            "host_basic": {
                "hostname": host.get("hostname", ""),
                "ip_address": host.get("ip_address", ""),
                "os_type": host.get("os_type", ""),
                "os_version": host.get("os_version", ""),
            },
        }

        # 画像
        profile = HostProfile.get_by_host(host_id)
        if profile:
            analysis_data["profile"] = {
                "system_summary": profile.get("system_summary", ""),
                "cpu_info": profile.get("cpu_info", ""),
                "memory_info": profile.get("memory_info", ""),
                "security_products": profile.get("security_products", ""),
            }

        # 分析结果
        analysis = AnalysisResult.get_by_host(host_id)
        if analysis:
            analysis_data["analysis_result"] = {
                "risk_level": analysis.get("risk_level", ""),
                "risk_score": analysis.get("risk_score", 0),
                "total_findings": analysis.get("total_findings", 0),
                "summary": analysis.get("summary", ""),
            }

        # 异常进程
        processes = AbnormalProcess.list_by_host(host_id)
        if processes:
            analysis_data["abnormal_processes"] = [
                {"name": p.get("process_name"), "path": p.get("process_path"),
                 "cmd": p.get("command_line"), "reason": p.get("reason"),
                 "severity": p.get("severity")}
                for p in processes[:20]  # 限制数量避免prompt过长
            ]

        # 可疑外连
        connections = SuspiciousConnection.list_by_host(host_id)
        if connections:
            analysis_data["suspicious_connections"] = [
                {"remote": f"{p.get('remote_address')}:{p.get('remote_port')}",
                 "process": p.get("process_name"), "reason": p.get("reason"),
                 "severity": p.get("severity")}
                for p in connections[:20]
            ]

        # 持久化痕迹
        persistence = PersistenceItem.list_by_host(host_id)
        if persistence:
            analysis_data["persistence_items"] = [
                {"type": p.get("type"), "name": p.get("name"),
                 "command": p.get("command"), "suspicious": p.get("is_suspicious"),
                 "reason": p.get("reason")}
                for p in persistence[:20]
            ]

        # IOC命中
        ioc_hits = IocHit.list_by_host(host_id)
        if ioc_hits:
            analysis_data["ioc_hits"] = [
                {"type": p.get("ioc_type"), "value": p.get("ioc_value"),
                 "context": p.get("context"), "severity": p.get("severity")}
                for p in ioc_hits[:20]
            ]

        # 时间线
        timeline = TimelineEvent.list_by_host(host_id)
        if timeline:
            analysis_data["timeline"] = [
                {"time": p.get("timestamp"), "type": p.get("event_type"),
                 "desc": p.get("description"), "severity": p.get("severity")}
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
    async def call_llm(api_base_url: str, api_key: str, model: str,
                       system_prompt: str, user_prompt: str,
                       max_tokens: int, temperature: float) -> dict:
        """调用 OpenAI-compatible 格式的 LLM API.

        兼容部分新模型/代理网关对 token 参数名的差异：
        - 传统 chat completions: max_tokens
        - 新接口/部分网关: max_output_tokens
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
                    logger.warning("LLM gateway rejected max_output_tokens expectation mismatch; retrying with max_output_tokens")
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
    async def analyze_with_ai(host_id: int) -> dict:
        """一键AI分析 — 组装数据、调用LLM、保存报告.

        Args:
            host_id: 主机ID.

        Returns:
            AI分析报告字典.

        Raises:
            ValueError: AI功能未开启或配置不完整.
        """
        # 1. 检查AI是否开启
        config = AiConfig.get()
        if not config or config.get("enabled") != 1:
            raise ValueError("AI分析功能未开启，请在AI设置中手动开启")
        if not config.get("api_base_url") or not config.get("api_key"):
            raise ValueError("API配置不完整")

        # 2. 检查主机是否已完成本地分析
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

        # 4. 构建prompt
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
            raise ValueError(f"AI服务调用失败 (HTTP {e.response.status_code}): {e.response.text[:200]}")
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

        # 7. 尝试按结构化格式提取各部分
        risk_assessment = AiService._extract_section(ai_content, "风险评估")
        threat_analysis = AiService._extract_section(ai_content, "威胁分析")
        timeline_analysis = AiService._extract_section(ai_content, "时间线解读")
        recommendations = AiService._extract_section(ai_content, "处置建议")

        # 8. 获取主机关联的案件ID
        case_id = host.get("case_id", 0)

        # 9. 保存AI报告
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

        logger.info("AI analysis completed for host %d: model=%s, tokens=%d",
                     host_id, model_name, tokens_used)
        return report

    @staticmethod
    def _extract_section(text: str, section_name: str) -> str:
        """从AI回复中提取指定章节内容."""
        # 支持多种标题格式: ## 风险评估, ### 风险评估, **风险评估**
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

    @staticmethod
    def get_report(host_id: int) -> Optional[dict]:
        """获取主机的AI分析报告."""
        return AiAnalysisReport.get_by_host(host_id)

    @staticmethod
    def delete_report(host_id: int) -> None:
        """删除主机的AI分析报告."""
        AiAnalysisReport.delete_by_host(host_id)
