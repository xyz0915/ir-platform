"""Windows 安全事件日志 → 规则引擎 → 告警 的桥接服务（P0-2）.

背景
----
``agent/collectors/security.py`` 会产出 ``event_ids_summary``（形如
``{"4625": 37, "4624": 12}``）与 ``event_records``，但此前后端仅把这份数据
写进 ``agent_imports.raw_json`` 供全文检索，**没有任何规则消费它**。
其结果是 4625/4648/4662/4769/4672/4624 等 Windows 核心安全审计事件全部漏报。

本模块补上这段断点：

    security payload ──► extract_event_summary()
                          └─► load_event_log_rules()        （DB 优先，回退内置 JSON）
                                └─► MatcherRegistry.dispatch("event_log_summary", ...)
                                      └─► Alert.create_or_aggregate()

设计要点
--------
- **非阻塞**：所有对外入口都用 try/except 兜底，任何异常只写日志，
  绝不影响 Agent 数据导入主流程。
- **幂等**：复用 ``Alert.create_or_aggregate`` 的 (host_id, rule_name, 5 分钟)
  聚合窗口，同一批次重复上报只递增 count，不产生重复告警。
- **可降级**：DB 中没有 event_log_summary 规则时（未 seed 的环境），
  自动回退到内置 ``event_log_rules.json``，保证开箱即用。
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RULE_TYPE = "event_log_summary"

# 内置规则文件（DB 未 seed 时的回退来源）
_BUILTIN_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "event_log_rules.json"


def extract_event_summary(payload) -> dict:
    """从 Agent security 采集器载荷中抽取 event_ids_summary.

    兼容以下形态：
      - ``{"event_ids_summary": {...}, "antivirus": [...]}``  单个采集结果对象
      - ``[{"event_ids_summary": {...}}]``                    列表包裹（import 链路常见）
      - ``{"4625": 3}``                                       已剥离外层的裸计数字典
      - ``None`` / 其它                                        返回 {}

    多个元素时按事件 ID 累加合并。

    Args:
        payload: Agent security 采集器的原始载荷。

    Returns:
        ``{"4625": 37, ...}`` 形态的计数字典；无法解析时返回 {}。
    """
    if payload is None:
        return {}

    # 字符串形态（直接来自 agent_imports.raw_json）
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    items = payload if isinstance(payload, list) else [payload]

    merged: dict = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = item.get("event_ids_summary")
        if summary is None:
            # 裸计数字典：所有值均为数字才认定
            if item and all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                for v in item.values()
            ):
                summary = item
            else:
                continue
        if not isinstance(summary, dict):
            continue
        for k, v in summary.items():
            try:
                merged[str(k).strip()] = merged.get(str(k).strip(), 0) + int(v)
            except (TypeError, ValueError):
                continue
    return merged


def _load_builtin_rules() -> list:
    """读取内置 event_log_rules.json（DB 回退来源）."""
    try:
        with open(_BUILTIN_RULES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("event_log_rules.json 结构异常（非数组），忽略")
            return []
        return [r for r in data if isinstance(r, dict) and r.get("enabled", True)]
    except FileNotFoundError:
        logger.warning("内置规则文件不存在: %s", _BUILTIN_RULES_PATH)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取内置 event_log_rules.json 失败: %s", exc)
        return []


def load_event_log_rules() -> list:
    """加载所有启用的 event_log_summary 规则.

    优先从 DB 的 ``rules`` 表读取（用户可能已在 UI 中调整阈值）；
    DB 中一条都没有时回退到内置 JSON，保证未 seed 环境也具备检测能力。

    Returns:
        规则字典列表，每项至少含 name / condition / severity。
    """
    db_rules: list = []
    try:
        from app.models.rule import Rule
        for r in Rule.list(enabled=True):
            if r.get("rule_type") == RULE_TYPE:
                db_rules.append(r)
    except Exception as exc:  # noqa: BLE001
        logger.debug("从 DB 读取 event_log_summary 规则失败，回退内置: %s", exc)

    if db_rules:
        return db_rules
    return _load_builtin_rules()


def evaluate_summary(event_summary: dict, rules: Optional[list] = None) -> list:
    """对事件计数字典执行规则匹配，返回命中的规则列表（纯函数，不写库）.

    Args:
        event_summary: ``{"4625": 37, ...}`` 计数字典。
        rules: 规则列表；None 时自动加载。

    Returns:
        命中的规则字典列表（含 matched_count 实测值，便于生成告警详情）。
    """
    if not event_summary:
        return []

    if rules is None:
        rules = load_event_log_rules()
    if not rules:
        return []

    try:
        from app.rules.matchers.registry import MatcherRegistry
        import app.rules.rule_engine  # noqa: F401  确保 matcher 已注册
    except Exception as exc:  # noqa: BLE001
        logger.warning("规则引擎不可用，跳过安全事件评估: %s", exc)
        return []

    data_item = {"event_ids_summary": event_summary}
    hits: list = []

    for rule in rules:
        condition = rule.get("condition")
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(condition, dict):
            continue

        try:
            matched = MatcherRegistry.dispatch(RULE_TYPE, data_item, condition, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("规则 %s 匹配异常: %s", rule.get("name"), exc)
            continue

        if not matched:
            continue

        # 记录实测计数，供告警详情展示
        target_ids = condition.get("event_ids")
        if target_ids is None:
            target_ids = [condition.get("event_id")]
        if not isinstance(target_ids, (list, tuple)):
            target_ids = [target_ids]
        observed = {
            str(i): event_summary.get(str(i), 0)
            for i in target_ids if i is not None
        }

        hit = dict(rule)
        hit["observed_counts"] = observed
        hits.append(hit)

    return hits


def evaluate_and_alert(host_id: int, payload, case_id: Optional[int] = None) -> list:
    """端到端：解析安全事件载荷 → 规则匹配 → 写入告警.

    调用方（``import_service``）应以非阻塞方式调用本函数。

    Args:
        host_id: 主机 ID。
        payload: Agent security 采集器载荷（dict / list / json 字符串）。
        case_id: 案件 ID（可选，用于告警归属）。

    Returns:
        本次产生/聚合的告警摘要列表：
        ``[{"rule_name":..., "alert_id":..., "is_new":..., "severity":...}, ...]``
        任何异常下返回空列表。
    """
    try:
        event_summary = extract_event_summary(payload)
        if not event_summary:
            return []

        hits = evaluate_summary(event_summary)
        if not hits:
            return []

        from app.models.alert import Alert

        results: list = []
        for hit in hits:
            rule_name = hit.get("name") or "unknown_event_log_rule"
            severity = hit.get("severity") or "medium"
            label = hit.get("label") or rule_name
            observed = hit.get("observed_counts") or {}
            condition = hit.get("condition") or {}
            if isinstance(condition, str):
                try:
                    condition = json.loads(condition)
                except (json.JSONDecodeError, TypeError):
                    condition = {}

            detail = {
                "source": "windows_security_event_log",
                "rule_type": RULE_TYPE,
                "observed_counts": observed,
                "threshold": condition.get("count", 1),
                "operator": condition.get("operator", ">="),
                "mitre_attack": (condition.get("_meta") or {}).get("mitre_attack"),
                "description": hit.get("description", ""),
            }
            counts_text = ", ".join(f"{k}×{v}" for k, v in observed.items())
            title = f"{label}（{counts_text}）" if counts_text else label

            try:
                alert_id, is_new = Alert.create_or_aggregate(
                    host_id=host_id,
                    rule_name=rule_name,
                    severity=severity,
                    title=title,
                    detail=detail,
                    case_id=case_id,
                    rule_label=label,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("写入安全事件告警失败 rule=%s: %s", rule_name, exc)
                continue

            # Alert.create_or_aggregate 内部吞异常后会返回 (None, False)
            # （如 host_id 外键不存在）。此时告警并未真正落库，不能计入返回结果，
            # 否则调用方会拿到"看起来成功"的假摘要。
            if alert_id is None:
                logger.warning(
                    "安全事件告警未落库 rule=%s host=%s（可能 host_id 不存在）",
                    rule_name, host_id,
                )
                continue

            results.append({
                "rule_name": rule_name,
                "alert_id": alert_id,
                "is_new": is_new,
                "severity": severity,
                "observed_counts": observed,
            })

        if results:
            logger.info(
                "安全事件日志规则命中 host=%s，产生/聚合告警 %d 条: %s",
                host_id, len(results), [r["rule_name"] for r in results],
            )
        return results

    except Exception as exc:  # noqa: BLE001
        logger.warning("安全事件日志规则评估失败（非阻塞）host=%s: %s", host_id, exc)
        return []
