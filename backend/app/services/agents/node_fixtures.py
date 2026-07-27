"""节点模拟（simulate）硬编码 fixture — Q-1 选项 (a)。

每个节点类型对应一个 ``SIMULATE_<NODE>`` 常量，结构与被真实模式
``_run_<node>`` 的返回同构：``{output_text, structured, confidence, evidence}``。
``get_fixture(node_type, node_name)`` 按节点类型返回对应的合成结果，
供 ``PipelineEngine.execute_node(mode="simulate")`` 直接复用，零外部 IO。

设计依据：02-design.md §4.2 表（各节点 structured 最小字段集）。
"""

# ──────────────────────────────────────────────────────────────────────
# 7 个应急响应节点 + branch + llm + trigger(分诊) 的合成数据
# ──────────────────────────────────────────────────────────────────────

SIMULATE_FILE_ANALYSIS = {
    "output_text": (
        "# 文件分析报告\n"
        "检测到 3 条文件创建事件（命中规则）：\n"
        "  📄 ransom_note.txt\n     路径: C:\\Users\\victim\\Desktop\\ransom_note.txt\n"
        "     命中规则: T1486_file_encryption\n"
        "  📄 config.bin\n     路径: C:\\ProgramData\\evil\\config.bin\n"
        "  📄 payload.dll\n     路径: C:\\Windows\\Temp\\payload.dll"
    ),
    "structured": {
        "count": 3,
        "files": [
            {
                "file_name": "ransom_note.txt",
                "path": "C:\\Users\\victim\\Desktop\\ransom_note.txt",
                "matched_rules": ["T1486_file_encryption"],
            },
            {
                "file_name": "config.bin",
                "path": "C:\\ProgramData\\evil\\config.bin",
                "matched_rules": [],
            },
            {
                "file_name": "payload.dll",
                "path": "C:\\Windows\\Temp\\payload.dll",
                "matched_rules": ["T1059_script"],
            },
        ],
        "summary": "在受感染主机上发现勒索信、加密配置与可疑 DLL，疑似勒索软件投放。",
    },
    "confidence": 0.75,
    "evidence": [
        {"type": "file_events", "ref": "security_events.id=12", "file_name": "ransom_note.txt"},
        {"type": "file_events", "ref": "security_events.id=14", "file_name": "payload.dll"},
    ],
}

SIMULATE_PROCESS_ANALYSIS = {
    "output_text": (
        "# 进程分析报告\n共记录 4 个进程事件。\n\n"
        "## 进程树分析\n\n  powershell.exe → 3 个子进程\n"
        "      ├─ rundll32.exe (PID=2241)\n"
        "      ├─ cmd.exe (PID=2290)\n"
        "      └─ wscript.exe (PID=2305)"
    ),
    "structured": {
        "process_count": 4,
        "tree": [
            {"parent": "powershell.exe", "child": "rundll32.exe", "pid": 2241},
            {"parent": "powershell.exe", "child": "cmd.exe", "pid": 2290},
            {"parent": "powershell.exe", "child": "wscript.exe", "pid": 2305},
        ],
        "suspicious": [
            {
                "process_name": "rundll32.exe",
                "pid": 2241,
                "cmd": "rundll32.exe C:\\ProgramData\\evil\\config.bin",
            },
        ],
        "summary": "powershell 拉起 rundll32/cmd/wscript，符合无文件攻击链特征。",
    },
    "confidence": 0.7,
    "evidence": [
        {"type": "process_events", "ref": "process_events.id=881", "process_name": "rundll32.exe", "pid": 2241},
    ],
}

SIMULATE_NETWORK_ANALYSIS = {
    "output_text": (
        "# 网络连接分析报告\n共记录 5 条网络连接。\n\n"
        "## 威胁连接: 2 条\n"
        "  🔴 10.0.0.15:49158 → 185.220.101.32:443 (tcp)\n"
        "     进程: rundll32.exe  威胁: high\n"
        "## 外网连接: 3 条\n"
        "  10.0.0.15:51002 → 91.219.236.18:8080"
    ),
    "structured": {
        "connection_count": 5,
        "threat_connections": [
            {
                "local_addr": "10.0.0.15",
                "remote_addr": "185.220.101.32",
                "process_name": "rundll32.exe",
                "threat_level": "high",
            },
        ],
        "external_connections": [
            {"local_addr": "10.0.0.15", "remote_addr": "185.220.101.32"},
            {"local_addr": "10.0.0.15", "remote_addr": "91.219.236.18"},
        ],
        "summary": "检测到与已知 Tor 出口节点建立的高危外联，疑似 C2 通信。",
    },
    "confidence": 0.75,
    "evidence": [
        {
            "type": "network_connection",
            "ref": "network_connections.id=551",
            "local_addr": "10.0.0.15",
            "remote_addr": "185.220.101.32",
        },
    ],
}

