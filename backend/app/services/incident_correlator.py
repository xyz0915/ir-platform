"""语义级跨资产事件归并器（第③批 T-D1 / P1-D）.

职责：
- ``keyword`` 模式：复用既有 ``correlate_incidents`` 的关键词分组逻辑（按 rule_name +
  攻击链阶段分组，落库到 ``incident_correlations``），保持向后兼容。
- ``semantic`` 模式：跨主机对 ``security_events``（仅 ``ai_verdict.label='suspicious'``）
  做语义聚类——优先用 ``AgentLLM`` 基于 LLM/语义相似度归类；当 ``AgentLLM`` 返回
  ``degraded=True``（无 AI 配置 / 熔断 / 连接失败）或 LLM 结果不可解析时，自动回退为
  基于字段（host / ip / event_type / 时间窗）的确定性聚类，**绝不抛出 500**。

所有 LLM 调用均经 ``AgentLLM`` 治理封装，符合 §8 的降级与审计约定。
"""

import json
import logging
from collections import defaultdict
from typing import Any, Optional

from app.database import get_connection
from app.models.incident_cluster import IncidentCluster
from app.services.agent_llm import AgentLLM

logger = logging.getLogger(__name__)


# 攻击链关键词 → 阶段映射（与既有 correlate_incidents 完全一致，便于复用）
_KILL_CHAIN_MAP = {
    "recon": ["scan", "probe", "recon"],
    "initial_access": ["4625", "brute", "phishing", "exploit"],
    "execution": ["4688", "process_create", "cmd", "powershell"],
    "persistence": ["4698", "7045", "scheduled_task", "service_install", "startup"],
    "credential_access": ["mimikatz", "procdump", "lsass", "sekurlsa"],
    "lateral_movement": ["4672", "4648", "psexec", "wmic", "winrm"],
    "exfiltration": ["5156", "connection_outbound", "c2", "beacon"],
    "defense_evasion": ["1102", "audit_clear", "wevtutil"],
}

_TITLE_MAP = {
    "recon": "侦察扫描",
    "initial_access": "初始入侵",
    "execution": "代码执行",
    "persistence": "持久化驻留",
    "credential_access": "凭据窃取",
    "lateral_movement": "横向移动",
    "exfiltration": "外连C2",
    "defense_evasion": "防御绕过",
    "general": "通用告警",
}

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


