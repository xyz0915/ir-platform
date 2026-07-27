"""Phase 3 验证脚本 — Timeline 置信度标注."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent"))

print("=" * 60)
print("Phase 3 Timeline 置信度标注验证")
print("=" * 60)

errors = []

# ── 1. Import 检查 ──
try:
    from collectors.timeline import TimelineCollector
    print("  [PASS] from collectors.timeline import TimelineCollector")
except Exception as e:
    print(f"  [FAIL] import: {e}")
    errors.append(("import", str(e)))

# ── 2. 进程事件置信度 ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [{"pid": 1, "name": "test.exe", "start_time": "2026-07-27T10:00:00"}],
        "network": {},
        "logs": {},
        "files": {},
        "browser": {},
        "security": {},
    })
    assert len(result) > 0, "Expected at least 1 event"
    event = result[0]
    assert event["time_confidence"] == "high", f"Expected high, got {event['time_confidence']}"
    assert event["time_source"] == "psutil.create_time", f"Expected psutil.create_time, got {event['time_source']}"
    print(f"  [PASS] Process event: confidence={event['time_confidence']}, source={event['time_source']}")
except Exception as e:
    print(f"  [FAIL] Process confidence: {e}")
    errors.append(("process_confidence", str(e)))

# ── 3. 浏览器事件置信度 ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [],
        "network": {},
        "logs": {},
        "files": {},
        "browser": {
            "chrome": {
                "history": [{"url": "http://example.com", "title": "Example", "visit_time": "2026-07-27T10:00:00"}]
            }
        },
        "security": {},
    })
    assert len(result) > 0, "Expected at least 1 event"
    event = result[0]
    assert event["time_confidence"] == "medium", f"Expected medium, got {event['time_confidence']}"
    assert event["time_source"] == "browser.history.visit_time", f"Expected browser.history.visit_time, got {event['time_source']}"
    print(f"  [PASS] Browser event: confidence={event['time_confidence']}, source={event['time_source']}")
except Exception as e:
    print(f"  [FAIL] Browser confidence: {e}")
    errors.append(("browser_confidence", str(e)))

# ── 4. 日志事件置信度 ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [],
        "network": {},
        "logs": {"system": [{"time": "2026-07-27T10:00:00", "description": "Test log"}]},
        "files": {},
        "browser": {},
        "security": {},
    })
    assert len(result) > 0, "Expected at least 1 event"
    event = result[0]
    assert event["time_confidence"] == "high", f"Expected high, got {event['time_confidence']}"
    assert event["time_source"] == "Windows.EventLog.TimeCreated", f"Expected Windows.EventLog.TimeCreated, got {event['time_source']}"
    print(f"  [PASS] Log event: confidence={event['time_confidence']}, source={event['time_source']}")
except Exception as e:
    print(f"  [FAIL] Log confidence: {e}")
    errors.append(("log_confidence", str(e)))

# ── 5. 文件事件置信度（recent = high, suspicious = medium） ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [],
        "network": {},
        "logs": {},
        "files": {
            "recent_files": [{"path": "/test/file.txt", "modified": "2026-07-27T10:00:00", "size": 100}],
            "suspicious_files": [{"path": "/tmp/malware.exe", "modified": "2026-07-27T09:00:00", "reason": "suspicious"}],
        },
        "browser": {},
        "security": {},
    })
    # Find recent file event
    recent_events = [e for e in result if "文件修改" in e.get("description", "")]
    suspicious_events = [e for e in result if "可疑文件" in e.get("description", "")]
    
    if recent_events:
        e = recent_events[0]
        assert e["time_confidence"] == "high", f"Expected high for recent, got {e['time_confidence']}"
        assert e["time_source"] == "os.stat().st_mtime"
        print(f"  [PASS] Recent file event: confidence={e['time_confidence']}, source={e['time_source']}")
    
    if suspicious_events:
        e = suspicious_events[0]
        assert e["time_confidence"] == "medium", f"Expected medium for suspicious, got {e['time_confidence']}"
        assert e["time_source"] == "os.stat().st_mtime"
        print(f"  [PASS] Suspicious file event: confidence={e['time_confidence']}, source={e['time_source']}")
except Exception as e:
    print(f"  [FAIL] File confidence: {e}")
    errors.append(("file_confidence", str(e)))

# ── 6. 网络事件置信度 ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [],
        "network": {"dns_cache": [{"domain": "evil.com", "value": "1.2.3.4"}]},
        "logs": {},
        "files": {},
        "browser": {},
        "security": {},
    })
    assert len(result) > 0, "Expected at least 1 event"
    event = result[0]
    assert event["time_confidence"] == "low", f"Expected low, got {event['time_confidence']}"
    assert event["time_source"] == "collected_at", f"Expected collected_at, got {event['time_source']}"
    print(f"  [PASS] Network event: confidence={event['time_confidence']}, source={event['time_source']}")
except Exception as e:
    print(f"  [FAIL] Network confidence: {e}")
    errors.append(("network_confidence", str(e)))

# ── 7. 安全事件置信度 ──
try:
    tc = TimelineCollector()
    result = tc.build_from_results({
        "processes": [],
        "network": {},
        "logs": {},
        "files": {},
        "browser": {},
        "security": {"event_ids_summary": {"4625": 3}},
    })
    assert len(result) > 0, "Expected at least 1 event"
    event = result[0]
    assert event["time_confidence"] == "high", f"Expected high, got {event['time_confidence']}"
    assert event["time_source"] == "Windows.EventLog.TimeCreated"
    print(f"  [PASS] Security event: confidence={event['time_confidence']}, source={event['time_source']}")
except Exception as e:
    print(f"  [FAIL] Security confidence: {e}")
    errors.append(("security_confidence", str(e)))

# ── Summary ──
print()
print("=" * 60)
if errors:
    print(f"Results: {7 - len(errors)} passed, {len(errors)} failed")
    for name, err in errors:
        print(f"  FAIL: {name} → {err}")
    sys.exit(1)
else:
    print("Results: 7 passed, 0 failed")
    print("  ✓ All confidence annotation tests passed!")
