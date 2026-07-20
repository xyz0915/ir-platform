"""NL 检索主流程：NL → 意图 → 执行 → 脱敏 → 摘要（§C / §8.2）。

复用：NlQueryGuard（编译+校验）、search_events（查询 security_events）、
data_masking.apply（脱敏）、AgentLLM（生成摘要）、NlQueryAudit（审计）。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection
from app.models.nl_query_audit import NlQueryAudit
from app.services.data_masking import apply as mask_apply
from app.services.agent_llm import AgentLLM
from app.services.nl_query_guard import NlQueryGuard, WHITELIST_FIELDS

logger = logging.getLogger(__name__)

# 可直接映射到 search_events 参数的白名单字段
_SEARCH_PARAM_MAP = {
    "host_id": "host_id",
    "event_type": "event_type",
    "severity": "severity",
    "attack_stage": "attack_stage",
    "source_collector": "source_collector",
    "status": "status",
    "description": "keyword",
    "command_line": "keyword",
}

# 结果默认展示列优先顺序（security_events 字段）
_DISPLAY_COLUMN_ORDER = [
    "timestamp", "host_id", "hostname", "event_type", "severity",
    "attack_stage", "source_collector", "status", "summary",
    "matched_rules", "evidence",
]


async def nl_log_search(
    nl_text: str,
    user: Optional[dict] = None,
    host_id: Optional[int] = None,
    time_range: Optional[dict] = None,
) -> dict:
    """执行一次自然语言日志检索。

    Args:
        nl_text: 自然语言检索需求。
        user: 当前用户字典（get_current_user）。
        host_id: 可选，限定主机范围。
        time_range: 可选，{"from": ISO, "to": ISO}。

    Returns:
        {columns, rows(脱敏后), summary, audit_id, total}

    Raises:
        ValueError: 意图被护栏拒绝或执行异常（端点层转 _fail）。
    """
    user = user or {}
    user_id = user.get("id")
    intent: dict[str, Any] = {}
    audit_id: Optional[int] = None

    try:
        # 1. 编译意图（经 AgentLLM）
        guard = NlQueryGuard()
        intent = await guard.compile(nl_text, user)

        # 2. 注入调用方约束（host_id / time_range）
        if host_id is not None:
            intent.setdefault("filters", []).append(
                {"field": "host_id", "op": "=", "value": host_id}
            )
        if time_range:
            intent["time_range"] = time_range

        # 3. 校验
        ok, err = guard.validate(intent, nl_text=nl_text)
        if not ok:
            audit_id = NlQueryAudit.create(
                user_id=user_id, nl_text=nl_text, intent_json=intent,
                status="rejected", error_message=err,
            )
            raise ValueError(err)

        # 4. 翻译为参数化查询并执行（查询 security_events 表）
        search_params, predicates, page, page_size = _translate(intent)
        result = search_events(**search_params, page=1, page_size=500)
        items = result["items"]
        for pred in predicates:
            items = [it for it in items if pred(it)]

        total = len(items)

        # 5. 脱敏
        masked_rows = [mask_apply(dict(it)) for it in items]

        # 6. 分页（在脱敏后数据集上切片）
        start = (page - 1) * page_size
        page_rows = masked_rows[start:start + page_size]

        # 7. 摘要（AgentLLM，失败仅降级为空）
        summary = ""
        try:
            summary = await _generate_summary(nl_text, page_rows, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("nl_log_search 摘要生成失败（降级）: %s", exc)
            summary = ""

        # 8. 写审计（ok + 脱敏）
        audit_id = NlQueryAudit.create(
            user_id=user_id, nl_text=nl_text, intent_json=intent,
            executed_sql_json={"search_params": search_params, "predicates": len(predicates)},
            row_count=total, masked=1, status="ok",
        )

        columns = _collect_columns(page_rows)
        return {
            "columns": columns,
            "rows": page_rows,
            "summary": summary,
            "audit_id": audit_id,
            "total": total,
        }
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("nl_log_search 执行异常")
        NlQueryAudit.create(
            user_id=user_id, nl_text=nl_text, intent_json=intent,
            status="error", error_message=str(exc),
        )
        raise ValueError(f"NL 检索失败: {exc}")


def search_events(
    host_id: Optional[int] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    attack_stage: Optional[str] = None,
    source_collector: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = "timestamp DESC",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """多维度检索安全事件（security_events 表，替代原先的 NormalizedLog.search）。

    Args:
        host_id: 主机 ID.
        event_type: 事件类型（逗号分隔）.
        severity: 严重度（逗号分隔）.
        attack_stage: 攻击阶段.
        source_collector: 采集器.
        status: 事件状态.
        keyword: 关键字（搜索 summary + evidence）.
        date_from: 起始时间.
        date_to: 截止时间.
        sort: 排序.
        page: 页码.
        page_size: 每页条数.

    Returns:
        {total, page, page_size, items}.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if host_id is not None:
        conditions.append("se.host_id=?")
        params.append(int(host_id))
    if event_type:
        types = [t.strip() for t in event_type.split(",") if t.strip()]
        if types:
            placeholders = ",".join("?" for _ in types)
            conditions.append(f"se.event_type IN ({placeholders})")
            params.extend(types)
    if severity:
        sevs = [s.strip() for s in severity.split(",") if s.strip()]
        if sevs:
            placeholders = ",".join("?" for _ in sevs)
            conditions.append(f"se.severity IN ({placeholders})")
            params.extend(sevs)
    if attack_stage:
        conditions.append("se.attack_stage=?")
        params.append(attack_stage)
    if source_collector:
        conditions.append("se.source_collector=?")
        params.append(source_collector)
    if status:
        conditions.append("se.status=?")
        params.append(status)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append("(se.evidence LIKE ? OR se.matched_rules LIKE ? OR se.event_type LIKE ?)")
        params.extend([kw, kw, kw])
    if date_from:
        conditions.append("se.timestamp >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("se.timestamp <= ?")
        params.append(date_to)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size

    with get_connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se WHERE {where_clause}",
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            f"""
            SELECT se.*, h.hostname
            FROM security_events se
            LEFT JOIN hosts h ON h.id = se.host_id
            WHERE {where_clause}
            ORDER BY se.{sort}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _translate(intent: dict):
    """将意图翻译为 (search_params, python_predicates, page, page_size)。"""
    search_params: dict[str, Any] = {}
    predicates: list = []
    filters = intent.get("filters", []) or []

    for f in filters:
        field = f.get("field")
        op = f.get("op")
        value = f.get("value")
        db_col = WHITELIST_FIELDS.get(field)
        if db_col is None:
            continue

        # 时间字段 → date_from/date_to
        if field == "timestamp":
            if op in (">=", ">", "between"):
                search_params["date_from"] = str(value)
            if op in ("<=", "<", "between"):
                search_params["date_to"] = str(value)
            continue

        # 直接映射的字段
        if field in _SEARCH_PARAM_MAP:
            param = _SEARCH_PARAM_MAP[field]
            if param == "keyword":
                # description / command_line 的 contains 或精确均走 search 的 keyword(LIKE)
                search_params["keyword"] = str(value)
            elif param == "host_id":
                # 整数列，强制转换避免字符串比较歧义
                try:
                    search_params["host_id"] = int(value)
                except (TypeError, ValueError):
                    search_params["host_id"] = value
            else:
                search_params[param] = value
            continue

        # 其余白名单字段 → Python 后置过滤（安全，不拼 SQL）
        predicates.append(_make_predicate(db_col, op, value))

    # time_range 覆盖
    tr = intent.get("time_range") or {}
    if tr.get("from"):
        search_params["date_from"] = str(tr["from"])
    if tr.get("to"):
        search_params["date_to"] = str(tr["to"])

    page = int(intent.get("page", 1) or 1)
    page_size = min(int(intent.get("page_size", 50) or 50), 500)
    sort = intent.get("sort") or "timestamp DESC"
    search_params["sort"] = sort

    return search_params, predicates, page, page_size


def _make_predicate(db_col: str, op: str, value: Any):
    """构造 Python 侧后置过滤谓词（安全，不拼 SQL）。"""

    def pred(row: dict) -> bool:
        cell = row.get(db_col)
        if cell is None:
            return False
        if op == "=":
            return str(cell) == str(value)
        if op == "!=":
            return str(cell) != str(value)
        if op == "contains":
            return str(value) in str(cell)
        if op == "in":
            vals = value if isinstance(value, list) else [value]
            return str(cell) in [str(v) for v in vals]
        if op == ">=":
            return str(cell) >= str(value)
        if op == "<=":
            return str(cell) <= str(value)
        if op == ">":
            return str(cell) > str(value)
        if op == "<":
            return str(cell) < str(value)
        return False

    return pred


def _collect_columns(rows: list[dict]) -> list[str]:
    """收集结果列（优先固定顺序，再补其余）。"""
    if not rows:
        return []
    present = set()
    ordered: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in present:
                present.add(k)
                ordered.append(k)
    head = [c for c in _DISPLAY_COLUMN_ORDER if c in present]
    tail = [c for c in ordered if c not in head]
    return head + tail


async def _generate_summary(nl_text: str, rows: list[dict], user: dict) -> str:
    """用 AgentLLM 生成自然语言摘要（无结果时返回提示）。"""
    if not rows:
        return "未检索到匹配日志。"
    sample = rows[:10]
    sample_text = "\n".join(
        f"- [{r.get('timestamp', '')}] {r.get('event_type', '')}/{r.get('severity', '')} "
        f"src={r.get('source_ip', '')} user={r.get('user_name', '')} "
        f"proc={r.get('process_name', '')} cmd={r.get('command_line', '')}"
        for r in sample
    )
    prompt = (
        f"用户用自然语言检索了日志：{nl_text}\n\n"
        f"以下是脱敏后的前 {len(sample)} 条结果样本：\n{sample_text}\n\n"
        f"请用中文简洁总结这些日志反映的安全态势（2~4 句）。"
    )
    resp = await AgentLLM().call(prompt, user)
    if resp.get("degraded"):
        return ""
    return (resp.get("content") or "").strip()
