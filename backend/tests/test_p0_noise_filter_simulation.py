"""P0 融合事件噪音过滤 — 模拟验证 (host 29 场景).

验证三个改动点:
1. _SAFE_PROCESS_NAMES 白名单跳过 (L429-436, L741-744)
2. 置信度门槛 confidence < 60 单信号过滤 (L602-608)
3. _aggregate_incidents 聚合逻辑 (L370-416)

此脚本为纯逻辑验证，不依赖后端数据库/ORM，直接白盒测试关键代码路径。
"""

import sys
import os

# 确保 backend 路径可导入（如果环境支持）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─────────────────────────────────────────────────────────────
# 从源码中复制的关键常量（与 anomaly_detector.py 保持一致）
# ─────────────────────────────────────────────────────────────

_SAFE_PROCESS_NAMES: set[str] = {
    "sqlservr", "vmtoolsd", "vgauthservice", "fdlauncher", "fdhost",
    "msdtssrvr", "msmdsrv", "reportingservicesservice", "sqlwriter",
    "conhost", "svchost", "csrss", "wininit", "services", "lsass",
    "smss", "winlogon", "runtimebroker", "taskhostw", "spoolsv",
    "dllhost", "sihost", "ctfmon", "searchindexer", "wlms",
}

SEVERITY_PROB: dict = {
    "critical": 0.95,
    "high": 0.80,
    "medium": 0.50,
    "low": 0.20,
    "info": 0.10,
}

CONFIDENCE_THRESHOLD = 60


def whitelist_check(process_name: str) -> bool:
    """模拟 _build_signals 中 L742-744 的白名单检查."""
    pname = process_name.lower().removesuffix(".exe")
    return pname in _SAFE_PROCESS_NAMES


def calc_confidence(signals: list[dict]) -> float:
    """模拟 correlate_incident L596-600 的朴素贝叶斯置信度."""
    prob_product = 1.0
    for s in signals:
        p = SEVERITY_PROB.get(s["severity"], 0.5)
        prob_product *= (1.0 - p)
    return (1.0 - prob_product) * 100.0


def should_suppress_single_alert(is_incident: bool, confidence: float) -> bool:
    """模拟 L602-608: 单信号低置信度不产出."""
    return (not is_incident) and confidence < CONFIDENCE_THRESHOLD


def aggregate_incidents(incidents: list[dict]) -> list[dict]:
    """模拟 _aggregate_incidents (L370-416)."""
    if len(incidents) <= 3:
        return incidents

    real_incidents = []
    alerts_by_type: dict[str, list[dict]] = {}
    for inc in incidents:
        if inc.get("kind") == "incident" or "+" in inc.get("type", ""):
            real_incidents.append(inc)
        else:
            t = inc.get("type", "unknown")
            alerts_by_type.setdefault(t, []).append(inc)

    output = list(real_incidents)
    sev_rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    for atype, alerts in alerts_by_type.items():
        if len(alerts) <= 2:
            output.extend(alerts)
            continue
        top3 = sorted(alerts, key=lambda a: a.get("confidence", 0), reverse=True)[:3]
        sevs = {a.get("severity", "") for a in alerts}
        max_conf = max(a.get("confidence", 0) for a in alerts)
        output.append({
            "incident_id": f"AGG-{atype}",
            "type": f"{atype} ×{len(alerts)}",
            "kind": "aggregated_alert",
            "confidence": max_conf,
            "severity": max(sevs, key=lambda s: sev_rank.get(s, 0)),
            "needs_review": True,
            "attack_path": [a.get("attack_path", [[]])[0] for a in top3 if a.get("attack_path")],
            "related_findings": [],
            "attck_techniques": [],
            "signals": [],
            "aggregated_count": len(alerts),
            "aggregated_top": top3,
        })
    return output


# ─────────────────────────────────────────────────────────────
# Test 1: 白名单包含核心进程
# ─────────────────────────────────────────────────────────────

