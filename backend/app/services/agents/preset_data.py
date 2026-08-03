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
    # ── 11 节点真实化：10 个新 preset agent（name=runner 键=前端 NodeType 字符串）──
    {
        "name": "guard",
        "display_name": "护栏",
        "type": "custom",
        "description": "合规门禁节点：策略检查 + 显式阻断（GuardrailAgent.evaluate）",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "policy": "default",
                "checks": [{"rule": "default_policy", "detail": ""}],
                "block": False,
                "reason": "",
            }
        },
    },
    {
        "name": "hitl",
        "display_name": "人工审核",
        "type": "custom",
        "description": "人工审核节点：等待审批链决策后执行处置动作",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": True,  # 必须：_run_single L430 需 agent_def.hitl=True 才进入等待
        "config": {
            # 顶层 action/target 供 _create_hitl_approval 读取（agent_def.config.action/target）
            "action": "export_report",
            "target": {"report_type": "incident"},
            "auto_rollback_plan": {},
            "input_params": {
                "action": "export_report",
                "target": {"report_type": "incident"},
                "auto_rollback_plan": {},
                "reason": "人工审核节点",
            },
        },
    },
    {
        "name": "condition",
        "display_name": "条件分支",
        "type": "custom",
        "description": "条件分支节点：对前置输出做表达式求值，输出 branch_taken/condition_met 决策信号",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "conditions": [{"label": "默认", "expr": "true"}],
                "source": "",
            }
        },
    },
    {
        "name": "parallel",
        "display_name": "并行分支",
        "type": "custom",
        "description": "并行分支节点：纯标记，下游声明依赖本节点后由拓扑排序天然并行",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "branches": [{"label": "分支A", "target": ""}],
            }
        },
    },
    {
        "name": "data-process",
        "display_name": "数据处理",
        "type": "custom",
        "description": "数据处理节点：select/filter/rename/limit 操作链",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "source": "",
                "operations": [],
            }
        },
    },
    {
        "name": "intel-query",
        "display_name": "外部情报查询",
        "type": "custom",
        "description": "外部情报查询节点：复用 EnrichmentService 查询 ip/domain 并落库",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "ioc_type": "ip",
                "ioc_value": "",
                "provider_name": "",
            }
        },
    },
    {
        "name": "action",
        "display_name": "处置执行",
        "type": "custom",
        "description": "处置执行节点：调用 ActionService 执行 7 种处置动作（require_hitl 可走审批链）",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "action": "export_report",
                "target": {},
                "operator": "",
                "require_hitl": False,
            }
        },
    },
    {
        "name": "output",
        "display_name": "知识库",
        "type": "custom",
        "description": "知识库输出节点：复用 KnowledgeRetriever 检索安全知识",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "keyword": "",
                "category": "",
                "limit": 5,
            }
        },
    },
    {
        "name": "mcp-tool",
        "display_name": "MCP 工具",
        "type": "custom",
        "description": "MCP 工具节点：调用 ToolRegistry 单工具路径",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "tool_id": "",
                "args": {},
            }
        },
    },
    {
        "name": "intel-source",
        "display_name": "情报源接入",
        "type": "custom",
        "description": "情报源接入节点：只读 ThreatIntelProviderConfig，输出可用源列表（剔除 api_key_ref）",
        "data_sources": [],
        "depends_on": [],
        "enabled": True,
        "hitl": False,
        "config": {
            "input_params": {
                "enabled_only": True,
                "provider": "",
            }
        },
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
