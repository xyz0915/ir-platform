"""Action 映射表 — 用户意图 → 后端 API 映射."""
from app.schemas.ai_advanced import ActionMapEntry

ACTION_MAP: list[ActionMapEntry] = [
    ActionMapEntry(
        user_intent="block_ip",
        action_name="封锁 IP",
        backend_api="block_ip",
        high_risk=True,
        description="将目标 IP 添加到防火墙黑名单",
    ),
    ActionMapEntry(
        user_intent="isolate_host",
        action_name="隔离主机",
        backend_api="isolate_host",
        high_risk=True,
        description="将目标主机从网络隔离",
    ),
    ActionMapEntry(
        user_intent="export_report",
        action_name="导出报告",
        backend_api="export_report",
        high_risk=False,
        description="生成本次调查的报告",
    ),
    ActionMapEntry(
        user_intent="mark_false_positive",
        action_name="标记误报",
        backend_api="mark_false_positive",
        high_risk=False,
        description="将该告警标记为误报并加入白名单",
    ),
    ActionMapEntry(
        user_intent="add_whitelist",
        action_name="加入白名单",
        backend_api="add_whitelist",
        high_risk=False,
        description="将目标加入策略白名单",
    ),
    ActionMapEntry(
        user_intent="create_case",
        action_name="创建案件",
        backend_api="create_case",
        high_risk=False,
        description="基于当前调查创建新案件",
    ),
    ActionMapEntry(
        user_intent="add_note",
        action_name="添加调查笔记",
        backend_api="add_note",
        high_risk=False,
        description="将当前发现添加到案件笔记",
    ),
]


def get_action(intent: str) -> ActionMapEntry | None:
    """根据意图名称查找 Action 映射."""
    for entry in ACTION_MAP:
        if entry.user_intent == intent:
            return entry
    return None


def list_actions() -> list[ActionMapEntry]:
    """返回全部 Action 映射."""
    return ACTION_MAP