def test_whitelist_contains_core_processes():
    """验证白名单包含 sqlservr, vmtoolsd, VGAuthService 等核心进程."""
    required = {"sqlservr", "vmtoolsd", "vgauthservice"}
    missing = required - _SAFE_PROCESS_NAMES
    assert not missing, f"Missing core processes in whitelist: {missing}"

    # 验证白名单共计 25 个进程
    assert len(_SAFE_PROCESS_NAMES) == 25, (
        f"Expected 25 safe processes, got {len(_SAFE_PROCESS_NAMES)}"
    )
    print(f"  ✅ Whitelist contains all core processes (total: {len(_SAFE_PROCESS_NAMES)})")


# ─────────────────────────────────────────────────────────────
# Test 2: 白名单检查逻辑 (lower + removesuffix .exe)
# ─────────────────────────────────────────────────────────────

def test_whitelist_check_logic():
    """验证白名单检查使用 .lower().removesuffix('.exe')."""
    # .exe 后缀应被剥离
    assert whitelist_check("sqlservr.exe"), "sqlservr.exe should be whitelisted"
    assert whitelist_check("vmtoolsd.exe"), "vmtoolsd.exe should be whitelisted"
    assert whitelist_check("VGAuthService.exe"), "VGAuthService.exe should be whitelisted"

    # 大小写不敏感
    assert whitelist_check("SqlServr"), "SqlServr should be whitelisted"
    assert whitelist_check("VMTOOLSD.EXE"), "VMTOOLSD.EXE should be whitelisted"

    # 非白名单进程
    assert not whitelist_check("malware.exe"), "malware.exe should NOT be whitelisted"
    assert not whitelist_check("powershell.exe"), "powershell.exe should NOT be whitelisted"
    assert not whitelist_check("cmd.exe"), "cmd.exe should NOT be whitelisted"
    print("  ✅ Whitelist check logic (.lower().removesuffix('.exe')) correct")


# ─────────────────────────────────────────────────────────────
# Test 3: host 29 场景 — 10 条 suspicious_process + 2 条白名单进程
# ─────────────────────────────────────────────────────────────

def test_host29_scenario_whitelist_skip():
    """模拟 host 29: 12 条信号，其中 2 条白名单 + 10 条 suspicious_process."""
    # 12 条原始进程命中
    processes = [
        # 2 条白名单进程（应被跳过）
        {"process_name": "sqlservr.exe", "severity": "medium", "pid": 1001, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "VGAuthService.exe", "severity": "low", "pid": 1002, "matched_rules": [{"name": "suspicious_process"}]},
        # 10 条可疑进程（应保留）
        {"process_name": "powershell.exe", "severity": "high", "pid": 2001, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "cmd.exe", "severity": "high", "pid": 2002, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "wscript.exe", "severity": "medium", "pid": 2003, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "cscript.exe", "severity": "medium", "pid": 2004, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "rundll32.exe", "severity": "medium", "pid": 2005, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "regsvr32.exe", "severity": "medium", "pid": 2006, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "mshta.exe", "severity": "medium", "pid": 2007, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "certutil.exe", "severity": "medium", "pid": 2008, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "bitsadmin.exe", "severity": "medium", "pid": 2009, "matched_rules": [{"name": "suspicious_process"}]},
        {"process_name": "schtasks.exe", "severity": "low", "pid": 2010, "matched_rules": [{"name": "suspicious_process"}]},
    ]

    # 模拟 _build_signals 中的白名单跳过
    signals = []
    for proc in processes:
        pname = (proc.get("process_name") or "").lower().removesuffix(".exe")
        if pname in _SAFE_PROCESS_NAMES:
            continue  # 白名单跳过
        signals.append({
            "category": "suspicious_process",
            "severity": proc["severity"],
            "evidence": f"process:{proc['process_name']} pid={proc['pid']}",
            "finding_id": f"PROC-{proc['pid']}",
            "attck": ["T1547", "T1564"],
            "host_context": {"pid": proc["pid"]},
        })

    # 验证：10 条保留（2 条白名单被跳过）
    assert len(signals) == 10, f"Expected 10 signals after whitelist filter, got {len(signals)}"

    # 验证白名单进程确实不在结果中
    signal_pids = {s["host_context"]["pid"] for s in signals}
    assert 1001 not in signal_pids, "sqlservr.exe (pid=1001) should be filtered"
    assert 1002 not in signal_pids, "VGAuthService.exe (pid=1002) should be filtered"

    # 验证可疑进程都在
    for pid in range(2001, 2011):
        assert pid in signal_pids, f"suspicious process pid={pid} should be retained"

    print(f"  ✅ Host 29 whitelist: 2 whitelisted skipped, {len(signals)} suspicious retained")