SIMULATE_REGISTRY_ANALYSIS = {
    "output_text": (
        "# 注册表/持久化分析报告\n检测到 2 条注册表相关安全事件。\n\n"
        "## 按规则分组:\n\n"
        "  ⚠️ persistence_run_key — 1 次命中\n"
        "     详情: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater"
    ),
    "structured": {
        "count": 2,
        "rule_groups": [
            {"rule_name": "persistence_run_key", "hits": 1},
            {"rule_name": "persistence_scheduled_task", "hits": 1},
        ],
        "summary": "在 Run 键值与计划任务中均发现可疑自启动项。",
    },
    "confidence": 0.8,
    "evidence": [
        {
            "type": "registry_events",
            "ref": "security_events.id=31",
            "detail": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater",
        },
    ],
}

SIMULATE_TIMELINE = {
    "output_text": (
        "# 事件时间线\n共 4 个时间节点：\n"
        "  🔴 2026-07-06T09:12:01 [high] file_create\n     规则: T1486_file_encryption\n"
        "  🟡 2026-07-06T09:13:40 [medium] process_start\n"
        "  🔴 2026-07-06T09:14:22 [high] network_outbound\n"
        "  🟡 2026-07-06T09:15:05 [medium] registry_modify"
    ),
    "structured": {
        "count": 4,
        "events": [
            {"timestamp": "2026-07-06T09:12:01", "event_type": "file_create", "severity": "high", "rule_name": "T1486_file_encryption"},
            {"timestamp": "2026-07-06T09:13:40", "event_type": "process_start", "severity": "medium", "rule_name": "T1059_script"},
            {"timestamp": "2026-07-06T09:14:22", "event_type": "network_outbound", "severity": "high", "rule_name": "T1071_c2"},
            {"timestamp": "2026-07-06T09:15:05", "event_type": "registry_modify", "severity": "medium", "rule_name": "T1547_registry"},
        ],
        "summary": "从文件落地、进程拉起、外联到持久化的完整攻击链时间线。",
    },
    "confidence": 0.7,
    "evidence": [],
}

SIMULATE_ROOT_CAUSE = {
    "output_text": (
        "## 根因分析\n\n"
        "第一触发点为 **powershell.exe 下载并执行了加密载荷**（2026-07-06T09:12:01）。\n"
        "攻击链路：投递 → 持久化(Run 键) → C2 外联 → 文件加密。\n"
        "受影响资产：主机 host-abc123（域成员，承载财务共享）。"
    ),
    "structured": {
        "root_cause": "powershell.exe 下载并执行了加密载荷",
        "attack_chain": [
            "投递（file_create）",
            "持久化（registry_modify / Run 键）",
            "C2 外联（network_outbound）",
            "加密（file_create / ransom_note）",
        ],
        "affected_assets": ["host-abc123"],
        "summary": "钓鱼文档触发 powershell 下载载荷，建立 C2 后加密文件。",
        "used_llm": True,
    },
    "confidence": 0.85,
    "evidence": [],
}

SIMULATE_THREAT_INTEL = {
    "output_text": (
        "# 威胁情报关联分析\n命中 2 条 IOC。\n\n"
        "## IOC 匹配结果\n\n"
        "  🔴 ip: 185.220.101.32\n     来源: tor_exit_node  严重度: high\n"
        "  🟡 domain: evil-cdn.example\n     来源: osint  严重度: medium"
    ),
    "structured": {
        "count": 2,
        "iocs": [
            {"ioc_type": "ip", "ioc_value": "185.220.101.32", "severity": "high", "source": "tor_exit_node"},
            {"ioc_type": "domain", "ioc_value": "evil-cdn.example", "severity": "medium", "source": "osint"},
        ],
        "summary": "外联 IP 命中 Tor 出口节点情报，域名命中 OSINT 黑名单。",
    },
    "confidence": 0.8,
    "evidence": [
        {"type": "ioc_hits", "ref": "185.220.101.32", "ioc_type": "ip"},
    ],
}

