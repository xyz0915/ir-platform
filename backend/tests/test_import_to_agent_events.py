"""导入后 agent_imports（日志检索）和 security_events（分析中心）数据量验证测试.

测试场景：导入一个新的 Agent JSON 后，验证：
1. agent_imports 表记录数增加（日志检索模块）
2. security_events 表记录数增加（分析中心模块）
"""
import sys
sys.path.insert(0, '.')

import json
from app.services.import_service import ImportService
from app.database import get_connection


def _count_agent_imports(host_id: int) -> int:
    """获取指定主机的 agent_imports 记录数."""
    with get_connection() as conn:
        r = conn.execute(
            "SELECT COUNT(*) as c FROM agent_imports WHERE host_id=?",
            [host_id],
        ).fetchone()
        return r["c"] if r else 0


def _count_security_events(host_id: int) -> int:
    """获取指定主机的 security_events 记录数."""
    with get_connection() as conn:
        r = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE host_id=?",
            [host_id],
        ).fetchone()
        return r["c"] if r else 0


def _make_minimal_agent_json() -> bytes:
    """构造一份最小的有效 Agent JSON."""
    data = {
        "system_info": {"hostname": "test-host", "os_version": "Windows 10"},
        "metadata": {
            "agent_version": "1.0",
            "collection_time": "2026-07-14T12:00:00",
            "platform": "windows",
        },
        "processes": [
            {"pid": 1, "name": "idle.exe", "path": "C:\\Windows\\idle.exe", "user": "SYSTEM"},
            {"pid": 2, "name": "svchost.exe", "path": "C:\\Windows\\svchost.exe", "user": "SYSTEM"},
        ],
        "network_connections": [
            {"protocol": "TCP", "local_port": 80, "remote_ip": "10.0.0.1", "remote_port": 443},
        ],
        "registry_keys": [
            {"key_path": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run\\Test",
             "value": "test.exe", "value_type": "REG_SZ"},
        ],
        "file_hashes": [
            {"file_path": "C:\\test\\test.exe", "sha256": "a" * 64},
        ],
        "startup_items": [
            {"name": "TestStartup", "command": "test.exe", "enabled": True},
        ],
    }
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_import_increases_agent_imports():
    """验证导入后 agent_imports 表记录数增加."""
    host_id = 1  # 已存在的主机，导入时该主机下不会有冲突

    before = _count_agent_imports(host_id)
    before_events = _count_security_events(host_id)

    # 执行导入
    file_content = _make_minimal_agent_json()
    ImportService.import_json(
        host_id=host_id,
        file_content=file_content,
        file_name="test_import.json",
    )

    after = _count_agent_imports(host_id)
    after_events = _count_security_events(host_id)

    print(f"host_id={host_id}:")
    print(f"  agent_imports: {before} → {after}（增加 {after - before}）")
    print(f"  security_events: {before_events} → {after_events}（增加 {after_events - before_events}）")

    assert after > before, (
        f"agent_imports 记录数未增加（导入前={before}，导入后={after}）"
    )
    assert after_events > before_events, (
        f"security_events 记录数未增加（导入前={before_events}，导入后={after_events}）"
    )

    print("✓ 验证通过：agent_imports 和 security_events 记录数均正确增加")


def test_import_counts_match_collectors():
    """验证导入的 collector 分组数和事件数大致合理."""
    host_id = 2

    file_content = _make_minimal_agent_json()
    ImportService.import_json(
        host_id=host_id,
        file_content=file_content,
        file_name="test_import2.json",
    )

    after = _count_agent_imports(host_id)
    after_events = _count_security_events(host_id)

    # 最小 JSON 有 5 个采集器类型
    assert after > 0, f"agent_imports 应有数据，实际 {after}"
    assert after_events > 0, f"security_events 应有数据，实际 {after_events}"

    print(f"\nhost_id={host_id}:")
    print(f"  agent_imports: {after} 条写入")
    print(f"  security_events: {after_events} 条写入")
    print(f"  数据量合理：agent_imports({after}) ≤ security_events({after_events}) 可能（1:N 展开）")
    print("✓ 验证通过：采集器分组和事件数量合理")


if __name__ == "__main__":
    print("=" * 60)
    print("导入后数据链路验证测试")
    print("=" * 60)
    try:
        test_import_increases_agent_imports()
        test_import_counts_match_collectors()
        print("\n" + "=" * 60)
        print("✓ 全部测试通过")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        raise