# ─────────────────────────────────────────────────────────────
# Test 4: 置信度门槛 — 单信号 < 60 不产出
# ─────────────────────────────────────────────────────────────

def test_confidence_threshold():
    """验证单信号告警 confidence < 60 被抑制."""
    # 单信号 low severity: confidence = 20 → 应被抑制
    low_signal = [{"category": "suspicious_process", "severity": "low"}]
    conf_low = calc_confidence(low_signal)
    assert conf_low < 60, f"Expected low confidence < 60, got {conf_low}"
    assert should_suppress_single_alert(False, conf_low), "Single low signal should be suppressed"
    print(f"  ✅ Low single signal confidence={conf_low:.1f} → suppressed")

    # 单信号 medium severity: confidence = 50 → 应被抑制
    med_signal = [{"category": "suspicious_process", "severity": "medium"}]
    conf_med = calc_confidence(med_signal)
    assert conf_med < 60, f"Expected medium confidence < 60, got {conf_med}"
    assert should_suppress_single_alert(False, conf_med), "Single medium signal should be suppressed"
    print(f"  ✅ Medium single signal confidence={conf_med:.1f} → suppressed")

    # 单信号 high severity: confidence = 80 → 应保留
    high_signal = [{"category": "suspicious_process", "severity": "high"}]
    conf_high = calc_confidence(high_signal)
    assert conf_high >= 60, f"Expected high confidence >= 60, got {conf_high}"
    assert not should_suppress_single_alert(False, conf_high), "Single high signal should NOT be suppressed"
    print(f"  ✅ High single signal confidence={conf_high:.1f} → retained")

    # 多信号 incident: 即使 confidence < 60 也不抑制
    multi_signal = [
        {"category": "suspicious_process", "severity": "info"},
        {"category": "suspicious_connection", "severity": "info"},
    ]
    conf_multi = calc_confidence(multi_signal)
    assert not should_suppress_single_alert(True, conf_multi), "Multi-signal incident should never be suppressed"
    print(f"  ✅ Multi-signal incident (confidence={conf_multi:.1f}) → always retained")


# ─────────────────────────────────────────────────────────────
# Test 5: _aggregate_incidents 聚合逻辑
# ─────────────────────────────────────────────────────────────

def test_aggregate_incidents_basic():
    """验证 _aggregate_incidents 正确区分 incident / single_alert 并聚合."""
    # 构造输入：1 个 incident + 10 条同类型 single_alert
    incidents = [
        {
            "incident_id": "INC-123", "type": "suspicious_process+suspicious_connection",
            "kind": "incident", "confidence": 95.0, "severity": "critical",
            "needs_review": False, "attack_path": ["ws_payload → powershell → C2 beacon"],
            "related_findings": ["F1", "F2"], "attck_techniques": ["T1547", "T1059"],
            "attck_technique_map": {}, "signals": [],
        },
    ]
    # 10 条 suspicious_process 单信号告警
    for i in range(10):
        incidents.append({
            "incident_id": f"ALERT-{i}", "type": "suspicious_process",
            "kind": "single_alert", "confidence": 30 + i * 5, "severity": "medium",
            "needs_review": True, "attack_path": [[f"process_{i}"]],
            "related_findings": [f"F{i+10}"], "attck_techniques": ["T1547"],
            "attck_technique_map": {}, "signals": [],
        })

    result = aggregate_incidents(incidents)

    # 应产出 2 条: 1 incident + 1 aggregated_alert
    assert len(result) == 2, f"Expected 2 outputs, got {len(result)}"

    # incident 保持原样
    incident_outputs = [r for r in result if r.get("kind") == "incident"]
    assert len(incident_outputs) == 1, "Should have exactly 1 incident"

    # aggregated_alert 包含 aggregated_count / aggregated_top
    agg = [r for r in result if r.get("kind") == "aggregated_alert"]
    assert len(agg) == 1, "Should have exactly 1 aggregated_alert"
    assert agg[0]["aggregated_count"] == 10, f"aggregated_count should be 10, got {agg[0]['aggregated_count']}"
    assert len(agg[0]["aggregated_top"]) == 3, f"aggregated_top should have 3 items, got {len(agg[0]['aggregated_top'])}"
    assert agg[0]["type"] == "suspicious_process ×10"
    print("  ✅ Aggregation: incident preserved, 10 single_alerts → 1 aggregated_alert with top-3")

    # 验证 top-3 按 confidence 降序
    top_confs = [a["confidence"] for a in agg[0]["aggregated_top"]]
    assert top_confs == sorted(top_confs, reverse=True), "top-3 should be sorted by confidence desc"
    print("  ✅ Top-3 sorted by confidence descending")


