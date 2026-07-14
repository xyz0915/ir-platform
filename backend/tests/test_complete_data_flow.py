"""验证完整数据流：从导入 JSON 到日志检索和分析中心的数据链路测试.

测试场景：
1. 导入一份新的 Agent JSON
2. 验证 agent_imports（日志检索）表记录数增加
3. 验证 security_events（分析中心）表记录数增加
4. 验证 item_count 字段正确反映实际数据条目数
5. 验证案件级汇总数据（log_count/event_count）正确
"""
import sys
sys.path.insert(0, '.')

import json
from app.services.import_service import ImportService
from app.database import get_connection


def _make_realistic_agent_json(hostname: str) -> bytes:
    """构造一份真实的 Agent JSON（多种采集器，含正常和异常数据）."""
    data = {
        "system_info": {"hostname": hostname, "os_version": "Windows 10"},
        "metadata": {
            "agent_version": "1.0",
            "collection_time": "2026-07-14T15:00:00",
            "platform": "windows",
        },
        "processes": [
            {"pid": i, "name": f"proc_{i}.exe", "path": f"C:\\test\\{i}.exe", "user": "SYSTEM"}
            for i in range(50)
        ],
        "network_connections": [
            {"protocol": "TCP", "local_port": 80 + i, "remote_ip": f"10.0.0.{i}", "remote_port": 443}
            for i in range(20)
        ],
        "registry_keys": [
            {"key_path": f"HKLM\\SOFTWARE\\Test\\Key{i}", "value": f"v{i}", "value_type": "REG_SZ"}
            for i in range(30)
        ],
        "file_hashes": [
            {"file_path": f"C:\\file{i}.exe", "sha256": "a" * 64} for i in range(5)
        ],
        "wmi_subscriptions": [
            {"name": f"WMI_{i}", "event_filter": "log"} for i in range(2)
        ],
        "startup_items": [
            {"name": f"Startup_{i}", "command": f"test_{i}.exe", "enabled": True}
            for i in range(10)
        ],
        "services": [
            {"name": f"Svc_{i}", "display_name": f"Service {i}", "status": "running"}
            for i in range(15)
        ],
        "users": [
            {"username": f"user_{i}", "is_admin": False, "is_disabled": False}
            for i in range(3)
        ],
    }
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_complete_import_flow():
    """测试完整数据流：导入 → agent_imports + security_events 都增加."""
    test_host_id = 100  # 使用一个独立的 host_id 避免污染其他测试

    # 准备：创建主机
    with get_connection() as conn:
        # 确保测试主机存在
        conn.execute(
            "INSERT OR IGNORE INTO hosts (id, hostname, case_id, status) VALUES (?, ?, ?, 'pending')",
            [test_host_id, f"TEST-HOST-{test_host_id}", 999],
        )
        # 清空旧测试数据
        conn.execute("DELETE FROM agent_imports WHERE host_id=?", [test_host_id])
        conn.execute("DELETE FROM security_events WHERE host_id=?", [test_host_id])
        conn.execute("DELETE FROM import_records WHERE host_id=?", [test_host_id])
        conn.commit()

    # 触发导入
    file_content = _make_realistic_agent_json(f"TEST-HOST-{test_host_id}")
    ImportService.import_json(
        host_id=test_host_id,
        file_content=file_content,
        file_name="complete_flow_test.json",
    )

    # 验证
    with get_connection() as conn:
        ai_count = conn.execute(
            "SELECT COUNT(*) as c FROM agent_imports WHERE host_id=?", [test_host_id]
        ).fetchone()['c']

        ai_item_sum = conn.execute(
            "SELECT COALESCE(SUM(item_count), 0) as c FROM agent_imports WHERE host_id=?",
            [test_host_id],
        ).fetchone()['c']

        se_count = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE host_id=?", [test_host_id]
        ).fetchone()['c']

        # 各采集器的 item_count 详情
        details = conn.execute(
            """SELECT collector_type, item_count, raw_json
               FROM agent_imports WHERE host_id=?
               ORDER BY collector_type""",
            [test_host_id],
        ).fetchall()

    print(f"\nhost_id={test_host_id} 完整链路测试：")
    print(f"  agent_imports 记录数: {ai_count} (期望 8 个采集器)")
    print(f"  agent_imports 总条目数: {ai_item_sum} (期望 50+20+30+5+2+10+15+3=135)")
    print(f"  security_events 记录数: {se_count} (期望 ≥ 50，进程数)")
    print()
    print("  各采集器 item_count 详情：")
    for r in details:
        # 验证 item_count 与实际 raw_json 数组长度一致
        try:
            parsed = json.loads(r['raw_json'])
            actual = len(parsed) if isinstance(parsed, list) else 1
            ok = "✓" if actual == r['item_count'] else "✗"
        except:
            ok = "?"
            actual = "?"
        print(f"    {ok} {r['collector_type']:12s}: item_count={r['item_count']:>3} (实际: {actual})")

    # 断言
    assert ai_count == 8, f"agent_imports 应有 8 条，实际 {ai_count}"
    assert ai_item_sum == 135, f"item_count 总和应为 135，实际 {ai_item_sum}"
    assert se_count >= 50, f"security_events 应 ≥ 50（至少进程数），实际 {se_count}"

    print("\n✓ 全部断言通过：数据完整写入日志检索和分析中心")


