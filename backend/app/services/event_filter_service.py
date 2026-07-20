"""事件筛选参数构建器：根据前端筛选参数动态构建 SQL WHERE 子句.

支持的参数: case_id, host_id, filter, severity, event_type,
           rule_id, rule_category, rule_confidence_min,
           source_collector, time_range, keyword, start_time, end_time
"""

from __future__ import annotations

from typing import Any


def build_events_where(params: dict) -> tuple[str, list]:
    """根据前端筛选参数动态构建 WHERE 子句.

    Args:
        params: 筛选参数字典，支持以下键:
            - case_id (int|str): 案件 ID
            - host_id (int|str): 主机 ID
            - filter (str): "all" / "matched" / "unmatched"
            - severity (str): 逗号分隔，如 "critical,high"
            - event_type (str): 逗号分隔，如 "process_start,network_outbound"
            - rule_id (int|str): 规则 ID
            - rule_category (str): 规则分类
            - rule_confidence_min (float): 最小置信度 0.0-1.0
            - source_collector (str): 逗号分隔，如 "osquery,cm"
            - time_range (str): "1h" / "24h" / "7d" / "all"
            - keyword (str): 关键字搜索
            - start_time (str): 自定义开始时间 ISO
            - end_time (str): 自定义结束时间 ISO

    Returns:
        (where_sql, params_list): WHERE 子句字符串和参数列表.
    """
    conditions: list[str] = ["1=1"]
    sql_params: list[Any] = []

    # 案件 + 主机级联
    case_id = params.get("case_id")
    if case_id:
        case_id = int(case_id)
        conditions.append(
            "se.host_id IN (SELECT id FROM hosts WHERE case_id=?)"
        )
        sql_params.append(case_id)
        host_id = params.get("host_id")
        if host_id:
            conditions.append("se.host_id = ?")
            sql_params.append(int(host_id))

    # 三视图：全部 / 已匹配 / 未匹配
    filter_val = params.get("filter", "all")
    if filter_val == "matched":
        conditions.append(
            "se.matched_rules IS NOT NULL AND se.matched_rules != '[]'"
        )
    elif filter_val == "unmatched":
        conditions.append(
            "(se.matched_rules IS NULL OR se.matched_rules = '[]')"
        )

    # 严重度
    severity = params.get("severity")
    if severity:
        sev_list = [s.strip() for s in severity.split(",") if s.strip()]
        if sev_list:
            placeholders = ",".join("?" * len(sev_list))
            conditions.append(f"se.severity IN ({placeholders})")
            sql_params.extend(sev_list)

    # 引擎来源
    source_collector = params.get("source_collector")
    if source_collector:
        sc_list = [s.strip() for s in source_collector.split(",") if s.strip()]
        if sc_list:
            placeholders = ",".join("?" for _ in sc_list)
            conditions.append(f"se.source_collector IN ({placeholders})")
            sql_params.extend(sc_list)

    # 事件类型
    event_type = params.get("event_type")
    if event_type:
        type_list = [t.strip() for t in event_type.split(",") if t.strip()]
        if type_list:
            placeholders = ",".join("?" * len(type_list))
            conditions.append(f"se.event_type IN ({placeholders})")
            sql_params.extend(type_list)

    # 按规则 ID 筛选（json_each 精确匹配 rule_id）
    rule_id = params.get("rule_id")
    if rule_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM json_each(se.matched_rules) je "
            "WHERE json_extract(je.value, '$.rule_id') = ?)"
        )
        sql_params.append(int(rule_id))

    # 按规则分类筛选（json_each 精确匹配 category）
    rule_category = params.get("rule_category")
    if rule_category:
        conditions.append(
            "EXISTS (SELECT 1 FROM json_each(se.matched_rules) je "
            "WHERE json_extract(je.value, '$.category') = ?)"
        )
        sql_params.append(rule_category)

    # 置信度下限
    rule_confidence_min = params.get("rule_confidence_min")
    if rule_confidence_min is not None:
        try:
            conf_min = float(rule_confidence_min)
            conditions.append(
                "json_extract(se.matched_rules, '$[0].confidence') >= ?"
            )
            sql_params.append(conf_min)
        except (ValueError, TypeError):
            pass

    # AI 降噪筛选（v2 方案）
    ai_label = params.get("ai_label")
    if ai_label:
        if ai_label == "recommended":
            conditions.append("se.event_type = 'ai_recommended'")
        elif ai_label == "suspicious":
            conditions.append("""json_extract(se.ai_verdict, '$.label') = 'suspicious'""")
        elif ai_label == "false_positive":
            conditions.append("""json_extract(se.ai_verdict, '$.label') = 'false_positive'""")
    else:
        # 非 AI 筛选模式下，排除 AI 推荐事件（避免普通视图混入）
        conditions.append("se.event_type != 'ai_recommended'")

    # 时间范围预设
    time_range = params.get("time_range")
    if time_range and time_range != "all":
        hours_map = {"1h": 1, "24h": 24, "7d": 168}
        hours = hours_map.get(time_range)
        if hours is not None:
            conditions.append(
                "se.timestamp >= datetime('now', ? || ' hours')"
            )
            sql_params.append(f"-{hours}")

    # 自定义时间范围
    start_time = params.get("start_time")
    if start_time:
        conditions.append("se.timestamp >= ?")
        sql_params.append(start_time)

    end_time = params.get("end_time")
    if end_time:
        conditions.append("se.timestamp <= ?")
        sql_params.append(end_time)

    # 关键字搜索
    keyword = params.get("keyword")
    if keyword:
        conditions.append(
            "(se.evidence LIKE ? OR se.event_type LIKE ? OR se.id LIKE ?)"
        )
        like_pattern = f"%{keyword}%"
        sql_params.append(like_pattern)
        sql_params.append(like_pattern)
        sql_params.append(like_pattern)

    return "WHERE " + " AND ".join(conditions), sql_params
