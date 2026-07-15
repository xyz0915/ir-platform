"""事件富化服务测试 — 风险评分/影响范围/处置建议."""
import sys
sys.path.insert(0, '.')
from app.services.event_enrichment import (
    calculate_risk_score, _check_path_risk, generate_remediation,
    assess_impact_scope, get_host_stats, get_event_context,
)

def print_result(name, ok, detail=""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}")
    if detail: print(f"     {detail}")

# Test 1: 严重事件风险评分
event = {"severity": "critical", "matched_rules": [{"rule_id": 1}, {"rule_id": 2}], "ioc_matches": ["8.8.8.8"]}
score = calculate_risk_score(event)
print_result("严重事件风险分 >= 90", score >= 90, f"score={score}")

# Test 2: info 事件风险评分
event2 = {"severity": "info", "matched_rules": [], "ioc_matches": []}
score2 = calculate_risk_score(event2)
print_result("info 事件风险分 <= 10", score2 <= 10, f"score={score2}")

# Test 3: 路径风险检测 - 高危
ev_high = {"file_path": "C:\\Users\\xyz\\AppData\\Local\\Temp\\evil.exe"}
result = _check_path_risk(ev_high)
print_result("高危路径检测", result == "high", f"result={result}")

# Test 4: 路径风险检测 - 正常
ev_normal = {"file_path": "C:\\Program Files\\app\\normal.exe"}
result2 = _check_path_risk(ev_normal)
print_result("正常路径检测", result2 == "normal", f"result={result2}")

# Test 5: 处置建议 - process_start
rem = generate_remediation({"event_type": "process_start", "evidence": {"pid": 4352, "process_path": "C:\\Temp\\evil.exe"}})
print_result("process_start 处置建议", len(rem) >= 2 and "taskkill" in rem[0]["command"], f"steps={len(rem)}")

# Test 6: 处置建议 - registry
rem2 = generate_remediation({"event_type": "registry_modify", "evidence": {"key_path": "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"}})
print_result("registry 处置建议", len(rem2) >= 1 and "reg delete" in rem2[0]["command"])

# Test 7: 处置建议 - network
rem3 = generate_remediation({"event_type": "network_outbound", "evidence": {"remote_address": "185.234.72.18"}})
print_result("network 处置建议", len(rem3) >= 1 and "netsh" in rem3[0]["command"])

# Test 8: 处置建议 - file_create
rem4 = generate_remediation({"event_type": "file_create", "evidence": {"file_path": "C:\\Temp\\ransom.exe"}})
print_result("file_create 处置建议", len(rem4) >= 1 and "del /F" in rem4[0]["command"])

# Test 9: 处置建议 - 未知类型（fallback 隔离）
rem5 = generate_remediation({"event_type": "dns_query", "evidence": {}})
print_result("未知类型回退建议", len(rem5) >= 1 and "隔离" in rem5[0]["title"])

# Test 10: JSON 字符串参数
event_str = {"severity": "high", "matched_rules": "[]", "ioc_matches": "[]", "evidence": "{}"}
score_str = calculate_risk_score(event_str)
print_result("JSON 字符串参数不崩溃", score_str >= 55 and score_str <= 65, f"score={score_str}")

# Test 11: 空 evidence
event_empty = {"severity": "medium", "matched_rules": [], "ioc_matches": []}
score_empty = calculate_risk_score(event_empty)
print_result("空参数不崩溃", score_empty >= 35 and score_empty <= 45, f"score={score_empty}")