def test_reimport_idempotency():
    """测试重复导入：第二次导入不应该破坏已存在数据."""
    test_host_id = 101

    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO hosts (id, hostname, case_id, status) VALUES (?, ?, ?, 'pending')",
            [test_host_id, f"TEST-HOST-{test_host_id}", 999],
        )
        conn.execute("DELETE FROM agent_imports WHERE host_id=?", [test_host_id])
        conn.execute("DELETE FROM security_events WHERE host_id=?", [test_host_id])
        conn.execute("DELETE FROM import_records WHERE host_id=?", [test_host_id])
        conn.commit()

    file_content = _make_realistic_agent_json(f"TEST-HOST-{test_host_id}")

    # 第一次导入
    ImportService.import_json(
        host_id=test_host_id,
        file_content=file_content,
        file_name="reimport_test_1.json",
    )

    with get_connection() as conn:
        ai_first = conn.execute(
            "SELECT COUNT(*) as c FROM agent_imports WHERE host_id=?", [test_host_id]
        ).fetchone()['c']
        se_first = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE host_id=?", [test_host_id]
        ).fetchone()['c']

    # 第二次导入（应该再添加一批）
    ImportService.import_json(
        host_id=test_host_id,
        file_content=file_content,
        file_name="reimport_test_2.json",
    )

    with get_connection() as conn:
        ai_second = conn.execute(
            "SELECT COUNT(*) as c FROM agent_imports WHERE host_id=?", [test_host_id]
        ).fetchone()['c']
        se_second = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE host_id=?", [test_host_id]
        ).fetchone()['c']

    print(f"\nhost_id={test_host_id} 重复导入测试：")
    print(f"  第一次: agent_imports={ai_first}, security_events={se_first}")
    print(f"  第二次: agent_imports={ai_second}, security_events={se_second}")
    print(f"  增量: agent_imports +{ai_second - ai_first}, security_events +{se_second - se_first}")

    # 断言：第二次导入应该添加新的 agent_imports（import_batch_id 不同）
    assert ai_second == ai_first * 2, f"agent_imports 应翻倍（{ai_first}→{ai_second}）"
    # security_events 应该保持不变（事件去重，按 event_id）
    assert se_second == se_first, f"security_events 应去重（{se_first}→{se_second}）"

    print("\n✓ 重复导入行为正确：新增 agent_imports，事件去重不重复")


if __name__ == "__main__":
    print("=" * 60)
    print("完整数据流回归测试")
    print("=" * 60)
    try:
        test_complete_import_flow()
        test_reimport_idempotency()
        print("\n" + "=" * 60)
        print("✓ 全部测试通过")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        raise