class IncidentCorrelator:
    """事件归并器：统一 ``keyword`` / ``semantic`` 两种归并模式."""

    def __init__(self) -> None:
        self._llm = AgentLLM()

    # ─────────────────────────────────────────────
    # 统一入口
    # ─────────────────────────────────────────────
    async def cluster(
        self,
        events: Optional[list] = None,
        mode: str = "semantic",
        host_id: Optional[int] = None,
        time_window_minutes: int = 60,
        user: Optional[dict] = None,
    ) -> list:
        """统一归并入口.

        Args:
            events: 关键字模式的原始告警行（``alerts``）。semantic 模式可留空（内部拉取）。
            mode: ``keyword`` | ``semantic``。
            host_id: 限定主机（可选）。
            time_window_minutes: 时间窗（semantic 模式过滤可疑事件）。
            user: 当前用户（用于 LLM 审计）。

        Returns:
            keyword 模式返回 incident 字典列表；semantic 模式返回 cluster 字典列表。
        """
        if mode == "keyword":
            alerts = events if events is not None else self._fetch_alerts(host_id)
            return self._cluster_keyword(alerts)
        return await self._cluster_semantic(
            host_id=host_id,
            time_window_minutes=time_window_minutes,
            user=user,
        )

    # ─────────────────────────────────────────────
    # keyword 模式：复用既有分组逻辑
    # ─────────────────────────────────────────────
    @staticmethod
    def _fetch_alerts(host_id: Optional[int]) -> list:
        with get_connection() as conn:
            if host_id:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE host_id=? ORDER BY last_seen_at DESC LIMIT 200",
                    [host_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts ORDER BY last_seen_at DESC LIMIT 200"
                ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _cluster_keyword(alerts: list) -> list:
        """按 rule_name + 攻击链阶段分组（与既有 correlate_incidents 行为一致）."""
        if not alerts:
            return []

        rule_groups = defaultdict(list)
        for a in alerts:
            rule_groups[a.get("rule_name", "unknown")].append(a)

        incidents: list[dict] = []
        for rule_name, group in rule_groups.items():
            if not group:
                continue
            stage = "general"
            rule_lower = (rule_name or "").lower()
            for s, keywords in _KILL_CHAIN_MAP.items():
                if any(kw in rule_lower for kw in keywords):
                    stage = s
                    break

            first_seen = min(
                a.get("first_seen_at") or a.get("last_seen_at") or "" for a in group
            )
            last_seen = max(
                a.get("last_seen_at") or a.get("first_seen_at") or "" for a in group
            )
            hosts = list(
                set(str(a.get("host_id", "")) for a in group if a.get("host_id"))
            )

            alerts_sorted = sorted(group, key=lambda x: x.get("last_seen_at") or "")
            mitre_ids = [a["mitre_attack"] for a in group if a.get("mitre_attack")]

            incidents.append(
                {
                    "title": f"{_TITLE_MAP.get(stage, '通用告警')}: {rule_name}",
                    "description": (
                        f"规则 {rule_name} 触发 {len(group)} 次告警。"
                        f"时间窗口: {first_seen} ~ {last_seen}。"
                        f"涉及主机: {', '.join(hosts)}。"
                    ),
                    "severity": group[0].get("severity", "medium"),
                    "host_ids": hosts,
                    "alert_ids": [a.get("id") for a in group if a.get("id")],
                    "kill_chain": stage,
                    "mitre_ids": list(set(mitre_ids)),
                    "alert_count": len(group),
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                }
            )
        return incidents

    # ─────────────────────────────────────────────
    # semantic 模式：跨主机 AI 语义聚类（带确定性降级）
    # ─────────────────────────────────────────────
    async def _cluster_semantic(
        self,
        host_id: Optional[int],
        time_window_minutes: int,
        user: Optional[dict],
    ) -> list:
        """对可疑安全事件做语义聚类；LLM 不可用时回退字段聚类。

        返回 cluster 字典列表（已持久化到 incident_clusters）。
        """
        suspicious = self._fetch_suspicious_events(host_id, time_window_minutes)
        if not suspicious:
            return []

        clusters = await self._try_llm_cluster(suspicious, user)
        if not clusters:
            # LLM 降级或解析失败 → 确定性字段聚类
            clusters = self._deterministic_cluster(suspicious, time_window_minutes)

        # 持久化 + 组装返回
        result = []
        for c in clusters:
            member_ids = [str(i) for i in c.get("member_event_ids", [])]
            host_ids = sorted(
                set(str(e.get("host_id", "")) for e in suspicious if str(e.get("id", "")) in member_ids)
            )
            confidence = self._cluster_confidence(suspicious, member_ids)
            agg = self._verdict_agg(suspicious, member_ids)
            cluster_id = IncidentCluster.create(
                title=c.get("title", "未命名归并簇"),
                severity=c.get("severity", "medium"),
                confidence=confidence,
                member_event_ids=member_ids,
                host_ids=host_ids,
                summary=c.get("summary", ""),
                ai_verdict_agg=agg,
            )
            result.append(
                {
                    "cluster_id": cluster_id,
                    "title": c.get("title", "未命名归并簇"),
                    "severity": c.get("severity", "medium"),
                    "confidence": confidence,
                    "member_event_ids": member_ids,
                    "host_ids": host_ids,
                    "summary": c.get("summary", ""),
                    "ai_verdict_agg": agg,
                    "mode": "semantic",
                }
            )
        return result

    @staticmethod
    def _fetch_suspicious_events(
        host_id: Optional[int], time_window_minutes: int
    ) -> list:
        """拉取被 AI 标记为 suspicious 的安全事件（跨主机）。"""
        sql = (
            "SELECT * FROM security_events "
            "WHERE json_extract(ai_verdict, '$.label') = 'suspicious'"
        )
        params: list = []
        if host_id:
            sql += " AND host_id = ?"
            params.append(host_id)
        if time_window_minutes and time_window_minutes > 0:
            sql += f" AND timestamp >= datetime('now', '-{int(time_window_minutes)} minutes')"
        sql += " ORDER BY timestamp ASC"
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    async def _try_llm_cluster(self, events: list, user: Optional[dict]) -> list:
        """用 AgentLLM 做语义聚类；失败/降级返回空列表（交由确定性聚类兜底）."""
        try:
            brief = []
            for e in events:
                verdict = _safe_json_loads(e.get("ai_verdict")) or {}
                ev = _safe_json_loads(e.get("evidence")) or {}
                brief.append(
                    {
                        "id": str(e.get("id")),
                        "host_id": e.get("host_id"),
                        "host": e.get("host_id"),
                        "event_type": e.get("event_type"),
                        "severity": e.get("severity"),
                        "attack_type": verdict.get("attack_type", ""),
                        "reason": (verdict.get("reason") or "")[:80],
                        "ts": e.get("timestamp"),
                        "ip": _extract_ip(ev),
                    }
                )
            prompt = (
                "你是一名安全事件聚类分析师。下面是若干被 AI 判定为可疑(suspicious)的安全事件"
                "（可能跨多台主机）。请将语义相关、可能属于同一起攻击或同一根因的事件归并为若干簇。\n"
                "事件字段说明：id, host_id, event_type, severity, attack_type, reason(原因), ts(时间), ip(来源IP)。\n"
                "请返回 JSON 数组，每个元素格式：\n"
                '{"title": "簇标题(中文,<=30字)", '
                '"severity": "critical|high|medium|low", '
                '"member_event_ids": [事件id列表], '
                '"summary": "该簇的攻击叙事摘要(中文,<=200字)"}\n'
                "要求：每个事件必须且仅属于一个簇；不要遗漏任何事件；不要编造事件中不存在的信息。\n"
                "仅输出 JSON 数组，不要附加任何解释或 markdown。\n\n"
                f"事件列表：\n{json.dumps(brief, ensure_ascii=False, default=str)}"
            )
            resp = await self._llm.call(prompt, user=user)
            if resp.get("degraded") or not resp.get("content"):
                logger.info("IncidentCorrelator: LLM 降级，回退确定性聚类")
                return []
            parsed = _extract_json_array(resp["content"])
            if not parsed:
                logger.warning("IncidentCorrelator: LLM 返回无法解析为簇数组，回退确定性聚类")
                return []
            # 校验 member_event_ids 都在已知事件集中
            valid_ids = {str(e.get("id")) for e in events}
            clusters = []
            seen = set()
            for c in parsed:
                mids = [str(i) for i in (c.get("member_event_ids") or []) if str(i) in valid_ids]
                mids = [i for i in mids if i not in seen]
                if not mids:
                    continue
                seen.update(mids)
                clusters.append(
                    {
                        "title": str(c.get("title", "未命名归并簇"))[:60],
                        "severity": _normalize_severity(c.get("severity")),
                        "member_event_ids": mids,
                        "summary": str(c.get("summary", ""))[:500],
                    }
                )
            # 把未被任何簇覆盖的事件补为单事件簇
            for e in events:
                eid = str(e.get("id"))
                if eid not in seen:
                    seen.add(eid)
                    clusters.append(
                        {
                            "title": f"单事件：{e.get('event_type', eid)}",
                            "severity": _normalize_severity(e.get("severity")),
                            "member_event_ids": [eid],
                            "summary": f"未被归并的可疑事件（host_id={e.get('host_id')}）。",
                        }
                    )
            return clusters
        except Exception as exc:  # noqa: BLE001
            logger.warning("IncidentCorrelator LLM 聚类异常（降级）: %s", exc)
            return []

    @staticmethod
    def _deterministic_cluster(events: list, time_window_minutes: int) -> list:
        """确定性字段聚类：按 (host_id, event_type, ip) 归并。

        不依赖 LLM，保证在 AI 不可用时仍可产出稳定结果。
        """
        groups: dict[tuple, list] = defaultdict(list)
        for e in events:
            ev = _safe_json_loads(e.get("evidence")) or {}
            key = (
                e.get("host_id"),
                e.get("event_type"),
                _extract_ip(ev),
            )
            groups[key].append(e)

        clusters = []
        for (hid, etype, ip), members in groups.items():
            sev = max(
                (_SEVERITY_RANK.get(str(m.get("severity", "")).lower(), 0) for m in members),
                default=0,
            )
            severity = next((k for k, v in _SEVERITY_RANK.items() if v == sev), "medium")
            host_label = f"主机 {hid}" if hid is not None else "未知主机"
            ip_label = f"（源IP {ip}）" if ip else ""
            clusters.append(
                {
                    "title": f"{host_label} · {etype or '未知类型'}{ip_label}",
                    "severity": severity,
                    "member_event_ids": [m.get("id") for m in members],
                    "summary": (
                        f"基于字段（主机/事件类型/来源IP）的确定性归并，共 {len(members)} 条可疑事件。"
                        f"时间窗 {time_window_minutes} 分钟。AI 语义聚类当前不可用，已自动降级。"
                    ),
                }
            )
        return clusters

    @staticmethod
    def _cluster_confidence(events: list, member_ids: list) -> float:
        """簇置信度 = 成员 ai_verdict.confidence 均值（无则 0.5）。"""
        id_set = set(member_ids)
        confs = []
        for e in events:
            if str(e.get("id", "")) not in id_set:
                continue
            verdict = _safe_json_loads(e.get("ai_verdict")) or {}
            c = verdict.get("confidence")
            if isinstance(c, (int, float)):
                confs.append(float(c))
        if not confs:
            return 0.5
        return round(sum(confs) / len(confs), 2)

    @staticmethod
    def _verdict_agg(events: list, member_ids: list) -> dict:
        """聚合成员 ai_verdict：标签分布 / 平均置信度 / 攻击类型。"""
        id_set = set(member_ids)
        labels: dict[str, int] = defaultdict(int)
        attack_types: list[str] = []
        confs: list[float] = []
        for e in events:
            if str(e.get("id", "")) not in id_set:
                continue
            verdict = _safe_json_loads(e.get("ai_verdict")) or {}
            label = verdict.get("label", "unknown")
            labels[label] = labels.get(label, 0) + 1
            at = verdict.get("attack_type")
            if at:
                attack_types.append(at)
            c = verdict.get("confidence")
            if isinstance(c, (int, float)):
                confs.append(float(c))
        return {
            "labels": dict(labels),
            "avg_confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
            "attack_types": list(dict.fromkeys(attack_types)),
            "member_count": len(member_ids),
        }


# ─────────────────────────────────────────────
# 模块级辅助
# ─────────────────────────────────────────────
def _safe_json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_severity(sev: Any) -> str:
    s = str(sev or "medium").lower()
    return s if s in ("critical", "high", "medium", "low") else "medium"


def _extract_ip(evidence: Any) -> str:
    """从 evidence（可能嵌套）中提取首个来源 IP。"""
    if not isinstance(evidence, dict):
        return ""
    for key in ("source_ip", "src_ip", "ip", "ip_address", "dest_ip"):
        v = evidence.get(key)
        if isinstance(v, str) and v:
            return v
    for v in evidence.values():
        if isinstance(v, dict):
            ip = _extract_ip(v)
            if ip:
                return ip
    return ""


def _extract_json_array(text: str) -> list:
    """从 LLM 文本中稳健提取 JSON 数组（容忍 markdown 代码块 / 前后噪声）。"""
    if not text:
        return []
    s = text.strip()
    # 去掉 ```json ... ``` 包裹
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("[") :] if "[" in s else s
    # 找到第一个 [ 与最后一个 ]
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        arr = json.loads(s[start : end + 1])
        return arr if isinstance(arr, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