SIMULATE_BRANCH = {
    "output_text": "# 分支节点\n手动指定分支结果（本期不做表达式求值，仅手动选择）。",
    "structured": {
        "chosen_branch": None,
        "options": [],
        "downstream_active": [],
    },
    "confidence": 1.0,
    "evidence": [],
}

SIMULATE_LLM = {
    "output_text": "# 自定义大模型节点\n（模拟）基于节点 prompt 与输入参数合成的结论摘要。",
    "structured": {
        "summary": "（模拟）这是自定义 LLM 节点的合成摘要输出。",
        "prompt_used": "（模拟）未配置真实 prompt",
        "model": "（模拟）未指定模型",
    },
    "confidence": 0.6,
    "evidence": [],
}

SIMULATE_TRIAGE = {
    "output_text": (
        "# 触发器分诊报告（模拟）\n\n"
        "事件数量：1\n"
        "代表事件 ID：SE-1\n"
        "事件类型：malware\n"
        "最高严重度：critical\n"
        "建议优先级：**P0**\n"
        "主机 ID：host-triage-1\n"
        "时间戳：2026-07-18T10:00:00\n"
        "AI 初判：suspicious（beacon 行为）\n"
        "命中规则参考：Suspicious Beacon\n\n"
        "## 证据摘要\n"
        "  🔴 security_events.id=SE-1 — malware / critical（beacon）\n"
        "  🔴 normalized_logs — powershell.exe 外联 8.8.8.8\n\n"
        "> 置信度 0.75：基于 critical 严重度 + AI 初判 suspicious + 命中检测规则，"
        "判定为高危分诊事件，建议优先处置。"
    ),
    "structured": {
        "stage": "triage",
        "priority": "P0",
        "confidence": 0.75,
        "evidence_count": 2,
        "event_id": "SE-1",
        "summary": "检测到 critical 级 malware 事件（beacon 行为），AI 初判 suspicious，建议优先级 P0。",
    },
    "confidence": 0.75,
    "evidence": [
        {
            "type": "security_events",
            "ref": "security_events.id=SE-1",
            "event_type": "malware",
            "severity": "critical",
        },
        {
            "type": "normalized_logs",
            "ref": "normalized_logs.host_id=host-triage-1",
            "process_name": "powershell.exe",
            "remote_addr": "8.8.8.8",
        },
    ],
}

# 未知类型兜底
SIMULATE_DEFAULT = {
    "output_text": "# 节点模拟输出\n（模拟）该节点类型暂无专门的 fixture，返回通用合成结果。",
    "structured": {"summary": "（模拟）通用合成结果。"},
    "confidence": 0.5,
    "evidence": [],
}

_FIXTURE_MAP = {
    "file_analysis": SIMULATE_FILE_ANALYSIS,
    "process_analysis": SIMULATE_PROCESS_ANALYSIS,
    "network_analysis": SIMULATE_NETWORK_ANALYSIS,
    "registry_analysis": SIMULATE_REGISTRY_ANALYSIS,
    "timeline": SIMULATE_TIMELINE,
    "root_cause": SIMULATE_ROOT_CAUSE,
    "threat_intel": SIMULATE_THREAT_INTEL,
    "branch": SIMULATE_BRANCH,
    "llm": SIMULATE_LLM,
    "trigger": SIMULATE_TRIAGE,
}


def get_fixture(node_type: str, node_name: str = None) -> dict:
    """按节点类型返回 simulate 合成结果。

    Args:
        node_type: 节点类型（file_analysis / llm / branch ...）。
        node_name: 节点名称（预留，后续可基于名称返回差异化 fixture）。

    Returns:
        与真实模式 ``_run_<node>`` 同构的 dict：
        ``{output_text, structured, confidence, evidence}``。
    """
    return _FIXTURE_MAP.get(node_type, SIMULATE_DEFAULT)
