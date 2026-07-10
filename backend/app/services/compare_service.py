"""多主机对比分析服务 — 组装多主机数据后调用 LLM 进行四维度对比.

支持异步执行 + SSE 流式推送.
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from app.models.ai_config import AiConfigProfile
from app.models.ai_task import AiTask
from app.models.host import Host
from app.services.prompt_builder import PromptBuilder
from app.shared.ai_constants import TaskStatus

logger = logging.getLogger(__name__)


class CompareService:
    """多主机对比分析服务.

    比较 2-5 台主机在风险等级、威胁类型、攻击路径、处置建议四个维度的异同.
    """

    # 进程级流队列
    _task_streams: dict[str, asyncio.Queue] = {}
    _cancel_flags: dict[str, asyncio.Event] = {}

    _COMPARE_SYSTEM_PROMPT: str = """你是一个专业的网络安全应急响应分析专家。请对以下多台主机的取证数据进行横向对比分析。

请严格按照以下 JSON 格式输出，不要添加任何额外的解释说明：

```json
{
  "overview": {
    "total_hosts": 主机数量,
    "summary": "整体对比概述（200字以内）"
  },
  "risk_comparison": {
    "description": "风险等级对比分析",
    "hosts": [
      {"host_id": 主机ID, "hostname": "主机名", "risk_level": "风险等级", "risk_score": 分数, "analysis": "分析"}
    ]
  },
  "threat_comparison": {
    "description": "威胁类型对比分析",
    "common_threats": ["共同威胁1", "共同威胁2"],
    "unique_threats": {"主机ID": ["特有威胁1"]}
  },
  "attack_path_comparison": {
    "description": "攻击路径对比分析",
    "similarities": "相似点描述",
    "differences": "差异点描述"
  },
  "recommendation_comparison": {
    "description": "处置建议对比分析",
    "common_recommendations": ["共同建议1", "共同建议2"],
    "host_specific": {"主机ID": ["针对建议1"]}
  }
}
```

