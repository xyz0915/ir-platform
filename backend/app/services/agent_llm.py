"""Agent 层统一的 LLM 治理封装（薄封装）— 第①批 T-F1（§8.2）.

职责（仅做"解析 + 审计 + 脱敏 + 预算"，**不直接调用 httpx**）：
1. 解析当前激活的 AI Profile（``AiConfigProfile.get_active``）。
2. 解密 API Key（``AiService.decrypt_api_key``）。
3. 复用 ``AiService.call_llm``（其内部已包裹 ``CircuitBreaker`` + ``with_retry``）。
4. 每次调用写 ``ai_audit_log``（含 ``user_id``）。
5. 输入预算保护（``AI_INPUT_BUDGET``）。
6. 熔断 / 异常时优雅降级（返回 ``degraded=True``）。

返回结构：``{"content": str, "usage": dict, "degraded": bool, "error": Optional[str]}``
"""

import httpx
import logging
import time
from typing import Any, Optional

from app.config import settings
from app.models.ai_config import AiConfigProfile
from app.services.ai_service import AiService
from app.models.ai_audit_log import AiAuditLog
from app.shared.ai_error_mapping import map_http_error

logger = logging.getLogger(__name__)


class AgentLLM:
    """Agent / NL 检索共用的 LLM 治理封装。"""

    def __init__(self, profile: Optional[dict] = None) -> None:
        """初始化（可注入 profile，默认运行时解析激活 Profile）。"""
        self._profile = profile

    async def call(
        self,
        prompt: str,
        user: Optional[dict] = None,
        budget: int = settings.AI_INPUT_BUDGET,
    ) -> dict:
        """调用 LLM 并统一审计 / 降级。

        Args:
            prompt: 用户提示词（user_prompt）。
            user: 当前用户字典（来自 ``get_current_user``），用于审计 ``user_id``。
            budget: 输入 token 预算（默认 ``AI_INPUT_BUDGET``）。

        Returns:
            ``{"content": str, "usage": dict, "degraded": bool, "error": Optional[str]}``
        """
        user = user or {}
        user_id: Optional[int] = user.get("id")
        start_ts = time.time()

        # 1. 解析激活 Profile
        profile = self._profile or AiConfigProfile.get_active()
        if not profile or not profile.get("api_key") or not profile.get("api_base_url"):
            return self._degraded(
                error="未配置有效的 AI Profile（请先在 AI 设置中激活配置）",
                user_id=user_id,
                prompt=prompt,
                latency_ms=0,
            )

        api_base_url = profile.get("api_base_url", "")
        api_key = AiService.decrypt_api_key(profile.get("api_key", ""))
        model_name = profile.get("model_name", "gpt-4o")
        max_tokens = int(profile.get("max_tokens", 4096))
        temperature = float(profile.get("temperature", 0.3))
        system_prompt = profile.get("system_prompt", "") or "你是一个严谨的安全分析助手。"

        # 2. 输入预算保护（粗略按字符估算 1 token ≈ 1 字符，偏保守）
        if len(prompt) > budget:
            prompt = prompt[:budget]
            logger.warning("AgentLLM: prompt 长度超过预算 %d，已截断", budget)

        # 3. 复用 AiService.call_llm（已包裹熔断 + 重试）
        try:
            resp = await AiService.call_llm(
                api_base_url=api_base_url,
                api_key=api_key,
                model=model_name,
                system_prompt=system_prompt,
                user_prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except RuntimeError as exc:
            # 断路器已熔断 / 其它 RuntimeError → 优雅降级
            err_msg = "AI 服务不可用（断路器熔断）" if "断路器已熔断" in str(exc) else f"AI 调用失败: {exc}"
            logger.warning("AgentLLM: %s", err_msg)
            return self._degraded(
                error=err_msg,
                user_id=user_id,
                prompt=prompt,
                latency_ms=int((time.time() - start_ts) * 1000),
                profile=profile,
            )
        except httpx.ConnectError:
            mapped = "网络连接异常"
            logger.error("AgentLLM call failed: %s", mapped)
            return self._degraded(
                error=mapped,
                user_id=user_id,
                prompt=prompt,
                latency_ms=int((time.time() - start_ts) * 1000),
                profile=profile,
            )
        except httpx.TimeoutException:
            mapped = "AI 服务调用超时"
            logger.error("AgentLLM call failed: %s", mapped)
            return self._degraded(
                error=mapped,
                user_id=user_id,
                prompt=prompt,
                latency_ms=int((time.time() - start_ts) * 1000),
                profile=profile,
            )
        except httpx.HTTPStatusError as exc:
            try:
                mapped = map_http_error(exc)
            except Exception:
                mapped = f"AI 服务返回错误: {exc.response.status_code}"
            logger.error("AgentLLM call failed: %s", mapped)
            return self._degraded(
                error=mapped,
                user_id=user_id,
                prompt=prompt,
                latency_ms=int((time.time() - start_ts) * 1000),
                profile=profile,
            )
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            mapped = f"AI 服务内部错误: {msg}"
            logger.error("AgentLLM call failed: %s", mapped)
            return self._degraded(
                error=mapped,
                user_id=user_id,
                prompt=prompt,
                latency_ms=int((time.time() - start_ts) * 1000),
                profile=profile,
            )

        # 4. 解析响应
        choices = resp.get("choices", []) if isinstance(resp, dict) else []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "")
        usage = resp.get("usage", {}) if isinstance(resp, dict) else {}
        latency_ms = int((time.time() - start_ts) * 1000)

        # 5. 写审计日志（status=success）
        try:
            AiAuditLog.create(
                host_id=None,
                host_name="",
                profile_id=profile.get("id"),
                profile_name=profile.get("profile_name", ""),
                model_name=model_name,
                status="success",
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0),
                latency_ms=latency_ms,
                masked_mode=1 if settings.AI_MASKING_DEFAULT else 0,
                prompt=prompt,
                response=content,
                user_id=user_id,
            )
        except Exception as audit_exc:  # noqa: BLE001
            logger.warning("AgentLLM 审计写入失败: %s", audit_exc)

        return {
            "content": content,
            "usage": usage,
            "degraded": False,
            "error": None,
            "execution_duration_ms": latency_ms,
        }

    @staticmethod
    def _degraded(
        error: str,
        user_id: Optional[int] = None,
        prompt: str = "",
        latency_ms: int = 0,
        profile: Optional[dict] = None,
    ) -> dict:
        """构造降级返回并写失败审计日志。"""
        if profile:
            try:
                AiAuditLog.create(
                    host_id=None,
                    host_name="",
                    profile_id=profile.get("id"),
                    profile_name=profile.get("profile_name", ""),
                    model_name=profile.get("model_name", ""),
                    status="failed",
                    latency_ms=latency_ms,
                    masked_mode=1 if settings.AI_MASKING_DEFAULT else 0,
                    prompt=prompt,
                    response="",
                    error_message=error,
                    user_id=user_id,
                )
            except Exception as audit_exc:  # noqa: BLE001
                logger.warning("AgentLLM 降级审计写入失败: %s", audit_exc)
        return {"content": "", "usage": {}, "degraded": True, "error": error}
