"""智能体管理 Phase 2 — 预置 Agent 种子数据。

在首次启动时注入到 agent_definitions 表。
"""

import logging

logger = logging.getLogger(__name__)

PRESET_AGENTS = [
    {
        "name": "triage",
        "display_name": "分诊智能体",
        "type": "built-in",
        "description": "对安全事件进行初步分类、优先级评估和置信度预判",
        "data_sources": ["security_events", "normalized_logs"],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "file_analysis",
        "display_name": "文件分析",
        "type": "custom",
        "description": "分析可疑文件创建/写入/移动行为，关联进程上下文",
        "data_sources": ["security_events.file_create"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "process_analysis",
        "display_name": "进程分析",
        "type": "custom",
        "description": "构建进程树，分析异常进程链",
        "data_sources": ["process_events"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "network_analysis",
        "display_name": "网络分析",
        "type": "custom",
        "description": "外联 C2 分析、端口扫描检测",
        "data_sources": ["network_connection"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "registry_analysis",
        "display_name": "注册表分析",
        "type": "custom",
        "description": "Run 键、服务持久化、注册表修改分析",
        "data_sources": ["security_events.registry_modify"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "threat_intel",
        "display_name": "威胁情报",
        "type": "custom",
        "description": "IOC 匹配、恶意 IP/域名/Hash 关联",
        "data_sources": ["ioc_matches"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "timeline",
        "display_name": "时间线重建",
        "type": "custom",
        "description": "按时间轴聚合所有事件，重建攻击序列",
        "data_sources": ["process_events", "security_events"],
        "depends_on": ["triage"],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "root_cause",
        "display_name": "根因定位",
        "type": "custom",
        "description": "综合分析多个 Analyser 的输出，识别第一触发点",
        "data_sources": [],
        "depends_on": [
            "file_analysis",
            "process_analysis",
            "network_analysis",
        ],
        "enabled": True,
        "hitl": False,
    },
    {
        "name": "responder",
        "display_name": "处置建议",
        "type": "built-in",
        "description": "生成可逆、低危的处置建议，触发 HITL 审批门",
        "data_sources": [],
        "depends_on": ["root_cause"],
        "enabled": True,
        "hitl": True,
    },
    {
        "name": "reporter",
        "display_name": "报告输出",
        "type": "built-in",
        "description": "汇总所有分析阶段的结果，生成复盘报告",
        "data_sources": [],
        "depends_on": ["responder"],
        "enabled": True,
        "hitl": False,
    },
]


def seed_preset_agents(registry) -> int:
    """将预置 Agent 注入注册表（仅首次运行）。

    Args:
        registry: AgentRegistry 实例。

    Returns:
        注入的 Agent 数量（跳过已存在的则不计入）。
    """
    from app.models.agent_definition import AgentDefinitionModel
    from app.services.agents.agent_definition import AgentDefinition

    count = 0
    for data in PRESET_AGENTS:
        existing = AgentDefinitionModel.get(data["name"])
        if existing:
            logger.debug("Preset agent '%s' already exists, skipping", data["name"])
            continue
        agent_def = AgentDefinition.from_dict(data)
        registry.register(agent_def)
        count += 1
    logger.info("Seeded %d preset agents into registry", count)
    return count
