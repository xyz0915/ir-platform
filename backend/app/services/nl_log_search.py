"""NL 检索主流程：NL → 意图 → 执行 → 脱敏 → 摘要（§C / §8.2）。

复用：NlQueryGuard（编译+校验）、search_events（查询 security_events）、
data_masking.apply（脱敏）、AgentLLM（生成摘要）、NlQueryAudit（审计）。

【P0-3 改造】白名单字段按"真实列 / evidence JSON 路径 / keyword 兜底"三级翻译：
- 真实列 → search_events 具名参数
- evidence JSON → field_conditions（JSON_EXTRACT 参数化下推）
- keyword 兜底 → keyword LIKE
- 其余 → degraded 兜底（Python 后置过滤），并在 query_plan 中标注
移除 Python 内存过滤（仅保留 degraded 兜底），total 使用真实 COUNT。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection
from app.models.nl_query_audit import NlQueryAudit
from app.services.data_masking import apply as mask_apply
from app.services.agent_llm import AgentLLM
from app.services.nl_query_guard import NlQueryGuard
from app.services.field_query_map import (
    COLUMN_FIELDS,
    EVIDENCE_JSON_FIELDS,
    KEYWORD_FALLBACK_FIELDS,
    resolve_field,
    build_where_clause,
)
from app.services.time_utils import parse_client_time

logger = logging.getLogger(__name__)

# 可直接映射到 search_events 具名参数的白名单字段（COLUMN_FIELDS 子集）
_SEARCH_PARAM_MAP = {
    "host_id": "host_id",
    "event_type": "event_type",
    "severity": "severity",
    "attack_stage": "attack_stage",
    "source_collector": "source_collector",
    "status": "status",
    "assignee": "assignee",
}

# 结果默认展示列优先顺序（security_events 字段）
_DISPLAY_COLUMN_ORDER = [
    "timestamp", "host_id", "hostname", "event_type", "severity",
    "attack_stage", "source_collector", "status", "summary",
    "matched_rules", "evidence",
]

# 允许的排序（白名单防注入）
_ALLOWED_SORTS = {
    "timestamp asc", "timestamp desc",
    "host_id asc", "host_id desc",
    "severity asc", "severity desc",
    "event_type asc", "event_type desc",
}


def _sanitize_sort(sort: Optional[str]) -> str:
    """排序白名单：仅允许安全排序表达式，防注入。"""
    s = (sort or "").strip().lower()
    return s if s in _ALLOWED_SORTS else "timestamp DESC"


async def nl_log_search(
    nl_text: str,
    user: Optional[dict] = None,
    host_id: Optional[int] = None,
    time_range: Optional[dict] = None,
    preview_only: bool = False,
    allowed_host_ids: Optional[set[int]] = None,
) -> dict:
    """执行一次自然语言日志检索。

    Args:
        nl_text: 自然语言检索需求。
        user: 当前用户字典（get_current_user）。
        host_id: 可选，限定主机范围。
        time_range: 可选，{"from": ISO, "to": ISO}。
        preview_only: True 时不查库，仅编译/翻译并写 preview 审计。
        allowed_host_ids: ACL 注入的可见主机集合（None=全量）。

    Returns:
        {columns, rows(脱敏后), summary, audit_id, total, query_plan}

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

        # 4. 翻译为参数化查询（三级字段映射 → SQL/JSON_EXTRACT 下推）
        search_params, field_conditions, predicates, page, page_size, query_plan = _translate(intent)

        # 4.1 预览模式：不查库，写 status='preview' 审计
        if preview_only:
            audit_id = NlQueryAudit.create(
                user_id=user_id, nl_text=nl_text, intent_json=intent,
                executed_sql_json={"query_plan": query_plan, "field_conditions": field_conditions},
                row_count=0, masked=1, status="preview",
            )
            return {
                "columns": [],
                "rows": [],
                "summary": "",
                "audit_id": audit_id,
                "total": 0,
                "query_plan": query_plan,
                "preview": True,
            }

        # 5. 查询 security_events（真实 COUNT，字段条件下推 SQL）
        result = search_events(
            **search_params,
            field_conditions=field_conditions,
            page=1,
            page_size=500,
            allowed_host_ids=allowed_host_ids,
        )
        items = result["items"]
        for pred in predicates:
            items = [it for it in items if pred(it)]

        total = result["total"]

        # 6. 脱敏
        masked_rows = [mask_apply(dict(it)) for it in items]

        # 7. 分页（在脱敏后数据集上切片）
        start = (page - 1) * page_size
        page_rows = masked_rows[start:start + page_size]

        # 8. 摘要（AgentLLM，失败仅降级为空）
        summary = ""
        try:
            summary = await _generate_summary(nl_text, page_rows, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("nl_log_search 摘要生成失败（降级）: %s", exc)
            summary = ""

        # 9. 写审计（ok + 脱敏）
        audit_id = NlQueryAudit.create(
            user_id=user_id, nl_text=nl_text, intent_json=intent,
            executed_sql_json={"search_params": search_params, "field_conditions": field_conditions},
            row_count=total, masked=1, status="ok",
        )

        columns = _collect_columns(page_rows)
        return {
            "columns": columns,
            "rows": page_rows,
            "summary": summary,
            "audit_id": audit_id,
            "total": total,
            "query_plan": query_plan,
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
    allowed_host_ids: Optional[set[int]] = None,
    field_conditions: Optional[list[dict]] = None,
    case_id: Optional[int] = None,
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
        date_from: 起始时间（兼容 T/Z/毫秒格式）.
        date_to: 截止时间.
        sort: 排序（白名单）.
        page: 页码.
        page_size: 每页条数.
        allowed_host_ids: ACL 可见主机集合（None=全量；空集合=WHERE 1=0）.
        field_conditions: 结构化字段条件（三级映射 → SQL/JSON_EXTRACT，AND 语义）.
        case_id: 按案件过滤（host_id IN (SELECT id FROM hosts WHERE case_id=?)）.

    Returns:
        {total, page, page_size, items}.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if host_id is not None:
        conditions.append("se.host_id=?")
        params.append(int(host_id))
    if case_id is not None:
        conditions.append("se.host_id IN (SELECT id FROM hosts WHERE case_id=?)")
        params.append(case_id)
    if allowed_host_ids is not None:
        if not allowed_host_ids:
            conditions.append("1=0")  # 空可见集合 → 无结果
        else:
            placeholders = ",".join("?" for _ in allowed_host_ids)
            conditions.append(f"se.host_id IN ({placeholders})")
            params.extend(sorted(allowed_host_ids))
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
        params.append(parse_client_time(date_from))
    if date_to:
        conditions.append("se.timestamp <= ?")
        params.append(parse_client_time(date_to))

    # 结构化字段条件（三级映射 → SQL/JSON_EXTRACT，参数化）
    if field_conditions:
        fw, fp = build_where_clause(field_conditions, "se")
        if fw:
            conditions.append(f"({fw})")
            params.extend(fp)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size
    safe_sort = _sanitize_sort(sort)

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
            ORDER BY se.{safe_sort}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _translate(intent: dict):
    """将意图翻译为 (search_params, field_conditions, predicates, page, page_size, query_plan)。

    三级字段映射（§2.2.3）：
    - timestamp → date_from/date_to（时间范围）
    - COLUMN_FIELDS → search_events 具名参数
    - EVIDENCE_JSON_FIELDS → field_conditions（JSON_EXTRACT 下推）
    - KEYWORD_FALLBACK_FIELDS → search_params["keyword"]
    - 其它 → degraded 兜底（Python 后置过滤），query_plan 标注
    """
    search_params: dict[str, Any] = {}
    field_conditions: list[dict] = []
    predicates: list = []
    degraded: list[str] = []
    filters = intent.get("filters", []) or []

    for f in filters:
        field = f.get("field")
        op = f.get("op")
        value = f.get("value")
        if not field:
            continue

        # 时间字段 → date_from/date_to
        if field == "timestamp":
            if op in (">=", ">", "between"):
                search_params["date_from"] = str(value)
            if op in ("<=", "<", "between"):
                search_params["date_to"] = str(value)
            continue

        kind, _target = resolve_field(field)
        if kind == "column":
            if field in _SEARCH_PARAM_MAP:
                param = _SEARCH_PARAM_MAP[field]
                if param == "host_id":
                    # 整数列，强制转换避免字符串比较歧义
                    try:
                        search_params[param] = int(value)
                    except (TypeError, ValueError):
                        search_params[param] = value
                else:
                    search_params[param] = value
            else:
                # 其它真实列（ioc_matches/event_key/attack_chain_id/hostname 等）→ SQL 下推
                field_conditions.append({"field": field, "op": op, "value": value})
        elif kind == "json":
            # evidence JSON 路径 → JSON_EXTRACT 参数化下推
            field_conditions.append({"field": field, "op": op, "value": value})
        elif kind == "keyword":
            # keyword 兜底：evidence/matched_rules/event_type LIKE
            search_params["keyword"] = str(value)
        else:
            degraded.append(f"字段 {field} 无映射，改用 Python 后置过滤")
            predicates.append(_make_predicate(field, op, value))

    # time_range 覆盖
    tr = intent.get("time_range") or {}
    if tr.get("from"):
        search_params["date_from"] = str(tr["from"])
    if tr.get("to"):
        search_params["date_to"] = str(tr["to"])

    page = int(intent.get("page", 1) or 1)
    page_size = min(int(intent.get("page_size", 50) or 50), 500)
    sort = intent.get("sort") or "timestamp DESC"
    search_params["sort"] = _sanitize_sort(sort)

    sql_conditions = [
        {"field": c["field"], "op": c["op"], "value": c["value"]} for c in field_conditions
    ]
    if search_params.get("keyword"):
        sql_conditions.append({"keyword": search_params["keyword"]})

    query_plan = {
        "filters": filters,
        "time_range": intent.get("time_range", {}),
        "sql_conditions": sql_conditions,
        "page_size": page_size,
        "sort": search_params["sort"],
        "degraded": degraded,
    }
    return search_params, field_conditions, predicates, page, page_size, query_plan


def _make_predicate(field: str, op: str, value: Any):
    """构造 Python 侧后置过滤谓词（安全，不拼 SQL；仅 degraded 兜底用）。"""

    def pred(row: dict) -> bool:
        cell = row.get(field)
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
