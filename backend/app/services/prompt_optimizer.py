"""提示词自动优化器 — 调用 LLM 对现有提示词进行反馈驱动的优化.

每次优化保存为历史版本（最多 5 个），版本号自动递增.
"""

import json
import logging
from typing import Any, Optional

import httpx

from app.models.ai_config import AiConfigProfile, AiPromptVersion

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """提示词自动优化器.

    根据用户反馈调用 LLM 对现有 system_prompt 进行优化，
    优化结果保存到 ai_prompt_versions 表供历史追踪.
    """

    @staticmethod
    async def optimize(
        current_prompt: str,
        feedback: str,
        profile_id: Optional[int] = None,
    ) -> dict:
        """调用 LLM 优化提示词.

        流程：
        1. 获取 Profile 配置（API Key 等）
        2. 构建优化请求（让 LLM 基于当前 prompt + feedback 生成改进版）
        3. 调用 LLM
        4. 保存新版本到 ai_prompt_versions（最多保留 5 个历史版本）
        5. 返回优化结果

        Args:
            current_prompt: 当前提示词内容.
            feedback: 用户反馈/优化期望.
            profile_id: 使用的 AI Profile ID（None 则用激活配置）.

        Returns:
            {"optimized_prompt": str, "version": int, "changes": str}

        Raises:
            ValueError: 配置不完整或调用失败.
        """
        # 1. 获取配置
        if profile_id:
            profile = AiConfigProfile.get_by_id(profile_id)
        else:
            profile = AiConfigProfile.get_active()

        if not profile:
            raise ValueError("未找到有效的AI配置")
        if not profile.get("api_base_url") or not profile.get("api_key"):
            raise ValueError("API 配置不完整")

        # 2. 解密 API Key
        from app.services.ai_service import AiService

        try:
            api_key = AiService.decrypt_api_key(profile["api_key"])
        except Exception as e:
            raise ValueError(f"API Key 解密失败: {e}")

        api_base_url = profile["api_base_url"].rstrip("/")
        model_name = profile.get("model_name", "gpt-4o")

        # 3. 构建优化 prompt
        optimizer_system = """你是一个专业的提示词工程师。你的任务是优化给定的系统提示词。

请根据用户的反馈对提示词进行改进，使其更清晰、更精准、更有效。

输出格式为 JSON：
```json
{
  "optimized_prompt": "优化后的完整提示词",
  "changes": "用中文简要说明做了哪些修改"
}
```

优化原则：
1. 保持原有的分析框架和输出格式要求
2. 根据反馈增加或调整具体的分析指导
3. 使提示词更具体、更可操作
4. 不要随意删除原有的重要约束条件"""

        optimizer_user = f"""当前提示词：
---START---
{current_prompt}
---END---

用户反馈：{feedback}

请优化上述提示词并根据反馈进行改进。"""

        # 4. 调用 LLM
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": optimizer_system},
                {"role": "user", "content": optimizer_user},
            ],
            "max_tokens": 4096,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        url = api_base_url + "/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                llm_response = resp.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"LLM 调用失败 (HTTP {e.response.status_code}): {e.response.text[:200]}")
        except httpx.TimeoutException:
            raise ValueError("LLM 调用超时")
        except httpx.ConnectError:
            raise ValueError("无法连接 AI 服务")

        # 5. 解析 LLM 回复
        choices = llm_response.get("choices", [])
        if not choices:
            raise ValueError("LLM 返回空结果")

        content = choices[0].get("message", {}).get("content", "")

        # 尝试 JSON 解析
        try:
            # 可能包裹在 ```json 中
            json_str = content
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

            parsed = json.loads(json_str)
            optimized_prompt = parsed.get("optimized_prompt", current_prompt)
            changes = parsed.get("changes", "优化完成")
        except (json.JSONDecodeError, KeyError):
            # 如果解析失败，直接使用原始回复作为优化后的 prompt
            optimized_prompt = content.strip()
            changes = "LLM 优化完成（非 JSON 格式）"

        if not optimized_prompt or optimized_prompt == current_prompt:
            raise ValueError("LLM 未生成有效的优化结果")

        # 6. 保存版本
        effective_profile_id = profile_id or profile["id"]
        version_record = AiPromptVersion.create(
            profile_id=effective_profile_id,
            content=optimized_prompt,
        )

        # 7. 清理旧版本（保留最新 5 个）
        AiPromptVersion.clean_old_versions(effective_profile_id, keep=5)

        logger.info(
            "Prompt optimized: profile_id=%d, version=%d",
            effective_profile_id,
            version_record["version"],
        )

        return {
            "optimized_prompt": optimized_prompt,
            "version": version_record["version"],
            "changes": changes,
        }