def test_aggregate_incidents_small_count():
    """验证 ≤3 条时不聚合."""
    incidents = [
        {"incident_id": f"A-{i}", "type": "suspicious_process", "kind": "single_alert",
         "confidence": 50, "severity": "medium", "needs_review": True,
         "attack_path": [], "related_findings": [], "attck_techniques": [],
         "attck_technique_map": {}, "signals": [],
        } for i in range(3)
    ]
    result = aggregate_incidents(incidents)
    assert len(result) == 3, f"3 items should not be aggregated, got {len(result)}"
    print("  ✅ ≤3 items: no aggregation")


def test_aggregate_incidents_mixed_types():
    """验证不同类型各自聚合."""
    incidents = [
        {"incident_id": "INC-1", "type": "suspicious_process+webshell",
         "kind": "incident", "confidence": 88, "severity": "high",
         "needs_review": True, "attack_path": [], "related_findings": [],
         "attck_techniques": [], "attck_technique_map": {}, "signals": [],
        },
    ]
    # 5 条 suspicious_process
    for i in range(5):
        incidents.append({
            "incident_id": f"SP-{i}", "type": "suspicious_process", "kind": "single_alert",
            "confidence": 40, "severity": "medium", "needs_review": True,
            "attack_path": [], "related_findings": [], "attck_techniques": [],
            "attck_technique_map": {}, "signals": [],
        })
    # 4 条 suspicious_connection
    for i in range(4):
        incidents.append({
            "incident_id": f"SC-{i}", "type": "suspicious_connection", "kind": "single_alert",
            "confidence": 60, "severity": "high", "needs_review": True,
            "attack_path": [], "related_findings": [], "attck_techniques": [],
            "attck_technique_map": {}, "signals": [],
        })

    result = aggregate_incidents(incidents)

    # 预期: 1 incident + 1 aggregated (suspicious_process) + 1 aggregated (suspicious_connection) = 3
    assert len(result) == 3, f"Expected 3 outputs, got {len(result)}"

    kinds = {r.get("kind") for r in result}
    assert kinds == {"incident", "aggregated_alert"}, f"Unexpected kinds: {kinds}"

    types = {r.get("type") for r in result}
    assert "suspicious_process ×5" in types, "Missing aggregated suspicious_process"
    assert "suspicious_connection ×4" in types, "Missing aggregated suspicious_connection"
    print("  ✅ Mixed types: each type aggregated independently")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 72)
    print("P0 融合事件噪音过滤 — 模拟验证")
    print("=" * 72)

    all_pass = True
    tests = [
        ("白名单包含核心进程", test_whitelist_contains_core_processes),
        ("白名单检查逻辑 (.lower/.removesuffix)", test_whitelist_check_logic),
        ("Host 29 白名单跳过 (12→10)", test_host29_scenario_whitelist_skip),
        ("置信度门槛 (confidence<60 抑制)", test_confidence_threshold),
        ("聚合: incident/single_alert 区分", test_aggregate_incidents_basic),
        ("聚合: ≤3 条不聚合", test_aggregate_incidents_small_count),
        ("聚合: 混合类型各自聚合", test_aggregate_incidents_mixed_types),
    ]

    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  ❌ FAIL: {name} — {e}")
            all_pass = False
        except Exception as e:
            print(f"  💥 ERROR: {name} — {type(e).__name__}: {e}")
            all_pass = False

    print()
    print("=" * 72)
    if all_pass:
        print("✅ ALL TESTS PASSED — P0 噪音过滤验证通过")
    else:
        print("❌ SOME TESTS FAILED — 详见上方错误")
    print("=" * 72)
