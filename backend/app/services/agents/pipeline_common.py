"""DAG 流水线共享常量与纯函数工具（T01 基础设施）。

设计依据：``deliverables/software-company/dag-fix/design.md`` §8 共享知识。

提供：
- ``HITL_WAIT_TIMEOUT`` / ``HITL_EXPIRE_TTL``：HITL 等待超时与清理 TTL（环境变量可覆盖）；
- ``compute_final_status(run)``：收尾状态优先级（cancelled > failed > waiting_hitl > completed）；
- ``_stable_dict(obj)``：任意对象归一化为稳定 JSON 结构（缓存键用）；
- ``_safe_sse(on_sse, event_type, data)``：SSE 回调安全包装（协程内异常仅记录日志）。
"""

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# HITL 等待超时：进程存活但无人审批时的强制闭环上界，默认 1800s（30 分钟）。
# 环境变量 IR_HITL_WAIT_TIMEOUT 覆盖（秒）。
HITL_WAIT_TIMEOUT: float = float(os.environ.get("IR_HITL_WAIT_TIMEOUT", "1800"))

# waiting_hitl 清理 TTL：进程崩溃后残留记录的兜底清理，默认 86400s（24 小时）。
# 环境变量 IR_HITL_EXPIRE_TTL 覆盖（秒）。
HITL_EXPIRE_TTL: float = float(os.environ.get("IR_HITL_EXPIRE_TTL", "86400"))


def compute_final_status(run) -> str:
    """计算管道收尾状态（P1-3）。

    优先级：``cancelled > failed > waiting_hitl > completed``。

    Args:
        run: PipelineRun 实例（含 ``cancelled`` 标志与 ``stages`` 列表）。

    Returns:
        ``"cancelled" | "failed" | "waiting_hitl" | "completed"``。
    """
    if getattr(run, "cancelled", False):
        return "cancelled"
    stages = getattr(run, "stages", None) or []
    if any(s.get("status") == "failed" for s in stages):
        return "failed"
    if any(s.get("status") == "waiting_hitl" for s in stages):
        return "waiting_hitl"  # 防御：正常 await 后不应出现
    return "completed"


def _stable_dict(obj: Any) -> Any:
    """归一化任意对象为稳定的 JSON 结构（缓存键哈希用，P2-1）。

    - dict：递归处理值，键转 str（保持可 JSON 化）；
    - list / tuple：递归处理元素；
    - set：排序后递归（保证同一集合哈希一致）；
    - 其余（str/int/float/bool/None）：原样返回。

    CacheManager._make_key 内部会 ``json.dumps(sort_keys=True)``，
    因此只需保证嵌套结构可序列化、顺序稳定即可。
    """
    if isinstance(obj, dict):
        return {str(k): _stable_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stable_dict(v) for v in obj]
    if isinstance(obj, set):
        return sorted(
            (_stable_dict(v) for v in obj),
            key=lambda x: _json_sort_key(x),
        )
    return obj


def _json_sort_key(value: Any) -> str:
    """set 元素排序键（保证确定性）。"""
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


async def _safe_sse(on_sse: Callable, event_type: str, data: dict) -> None:
    """SSE 回调安全包装（P2-5）。

    协程内异常仅 ``logger.exception`` 记录，不向上抛出——避免推送失败
    破坏管道主流程（此前 ``except: pass`` 使异常不可观测）。
    """
    try:
        await on_sse(event_type, data)
    except Exception:
        logger.exception("PipelineEngine SSE 回调异常 event=%s", event_type)
