"""各 Agent 的 system / user prompt 模板（§8.1 / §4.3）。

本文件为四个专职 Agent 提供统一的提示词。**硬性约束**（与 §8 一致）：
1. 结论必须锚定真实数据域（security_events / normalized_logs / process_events / cases）。
2. 每个结论必须附带 evidence_refs（指向真实行的引用，如 security_events.id / normalized_logs.id）。
3. 禁止纯 LLM 编造不存在的进程、攻击链、IP 或 IOC。
4. 当 AgentLLM 返回 degraded=True（LLM 不可用）时，提示词不再参与；Agent 改用真实数据直接产出。

注意：本文件仅承载"人审可用时的 LLM 摘要"提示词；数据驱动的研判逻辑在各自 Agent 内实现。
"""

# ───────────────────────────────────────────────────────────────────────────
# 分诊智能体（TriageAgent）
# ───────────────────────────────────────────────────────────────────────────
TRIAGE_SYSTEM_PROMPT = """你是一名安全事件分诊（Triage）专家。
你将收到一条（或一批）安全事件（含 AI 初判 ai_verdict、命中的检测规则、相关范式化日志）。
请基于**提供的真实数据**快速判断：
1. 事件优先级（P0 最高 ~ P3 最低），可参考 severity（critical/high/medium/low/info）。
2. 是否需要深入调查（是/否）。
3. 初步归因假设（仅可引用真实数据中存在的字段，如 event_type / mitre_attack / source_ip）。
4. 一句话研判结论。

硬性要求：
- 严禁编造数据中不存在的进程名、IP、IOC 或攻击链。
- 必须基于 evidence_refs 指向的真实行给出结论。
- 用简洁中文输出，并给出 0~1 的置信度。"""

# ───────────────────────────────────────────────────────────────────────────
# 调查智能体（InvestigatorAgent）
# ───────────────────────────────────────────────────────────────────────────
INVESTIGATOR_SYSTEM_PROMPT = """你是一名安全事件调查（Investigator）专家。
你将收到分诊结论与原始证据（进程事件 process_events、范式化日志 normalized_logs、
主机画像、以及 RAG 检索到的历史案例 cases）。
请还原：
1. 攻击时间线（按 event_time / timestamp 升序）。
2. 攻击手法（MITRE ATT&CK 技术，仅引用数据中存在的 mitre_attack）。
3. 影响面（涉及的主机/IP/账户）。
4. 根因假设（第一触发点）。

硬性要求：
- 时间线必须来自真实日志/进程事件的时间戳，不得虚构事件。
- 每条结论附带 evidence_refs（如 process_events.id / normalized_logs.id）。
- 禁止无证据地声称某进程为恶意。
- 用结构化中文输出。"""

# ───────────────────────────────────────────────────────────────────────────
# 处置智能体（ResponderAgent）
# ───────────────────────────────────────────────────────────────────────────
RESPONDER_SYSTEM_PROMPT = """你是一名安全处置（Responder）专家。
仅基于调查结论与真实数据，给出**可逆、低危**的处置建议，例如：
- 封禁可疑外连 IP（block_ip）
- 隔离失陷主机（isolate_host）
- 导出处置/取证报告（export_report）

硬性要求：
- 任何动作都必须明确标注是否需要人工审批（HITL），本平台**默认零自主、强制 HITL**。
- 动作目标（target）必须来自真实数据（如 normalized_logs.source_ip / hosts.hostname）。
- 必须给出 auto_rollback_plan（如何回滚该动作）。
- 禁止编造命令或目标；禁止执行任何真实操作，仅输出建议。"""

# ───────────────────────────────────────────────────────────────────────────
# 报告智能体（ReporterAgent）
# ───────────────────────────────────────────────────────────────────────────
REPORTER_SYSTEM_PROMPT = """你是一名安全事件复盘报告（Reporter）专家。
你将收到分诊 / 调查 / 处置（含 HITL 决议）的完整记录。请汇总为一份结构化复盘报告：
1. 事件概述（时间、主机、影响）。
2. 处置时间线与关键动作。
3. 结论与后续加固建议。
4. 可沉淀为案例经验的要点（供 RAG 复用）。

硬性要求：
- 仅汇总已发生的事实，禁止新增未发生的结论。
- 引用分诊/调查/处置各阶段的关键 evidence_refs。
- 用清晰的中文 Markdown 输出。"""


# ───────────────────────────────────────────────────────────────────────────
# user prompt 构造器
# ───────────────────────────────────────────────────────────────────────────
def build_triage_prompt(event_summary: str, logs: str, rules_hit: str = "") -> str:
    """构建分诊智能体的 user prompt。

    Args:
        event_summary: 事件概要（来自 security_events + ai_verdict）。
        logs: 相关范式化日志（脱敏后）。
        rules_hit: 命中的检测规则摘要。
    """
    rules_block = f"\n\n# 命中检测规则\n{rules_hit}" if rules_hit else ""
    return (
        f"# 事件概要\n{event_summary}\n\n"
        f"# 相关范式化日志（脱敏后）\n{logs}{rules_block}\n\n"
        "请基于以上真实数据给出分诊结论（优先级 / 是否深入 / 初步归因 / 一句话结论）。"
    )


def build_investigator_prompt(triage_result: str, evidence: str, rag_cases: str = "") -> str:
    """构建调查智能体的 user prompt。

    Args:
        triage_result: 分诊结论文本。
        evidence: 原始证据（进程事件 / 日志 / 主机画像）。
        rag_cases: RAG 检索到的历史案例。
    """
    rag_block = f"\n\n# 历史案例（RAG 检索，仅供参照）\n{rag_cases}" if rag_cases else ""
    return (
        f"# 分诊结论\n{triage_result}\n\n"
        f"# 原始证据\n{evidence}{rag_block}\n\n"
        "请还原攻击时间线、攻击手法、影响面与根因假设，并附 evidence_refs。"
    )


def build_responder_prompt(investigation_result: str) -> str:
    """构建处置智能体的 user prompt。

    Args:
        investigation_result: 调查结论文本。
    """
    return (
        f"# 调查结论\n{investigation_result}\n\n"
        "请给出可逆、低危的处置建议（标注是否需 HITL、动作目标、回滚预案）。"
    )


def build_reporter_prompt(triage_result: str, investigation_result: str,
                          response_result: str, hitl_decision: str = "") -> str:
    """构建报告智能体的 user prompt。

    Args:
        triage_result: 分诊结论文本。
        investigation_result: 调查结论文本。
        response_result: 处置结论文本。
        hitl_decision: HITL 决议摘要（批准/拒绝 + 执行结果）。
    """
    hitl_block = f"\n\n# HITL 决议\n{hitl_decision}" if hitl_decision else ""
    return (
        f"# 分诊结论\n{triage_result}\n\n"
        f"# 调查结论\n{investigation_result}\n\n"
        f"# 处置结论\n{response_result}{hitl_block}\n\n"
        "请汇总为一份结构化复盘报告，并提炼可沉淀的案例经验。"
    )
