"""案件详情聚合接口（GET /api/cases/{id}/summary）单元测试.

P0+P1 改造验证：
  - 派生严重度取关联告警最高严重度（忽略 dismissed）
  - 告警态势统计（总数 / 严重度分布 / 状态分布）
  - 主机态势（总数 / 状态分布 / 在线 Agent）
  - 处置闭环进度（done/total/percent）
  - 取证任务进度
  - IOC 命中关联威胁情报（intel 回灌）
  - TTP（kill chain + 技战术，来自 threat_intel.attck）
  - AI 分析结论解析（risk_score / attack_chain / recommendation）

测试隔离：重定向 settings.DB_PATH 到临时库并 init_db()，不污染运行库。
"""

import json
import os
import tempfile

import app.config as _cfg
import app.database as _db

# 在导入任何模型前重定向数据库路径，使用临时库
_TMP_DB = os.path.join(tempfile.gettempdir(), "ir_test_case_summary.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
_cfg.settings.DB_PATH = _TMP_DB
_db.init_db()

from app.database import get_connection  # noqa: E402
from app.services.case_summary import get_case_summary  # noqa: E402


def _seed():
    with get_connection() as conn:
        for t in (
            "security_events", "threat_intel", "iocs", "ioc_hits",
            "triage_tasks", "remediation_checklist", "alerts",
            "agents", "hosts", "cases",
        ):
            conn.execute(f"DELETE FROM {t}")
        cur = conn.execute(
            "INSERT INTO cases (name, case_number, description, status, priority) "
            "VALUES ('T-CASE', 'QA-TEST', '测试案件', 'open', 'high')"
        )
        case_id = cur.lastrowid

        # 两台主机
        h1 = conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status, collection_time) "
            "VALUES (?, 'hostA', '10.0.0.1', 'windows', 'imported', '2026-08-01 09:30:00')",
            (case_id,),
        ).lastrowid
        h2 = conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status, collection_time) "
            "VALUES (?, 'hostB', '10.0.0.2', 'linux', 'analyzed', '2026-08-01 09:35:00')",
            (case_id,),
        ).lastrowid

        # 在线 Agent（仅 hostA）
        conn.execute(
            "INSERT INTO agents (host_id, agent_id, agent_version, status) VALUES (?, 'AGENT-A', '1.0', 'online')",
            (h1,),
        )
        conn.execute(
            "INSERT INTO agents (host_id, agent_id, agent_version, status) VALUES (?, 'AGENT-B', '1.0', 'offline')",
            (h2,),
        )

        # 告警：critical(open)/high(acknowledged)/medium(dismissed)
        conn.execute(
            "INSERT INTO alerts (host_id, case_id, rule_name, rule_label, title, severity, status, count, "
            "first_seen_at, last_seen_at) VALUES (?, ?, 'R1', 'R1', 'R1-告警', 'critical', 'open', 5, '2026-08-01 10:00:00', '2026-08-01 11:00:00')",
            (h1, case_id),
        )
        conn.execute(
            "INSERT INTO alerts (host_id, case_id, rule_name, rule_label, title, severity, status, count, "
            "first_seen_at, last_seen_at) VALUES (?, ?, 'R2', 'R2', 'R2-告警', 'high', 'acknowledged', 2, '2026-08-01 10:05:00', '2026-08-01 11:05:00')",
            (h1, case_id),
        )
        conn.execute(
            "INSERT INTO alerts (host_id, case_id, rule_name, rule_label, title, severity, status, count, "
            "first_seen_at, last_seen_at) VALUES (?, ?, 'R3', 'R3', 'R3-告警', 'medium', 'dismissed', 1, '2026-08-01 10:10:00', '2026-08-01 11:10:00')",
            (h2, case_id),
        )

        # 处置清单（case_id 关联，2 项 1 完成）
        items = [
            {"id": "i1", "text": "隔离主机", "checked": True, "source": "ai"},
            {"id": "i2", "text": "取证固定", "checked": False, "source": "manual"},
        ]
        conn.execute(
            "INSERT INTO remediation_checklist (host_id, case_id, items) VALUES (?, ?, ?)",
            (h1, case_id, json.dumps(items, ensure_ascii=False)),
        )

        # 取证任务：pending / running / done
        conn.execute(
            "INSERT INTO triage_tasks (host_id, scope, status) VALUES (?, '[''file_hashes'']', 'pending')", (h1,)
        )
        conn.execute(
            "INSERT INTO triage_tasks (host_id, scope, status) VALUES (?, '[''file_hashes'']', 'running')", (h2,)
        )
        conn.execute(
            "INSERT INTO triage_tasks (host_id, scope, status, finished_at) VALUES (?, '[''file_hashes'']', 'done', '2026-08-01 12:00:00')",
            (h1,),
        )

        # IOC 命中 + iocs + threat_intel
        conn.execute(
            "INSERT INTO ioc_hits (host_id, ioc_type, ioc_value, severity) VALUES (?, 'ip', '1.2.3.4', 'high')",
            (h1,),
        )
        conn.execute(
            "INSERT INTO ioc_hits (host_id, ioc_type, ioc_value, severity) VALUES (?, 'domain', 'evil.com', 'medium')",
            (h1,),
        )
        ioc1 = conn.execute(
            "INSERT INTO iocs (ioc_type, ioc_value, enabled) VALUES ('ip', '1.2.3.4', 1)"
        ).lastrowid
        ioc2 = conn.execute(
            "INSERT INTO iocs (ioc_type, ioc_value, enabled) VALUES ('domain', 'evil.com', 1)"
        ).lastrowid
        ti = json.dumps
        conn.execute(
            "INSERT INTO threat_intel (ioc_id, ioc_type, ioc_value, provider, risk_score, judgments, attck) "
            "VALUES (?, 'ip', '1.2.3.4', 'threatbook', 90, ?, ?)",
            (ioc1, ti(["malicious"]), ti([{"technique_id": "T1071", "name": "C2"}])),
        )
        conn.execute(
            "INSERT INTO threat_intel (ioc_id, ioc_type, ioc_value, provider, risk_score, judgments, attck) "
            "VALUES (?, 'domain', 'evil.com', 'virustotal', 70, ?, ?)",
            (ioc2, ti(["suspicious"]), ti([{"technique_id": "T1059", "name": "Command Scripting"}])),
        )

        # 安全事件：attack_stage + ai_analysis
        conn.execute(
            "INSERT INTO security_events (id, host_id, event_type, severity, event_key, attack_stage, ai_analysis, timestamp) "
            "VALUES ('evt-1', ?, 'ioc_match', 'high', 'ioc-1', 'command_and_control', ?, '2026-08-01 11:30:00')",
            (h1, ti({"risk_score": 88, "attack_chain": "C2->Exfil", "recommendation": "阻断外联"})),
        )
        conn.execute(
            "INSERT INTO security_events (id, host_id, event_type, severity, event_key, attack_stage, ai_analysis, timestamp) "
            "VALUES ('evt-2', ?, 'process_start', 'medium', 'proc-1', 'execution', NULL, '2026-08-01 11:35:00')",
            (h2,),
        )

    return case_id


