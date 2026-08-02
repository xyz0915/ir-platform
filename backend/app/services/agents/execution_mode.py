"""智能体执行模式判定 — P2 新建/编辑校验提示的单一事实来源。

设计依据：``custom-agent/design.md`` §4.1（P2 详细设计）。

- ``KNOWN_RUNNER_TYPES``：与 ``PipelineEngine._get_node_runner`` 的 key 对齐
  （7 个应急响应节点 + branch + llm + trigger + guardrail）。
- ``BUILTIN_AGENT_NAMES``：真实执行体 Agent 类（triage / responder / reporter）。
- ``ALL_KNOWN_TYPES``：全部已知类型（name ∈ 该集合 → 走内置真实逻辑）。
- ``classify_execution_mode`` / ``build_agent_warning``：供 create/update 接口返回
  顶层 ``warning`` 字段，向后兼容（既有消费方只读 code/data/message）。

⚠️ 前端 ``frontend/src/constants/agentRuntime.js`` 镜像本模块的
``ALL_KNOWN_TYPES``（共享知识 #4），修改此处时必须同步前端。
"""

from typing import Any

# 已知运行类型（与 pipeline_engine._get_node_runner 的 key 对齐）
KNOWN_RUNNER_TYPES = {
    "file_analysis",
    "process_analysis",
    "network_analysis",
    "registry_analysis",
    "timeline",
    "root_cause",
    "threat_intel",
    "branch",
    "llm",
    "trigger",
    "guardrail",
}

# 内置 Agent 类（真实执行体）
BUILTIN_AGENT_NAMES = {"triage", "responder", "reporter"}

# 全部已知类型（用于 P2 判定）
ALL_KNOWN_TYPES = KNOWN_RUNNER_TYPES | BUILTIN_AGENT_NAMES


def classify_execution_mode(name: str, tools: Any, model_profile: Any) -> str:
    """返回执行模式：'real' | 'custom-real' | 'summary'。

    Args:
        name: 智能体名称（唯一标识）。
        tools: 关联工具列表（tool_id 列表，可空）。
        model_profile: 关联模型 Profile（profile_id 字符串，可空）。

    Returns:
        - ``"real"``: name 属于内置已知类型 → 走内置真实逻辑；
        - ``"custom-real"``: 未知类型但配置了 tools 或 model_profile →
          运行时真实调用工具/LLM；
        - ``"summary"``: 未知类型且无 tools/model_profile → 静态摘要兜底。
    """
    if name in ALL_KNOWN_TYPES:
        return "real"
    if tools or model_profile:
        return "custom-real"
    return "summary"


def build_agent_warning(name: str, tools: Any, model_profile: Any) -> str:
    """构造创建/更新智能体的 warning 文案；无需提示时返回 ``''``。

    Args:
        name: 智能体名称。
        tools: 关联工具列表（tool_id 列表，可空）。
        model_profile: 关联模型 Profile（profile_id 字符串，可空）。

    Returns:
        warning 文案；name 属于已知类型时返回空字符串（不提示）。
    """
    mode = classify_execution_mode(name, tools, model_profile)
    if mode == "real":
        return ""
    if mode == "custom-real":
        return (
            f"智能体 '{name}' 不属于内置运行类型，将按【自定义执行】模式运行："
            f"已关联 {len(tools or [])} 个工具/模型 Profile，运行时真实调用（失败不阻断）。"
        )
    return (
        f"智能体 '{name}' 不属于已知运行类型（file_analysis/process_analysis/…），"
        f"运行时将走【摘要模式】：仅输出静态摘要。建议配置关联工具或模型 Profile 获得真实分析能力。"
    )
