"""临时测试脚本."""
from app.services.alert_engine import AlertEngine
from app.services.alert_ws import alert_ws_manager

engine = AlertEngine(ws_manager=alert_ws_manager)

events = [
    {"event_type": "process_start", "rule_name": "certutil_download",
     "severity": "high", "process_name": "certutil.exe",
     "pid": 1234, "command_line": "file download detected"},
    {"event_type": "process_start", "rule_name": "orphan_process",
     "severity": "critical", "process_name": "orphan.exe",
     "pid": 5678, "command_line": "suspicious"},
    {"event_type": "network", "rule_name": "unknown_rule",
     "process_name": "random.exe"},
]

new_alerts = engine.evaluate_events(host_id=5, events=events)
print("New alerts:", len(new_alerts))
for a in new_alerts:
    print(f'  #{a.get("id")} [{a.get("severity")}] {a.get("title")}')
print("AlertEngine test PASSED")