def test_derived_severity_ignores_dismissed():
    case_id = _seed()
    s = get_case_summary(case_id)
    # 最高未忽略告警为 critical
    assert s["case"]["derived_severity"] == "critical"
    assert s["case"]["priority"] == "high"


def test_alert_stats():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert s["alert_stats"]["total"] == 3
    assert s["alert_stats"]["by_severity"].get("critical") == 1
    assert s["alert_stats"]["by_severity"].get("high") == 1
    assert s["alert_stats"]["by_severity"].get("medium") == 1
    assert s["alert_stats"]["by_status"].get("open") == 1
    assert s["alert_stats"]["by_status"].get("acknowledged") == 1
    assert s["alert_stats"]["by_status"].get("dismissed") == 1
    # Top 告警按严重度+count 排序，首条应为 critical
    assert s["top_alerts"][0]["severity"] == "critical"


def test_host_stats_and_online_agents():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert s["host_stats"]["total"] == 2
    assert s["host_stats"]["by_status"].get("imported") == 1
    assert s["host_stats"]["by_status"].get("analyzed") == 1
    assert s["host_stats"]["online_agents"] == 1
    assert len(s["host_stats"]["risk_top"]) == 2


def test_remediation_progress():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert s["remediation_progress"]["total"] == 2
    assert s["remediation_progress"]["done"] == 1
    assert s["remediation_progress"]["percent"] == 50


def test_triage_progress():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert s["triage_progress"]["pending"] == 1
    assert s["triage_progress"]["running"] == 1
    assert s["triage_progress"]["done"] == 1
    assert s["triage_progress"]["failed"] == 0
    assert s["triage_progress"]["total"] == 3


def test_ioc_joins_threat_intel():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert len(s["ioc_summary"]) == 2
    ip_entry = next(e for e in s["ioc_summary"] if e["ioc_value"] == "1.2.3.4")
    assert ip_entry["intel"] is not None
    assert ip_entry["intel"]["risk_score"] == 90
    assert ip_entry["intel"]["judgments"] == ["malicious"]


def test_ttp_from_threat_intel_attck():
    case_id = _seed()
    s = get_case_summary(case_id)
    tech_ids = {t["technique_id"] for t in s["ttp_summary"]["techniques"]}
    assert "T1071" in tech_ids
    assert "T1059" in tech_ids
    stages = {k["stage"] for k in s["ttp_summary"]["kill_chain"]}
    assert "command_and_control" in stages
    assert "execution" in stages


def test_ai_summary_parsed():
    case_id = _seed()
    s = get_case_summary(case_id)
    assert s["ai_summary"]["risk_score"] == 88
    assert s["ai_summary"]["attack_chain"] == "C2->Exfil"
    assert "阻断外联" in (s["ai_summary"]["recommendation"] or "")


def test_timeline_present():
    case_id = _seed()
    s = get_case_summary(case_id)
    titles = {ev["title"] for ev in s["timeline"]}
    assert "案件创建" in titles
    assert "首批主机接入" in titles
    assert "首次告警" in titles