分析要求：
1. 识别多台主机间是否存在协同攻击模式（如横向移动、C2 信标同步等）
2. 对比 IOC 命中、异常进程、可疑外连的共性和差异
3. 给出系统性的加固建议
4. 用中文输出所有分析内容"""

    @classmethod
    async def compare_hosts(cls, host_ids: list[int]) -> dict:
        """提交多主机对比分析任务.

        Args:
            host_ids: 要对比的主机ID列表（2-5个）.

        Returns:
            {"task_id": int, "host_ids": list, "status": str, "message": str}

        Raises:
            ValueError: 主机数量不符合要求或主机不存在.
        """
        if len(host_ids) < 2:
            raise ValueError("至少需要选择 2 台主机进行对比")
        if len(host_ids) > 5:
            raise ValueError("最多支持 5 台主机进行对比")

        # 验证主机存在
        for hid in host_ids:
            host = Host.get_by_id(hid)
            if not host:
                raise ValueError(f"主机 {hid} 不存在")

        # 创建任务记录（使用一个临时占位 host_id = host_ids[0]）
        task = AiTask.create(
            host_id=host_ids[0],
            profile_id=None,
            masked_mode=0,
        )
        task_id_str = str(task["id"])
        cls._task_streams[task_id_str] = asyncio.Queue()
        cls._cancel_flags[task_id_str] = asyncio.Event()

        # 启动后台执行
        asyncio.create_task(cls._execute_compare(task["id"], host_ids))

        return {
            "task_id": task["id"],
            "host_ids": host_ids,
            "status": TaskStatus.PENDING.value,
            "message": "对比分析任务已提交",
        }

    @classmethod
    async def stream_events(cls, task_id: int) -> AsyncGenerator[dict, None]:
        """SSE 事件流 — 用于前端实时显示对比进度.

        Args:
            task_id: 任务ID.

        Yields:
            事件字典.
        """
        task_id_str = str(task_id)
        queue = cls._task_streams.get(task_id_str)

        if queue is None:
            task = AiTask.get_by_id(task_id)
            if task:
                if task["status"] == TaskStatus.COMPLETED.value:
                    yield {"event": "complete", "data": {
                        "progress": 100,
                        "message": "对比分析完成",
                        "result": json.loads(task.get("progress_message", "{}")),
                    }}
                elif task["status"] == TaskStatus.FAILED.value:
                    yield {"event": "error", "data": {
                        "message": task.get("error_message", "对比失败"),
                    }}
            yield {"event": "done", "data": {"message": "stream ended"}}
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
                if event["event"] == "done":
                    break
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": {"timestamp": time.time()}}

    @classmethod
    async def _execute_compare(cls, task_id: int, host_ids: list[int]) -> None:
        """后台执行对比分析.

        Args:
            task_id: 任务ID.
            host_ids: 主机ID列表.
        """
        task_id_str = str(task_id)
        queue = cls._task_streams.get(task_id_str)
        cancel_event = cls._cancel_flags.get(task_id_str)

        try:
            # --- 阶段1: 组装数据 ---
            await cls._push_stage(task_id_str, task_id, "assembling", 10, "正在组装多主机数据...")

            hosts_data: list[dict] = []
            for hid in host_ids:
                host = Host.get_by_id(hid)
                if not host:
                    continue
                prompts = PromptBuilder.build(host_id=hid, masked=False)
                hosts_data.append({
                    "host_id": hid,
                    "hostname": host.get("hostname", ""),
                    "ip_address": host.get("ip_address", ""),
                    "os_type": host.get("os_type", ""),
                    "user_prompt": prompts["user_prompt"],
                })

            # --- 阶段2: 调用 LLM ---
            await cls._push_stage(task_id_str, task_id, "calling", 40, "正在调用AI模型进行对比分析...")

            if cancel_event and cancel_event.is_set():
                await cls._fail_compare(task_id, "任务已被用户取消")
                return

            # 获取配置
            profile = AiConfigProfile.get_active()
            if not profile:
                raise ValueError("未找到有效的AI配置")

            from app.services.ai_service import AiService

            api_key = AiService.decrypt_api_key(profile["api_key"])
            api_base_url = profile["api_base_url"].rstrip("/")
            model_name = profile.get("model_name", "gpt-4o")
            max_tokens = profile.get("max_tokens", 4096)

            # 构建对比 prompt
            compare_user_prompt = cls._build_compare_prompt(hosts_data)

            # 流式调用
            full_content = ""
            async for chunk in AiService.call_llm_stream(
                api_base_url=api_base_url,
                api_key=api_key,
                model=model_name,
                system_prompt=cls._COMPARE_SYSTEM_PROMPT,
                user_prompt=compare_user_prompt,
                max_tokens=max_tokens,
                temperature=profile.get("temperature", 0.3),
            ):
                if cancel_event and cancel_event.is_set():
                    await cls._fail_compare(task_id, "任务已被用户取消")
                    return

                content = chunk.get("content", "")
                if content:
                    full_content += content
                if queue:
                    try:
                        queue.put_nowait({"event": "content", "data": {"content": content}})
                    except asyncio.QueueFull:
                        pass

            # --- 阶段3: 解析和保存 ---
            await cls._push_stage(task_id_str, task_id, "saving", 90, "正在保存对比结果...")

            result = cls._parse_compare_json(full_content)

            # 保存结果到任务的 progress_message（JSON 格式）
            result_json = json.dumps(result, ensure_ascii=False)
            AiTask.update_status(
                task_id=task_id,
                status=TaskStatus.COMPLETED.value,
                progress=100,
                progress_message=result_json,
            )

            if queue:
                try:
                    queue.put_nowait({"event": "complete", "data": {
                        "progress": 100,
                        "message": "对比分析完成",
                        "result": result,
                    }})
                except asyncio.QueueFull:
                    pass

            logger.info("Compare task %d completed for hosts %s", task_id, host_ids)

        except Exception as e:
            logger.exception("Compare task %d failed: %s", task_id, e)
            await cls._fail_compare(task_id, str(e))

        finally:
            if queue:
                try:
                    await asyncio.sleep(0.5)  # 确保 complete 事件先被消费
                    queue.put_nowait({"event": "done", "data": {"message": "stream ended"}})
                except asyncio.QueueFull:
                    pass

    @classmethod
    async def _push_stage(
        cls,
        task_id_str: str,
        task_id: int,
        stage: str,
        progress: int,
        message: str,
    ) -> None:
        """推送进度阶段事件."""
        queue = cls._task_streams.get(task_id_str)
        AiTask.update_status(
            task_id=task_id,
            status=TaskStatus.RUNNING.value,
            progress=progress,
            progress_message=message,
        )
        if queue:
            try:
                queue.put_nowait({"event": "progress", "data": {
                    "progress": progress,
                    "message": message,
                    "stage": stage,
                }})
            except asyncio.QueueFull:
                pass

    @classmethod
    async def _fail_compare(cls, task_id: int, error_message: str) -> None:
        """标记对比任务为失败."""
        AiTask.update_status(
            task_id=task_id,
            status=TaskStatus.FAILED.value,
            progress_message=error_message,
            error_message=error_message,
        )
        queue = cls._task_streams.get(str(task_id))
        if queue:
            try:
                queue.put_nowait({"event": "error", "data": {"message": error_message}})
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _build_compare_prompt(hosts_data: list[dict]) -> str:
        """构建对比分析的用户 prompt."""
        parts: list[str] = ["请对以下多台主机的取证数据进行横向对比分析：\n"]

        for i, hd in enumerate(hosts_data, 1):
            parts.append(f"=== 主机{i}: {hd['hostname']} (ID={hd['host_id']}, {hd['ip_address']}) ===")
            # 截取关键数据（避免超长）
            user_prompt = hd.get("user_prompt", "")
            if len(user_prompt) > 3000:
                user_prompt = user_prompt[:3000] + "\n...(数据已截断)"
            parts.append(user_prompt)
            parts.append("")

        parts.append("请基于以上数据，从风险等级、威胁类型、攻击路径、处置建议四个维度进行横向对比分析。")
        return "\n".join(parts)

    @staticmethod
    def _parse_compare_json(content: str) -> dict:
        """解析 LLM 返回的对比 JSON."""
        default = {
            "overview": {"total_hosts": 0, "summary": ""},
            "risk_comparison": {"description": "", "hosts": []},
            "threat_comparison": {"description": "", "common_threats": [], "unique_threats": {}},
            "attack_path_comparison": {"description": "", "similarities": "", "differences": ""},
            "recommendation_comparison": {"description": "", "common_recommendations": [], "host_specific": {}},
        }
        if not content:
            return default

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
        else:
            brace_start = content.find("{")
            brace_end = content.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                json_str = content[brace_start:brace_end + 1]

        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning("Failed to parse compare JSON")

        return default
