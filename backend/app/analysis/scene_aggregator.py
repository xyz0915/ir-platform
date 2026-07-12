"""攻击场景汇聚模块 — 将融合事件按时间窗+同一主机归并为攻击场景.

场景汇聚（Scene Aggregation）与攻击链（Attack Chain）的边界：
- 攻击链：按固定顺序步骤匹配（如 进程→连接→注册表），有严格时序
- 场景汇聚：按时间窗 + 相关TTP归并，不限定顺序，更灵活
"""

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 场景类型定义
SCENE_TYPES = {
    "webshell_attack": {
        "name": "WebShell 攻击",
        "related_types": {"webshell_detected", "cmd_execution", "suspicious_connection", "process_create"},
        "risk_weight": 1.0,
    },
    "lateral_movement": {
        "name": "横向移动",
        "related_types": {"rdp_bruteforce", "psexec_service", "smb_connection", "credential_dump"},
        "risk_weight": 1.0,
    },
    "privilege_escalation": {
        "name": "权限提升",
        "related_types": {"uac_bypass", "token_manipulation", "service_install", "process_injection"},
        "risk_weight": 0.9,
    },
    "persistence": {
        "name": "持久化驻留",
        "related_types": {"registry_persistence", "scheduled_task", "service_persistence", "startup_item", "wmi_persistence"},
        "risk_weight": 0.8,
    },
    "credential_access": {
        "name": "凭据窃取",
        "related_types": {"lsass_dump", "mimikatz", "credential_dump", "keylog"},
        "risk_weight": 1.0,
    },
    "defense_evasion": {
        "name": "防御绕过",
        "related_types": {"antivirus_tamper", "firewall_disable", "etw_amsi_tamper", "process_hide"},
        "risk_weight": 0.7,
    },
    "command_and_control": {
        "name": "C2 通信",
        "related_types": {"beacon_connection", "dns_tunnel", "https_outbound", "dga_domain"},
        "risk_weight": 0.9,
    },
    "discovery": {
        "name": "信息收集",
        "related_types": {"network_scan", "user_enum", "domain_enum", "process_enum"},
        "risk_weight": 0.5,
    },
}


class SceneAggregator:
    """攻击场景汇聚器.

    将融合事件列表中的单条告警按时间窗 + 关联 attack_type 归并为场景对象。
    """

    TIME_WINDOW_MINUTES = 30
    _SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

    @classmethod
    def aggregate(cls, incidents: list[dict], host_id: int = None) -> list[dict]:
        """将融合事件汇聚为攻击场景.

        Args:
            incidents: 融合事件列表（来自 AnalysisService._aggregate_incidents 的输出）
            host_id: 主机 ID（可选，用于标记）

        Returns:
            攻击场景列表 [{scene_id, type, name, risk_level, steps[], start_time, end_time, ...}]
        """
        if not incidents:
            return []

        # 1. 按时间排序
        sorted_inc = sorted(incidents, key=lambda x: x.get("timestamp", "") or x.get("first_seen", ""))

        # 2. 时间窗聚类
        scenes = []
        used = set()

        for i, inc in enumerate(sorted_inc):
            if i in used:
                continue
            inc_type = inc.get("type", "").replace(" ×", "").replace("×", "").strip().lower()

            # 查找匹配的场景类型
            scene_type = cls._match_scene_type(inc_type)
            if not scene_type:
                continue

            # 初始化场景
            scene = {
                "scene_id": f"SCENE-{host_id or 'X'}-{len(scenes) + 1}",
                "type": scene_type,
                "name": SCENE_TYPES[scene_type]["name"],
                "risk_level": inc.get("severity", "medium"),
                "host_id": host_id,
                "steps": [inc],
                "start_time": inc.get("timestamp") or inc.get("first_seen", ""),
                "end_time": inc.get("timestamp") or inc.get("first_seen", ""),
                "total_alerts": 1,
                "confidence": inc.get("confidence", 0),
                "needs_review": inc.get("needs_review", False),
                "attack_chain": [],  # 攻击链步骤（如果有）
            }
            used.add(i)

            # 在当前场景的时间窗内查找同类告警
            window_start = cls._parse_time(scene["start_time"])
            for j in range(i + 1, len(sorted_inc)):
                if j in used:
                    continue
                j_time = cls._parse_time(sorted_inc[j].get("timestamp") or sorted_inc[j].get("first_seen", ""))
                if window_start and j_time:
                    if (j_time - window_start).total_seconds() > cls.TIME_WINDOW_MINUTES * 60:
                        break  # 超出时间窗

                j_type = sorted_inc[j].get("type", "").replace(" ×", "").replace("×", "").strip().lower()
                j_scene = cls._match_scene_type(j_type)

                if j_scene == scene_type or (j_scene and SCENE_TYPES.get(j_scene, {}).get("risk_weight", 0) >= 0.7):
                    scene["steps"].append(sorted_inc[j])
                    scene["total_alerts"] += 1
                    scene["end_time"] = sorted_inc[j].get("timestamp") or sorted_inc[j].get("first_seen", "")
                    scene["confidence"] = max(scene["confidence"], sorted_inc[j].get("confidence", 0))
                    scene["risk_level"] = max(
                        scene["risk_level"],
                        sorted_inc[j].get("severity", "medium"),
                        key=lambda s: cls._SEV_RANK.get(s, 0)
                    )
                    used.add(j)

            if scene["steps"]:
                scenes.append(scene)

        # 3. 补充未归入场景的独立告警
        for i, inc in enumerate(sorted_inc):
            if i not in used:
                scenes.append({
                    "scene_id": f"SCENE-{host_id or 'X'}-INDEP-{i + 1}",
                    "type": "uncategorized",
                    "name": "独立告警",
                    "risk_level": inc.get("severity", "medium"),
                    "host_id": host_id,
                    "steps": [inc],
                    "start_time": inc.get("timestamp") or inc.get("first_seen", ""),
                    "end_time": inc.get("timestamp") or inc.get("first_seen", ""),
                    "total_alerts": 1,
                    "confidence": inc.get("confidence", 0),
                    "needs_review": inc.get("needs_review", False),
                    "attack_chain": [],
                })

        return scenes

    @classmethod
    def _match_scene_type(cls, inc_type: str) -> str | None:
        """根据告警类型匹配场景类型."""
        for scene_key, scene_def in SCENE_TYPES.items():
            for related in scene_def["related_types"]:
                if related in inc_type:
                    return scene_key
        return None

    @staticmethod
    def _parse_time(ts: Any) -> datetime | None:
        """解析时间字符串."""
        if not ts:
            return None
        if isinstance(ts, datetime):
            return ts
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(str(ts)[:26], fmt)
            except (ValueError, TypeError):
                continue
        return None
