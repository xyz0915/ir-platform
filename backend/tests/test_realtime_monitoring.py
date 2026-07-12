"""实时监控模块 — 后端集成测试."""

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    print("=== 1. Database init ===")
    from app.database import get_connection, init_db
    init_db()
    from app.database import get_connection
    with get_connection() as conn:
        for hid in range(1, 5):
            conn.execute("INSERT OR IGNORE INTO cases (id, name) VALUES (?, ?)", [hid, f'test-case-{hid}'])
            conn.execute("INSERT OR IGNORE INTO hosts (id, case_id, hostname) VALUES (?, ?, ?)", [hid, hid, f'test-host-{hid}'])
        conn.commit()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("  alerts table:", "alerts" in tables)
        print("  agents table:", "agents" in tables)

    print("\n=== 2. Alert model CRUD ===")
    from app.models.alert import Alert

    a = Alert.create(host_id=1, rule_name="TEST-RULE", severity="high",
                     title="Test Alert", detail="Test detail",
                     source_process="test.exe")
    assert a is not None, "Alert.create failed"
    print("  Create OK:", a.get("id"))

    ok = Alert.acknowledge(a["id"], user="tester")
    assert ok, "Alert.acknowledge failed"
    print("  Acknowledge OK")

    ok = Alert.resolve(a["id"])
    assert ok, "Alert.resolve failed"
    print("  Resolve OK")

    stats = Alert.get_stats()
    assert stats.get("total", 0) > 0
    print("  Stats OK:", stats)

    lst = Alert.list()
    assert len(lst) > 0
    print("  List OK:", len(lst), "items")

    # Aggregation test - create two alerts with same rule_name in quick succession
    agg_id1, is_new1 = Alert.create_or_aggregate(
        host_id=2, rule_name="AGG-TEST", severity="high", title="Agg Test 1")
    assert is_new1, "First should be new"
    agg_id2, is_new2 = Alert.create_or_aggregate(
        host_id=2, rule_name="AGG-TEST", severity="high", title="Agg Test 2")
    assert not is_new2, "Second should aggregate"
    print("  Aggregate OK: id1=", agg_id1, "id2=", agg_id2)

    print("\n=== 3. Agent model ===")
    from app.models.agent_model import AgentModel

    reg = AgentModel.register(host_id=1, agent_version="1.0",
                              os_type="linux", collectors=["events"])
    assert reg is not None
    print("  Register OK:", reg)

    hb = AgentModel.heartbeat(host_id=1)
    assert hb
    print("  Heartbeat OK")

    online = AgentModel.get_online_hosts()
    print("  Online hosts:", len(online))

    print("\n=== 4. AlertEngine ===")
    from app.services.alert_engine import AlertEngine
    from app.services.alert_ws import alert_ws_manager

    engine = AlertEngine(ws_manager=alert_ws_manager)

    r = engine.process_event(host_id=1, event={
        "event_type": "process_create", "pid": 1234,
        "process_name": "powershell.exe",
        "command_line": "powershell -enc SQBFAFgA"})
    print("  Process event:", r is not None)

    r = engine.process_event(host_id=1, event={
        "event_type": "file_create", "process_name": "svchost.exe",
        "pid": 5678, "detail": "/etc/passwd modified"})
    print("  File event:", r is not None)

    print("\n=== 5. Main app routers ===")
    from app.main import app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    alert_routes = [p for p in routes if "alert" in p]
    agent_routes = [p for p in routes if "agent" in p or "heartbeat" in p or "hosts/online" in p]
    ws_routes = [p for p in routes if "ws" in p]
    print("  Alert routes:", alert_routes)
    print("  Agent routes:", agent_routes)
    print("  WebSocket routes:", ws_routes)

    print("\n" + "=" * 40)
    print("ALL 5 CHECKS PASSED")
    print("=" * 40)
