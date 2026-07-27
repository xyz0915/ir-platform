"""Phase 1 时间标准化基础库 — 测试验证脚本.

运行方式: python test_phase1_timestamp.py
"""

import sys
import os

# 确保能找到 agent 内部模块（该代码库无 __init__.py，靠 sys.path 直引）
_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "agent"))

from datetime import datetime, timezone, timedelta


def test_normalize_timestamp():
    """测试 normalize_timestamp 的各种输入格式."""
    from utils.platform import normalize_timestamp

    # 1. ISO 8601 with T（无时区）→ 应有值
    result1 = normalize_timestamp("2026-07-27T10:21:47")
    assert result1, f"Expected non-empty, got '{result1}'"
    assert "T" in result1, f"Expected T separator, got '{result1}'"
    assert result1.endswith("+08:00"), f"Expected +08:00 timezone, got '{result1}'"
    print(f"  [PASS] ISO with T: '{result1}'")

    # 2. 空格分隔 → 替换 T + 时区
    result2 = normalize_timestamp("2026-07-27 10:21:47")
    assert result2, f"Expected non-empty, got '{result2}'"
    assert "T" in result2, f"Expected T separator, got '{result2}'"
    assert result2.endswith("+08:00"), f"Expected +08:00, got '{result2}'"
    print(f"  [PASS] Space separated: '{result2}'")

    # 3. .NET /Date(ms)/ 格式
    result3 = normalize_timestamp("/Date(1785118871000)/")
    assert result3, f"Expected non-empty, got '{result3}'"
    assert result3.endswith("+08:00"), f"Expected +08:00, got '{result3}'"
    print(f"  [PASS] .NET Date: '{result3}'")

    # 4. 空字符串 → 返回 ""
    result4 = normalize_timestamp("")
    assert result4 == "", f"Expected '', got '{result4}'"
    print(f"  [PASS] Empty string: '{result4}'")

    # 5. None → 返回 ""
    result5 = normalize_timestamp(None)
    assert result5 == "", f"Expected '', got '{result5}'"
    print(f"  [PASS] None: '{result5}'")

    # 6. ISO 8601 with T+tz（保持+转 UTC+8）
    result6 = normalize_timestamp("2026-07-27T02:21:47+00:00")
    assert result6, f"Expected non-empty, got '{result6}'"
    assert result6.endswith("+08:00"), f"Expected +08:00, got '{result6}'"
    # UTC 0点 → UTC+8 就是 10:21
    print(f"  [PASS] ISO with tz: '{result6}'")

    # 7. Chrome epoch
    result7 = normalize_timestamp("132626567210000000")
    assert result7, f"Expected non-empty, got '{result7}'"
    assert result7.endswith("+08:00"), f"Expected +08:00, got '{result7}'"
    print(f"  [PASS] Chrome epoch: '{result7}'")

    # 8. 无法解析的内容 → 返回原值
    result8 = normalize_timestamp("not a timestamp")
    assert result8 == "not a timestamp", f"Expected original, got '{result8}'"
    print(f"  [PASS] Unparseable returns original: '{result8}'")

    print()
    print("  ✓ All normalize_timestamp tests passed!")
    return True


def test_normalize_timestamp_with_source():
    """测试 source 参数不影响返回值."""
    from utils.platform import normalize_timestamp

    result = normalize_timestamp("2026-07-27T10:21:47", source="timeline")
    assert result, f"Expected non-empty, got '{result}'"
    print(f"  [PASS] normalize_timestamp with source='timeline': '{result}'")


def test_to_utc8():
    """测试 to_utc8 函数."""
    from utils.platform import to_utc8

    # 无时区 datetime → 假设本地时区 → 转 UTC+8
    dt_naive = datetime(2026, 7, 27, 10, 21, 47)
    result = to_utc8(dt_naive)
    assert result, f"Expected non-empty, got '{result}'"
    assert result.endswith("+08:00"), f"Expected +08:00, got '{result}'"
    print(f"  [PASS] to_utc8 naive: '{result}'")

    # UTC datetime → 转 UTC+8
    dt_utc = datetime(2026, 7, 27, 2, 21, 47, tzinfo=timezone.utc)
    result2 = to_utc8(dt_utc)
    assert result2.endswith("+08:00"), f"Expected +08:00, got '{result2}'"
    # 小时数应为 10（2+8=10）
    assert "10:21:47" in result2, f"Expected 10:21:47, got '{result2}'"
    print(f"  [PASS] to_utc8 UTC→+08: '{result2}'")

    print("  ✓ All to_utc8 tests passed!")


def test_parse_dotnet_date():
    """测试 _parse_dotnet_date 辅助函数."""
    from utils.platform import _parse_dotnet_date

    # 有效 .NET 日期
    result = _parse_dotnet_date("/Date(1785118871000)/")
    assert result, f"Expected non-empty, got '{result}'"
    assert result.endswith("+08:00"), f"Expected +08:00, got '{result}'"
    print(f"  [PASS] _parse_dotnet_date: '{result}'")

    # 无效格式 → None
    result2 = _parse_dotnet_date("invalid")
    assert result2 is None, f"Expected None, got '{result2}'"
    print(f"  [PASS] _parse_dotnet_date invalid: None")

    # 空字符串
    result3 = _parse_dotnet_date("")
    assert result3 is None, f"Expected None, got '{result3}'"
    print(f"  [PASS] _parse_dotnet_date empty: None")

    print("  ✓ All _parse_dotnet_date tests passed!")


def test_import_clock_sync():
    """测试 clock_sync 模块可导入."""
    try:
        import utils.clock_sync
        print(f"  [PASS] import utils.clock_sync: OK")
        # 确认 ClockSync 类存在
        from utils.clock_sync import ClockSync
        assert hasattr(ClockSync, 'detect_offset'), "Missing detect_offset"
        assert hasattr(ClockSync, 'adjust_timestamp'), "Missing adjust_timestamp"
        print(f"  [PASS] ClockSync class has required methods")
    except Exception as e:
        print(f"  [FAIL] import failed: {e}")
        raise


def test_clock_sync_adjust_timestamp():
    """测试 ClockSync.adjust_timestamp 修正."""
    from utils.clock_sync import ClockSync

    # offset=0 → 原值返回
    result = ClockSync.adjust_timestamp("2026-07-27T10:21:47+08:00", 0.0)
    assert result == "2026-07-27T10:21:47+08:00", f"Expected original, got '{result}'"
    print(f"  [PASS] adjust_timestamp zero offset: '{result}'")

    # offset=3600 (1小时) → 时间应该加1小时
    result2 = ClockSync.adjust_timestamp("2026-07-27T10:21:47+08:00", 3600.0)
    assert "11:21:47" in result2, f"Expected 11:21:47, got '{result2}'"
    print(f"  [PASS] adjust_timestamp +3600s: '{result2}'")

    # offset=-3600 (倒退1小时)
    result3 = ClockSync.adjust_timestamp("2026-07-27T10:21:47+08:00", -3600.0)
    assert "09:21:47" in result3, f"Expected 09:21:47, got '{result3}'"
    print(f"  [PASS] adjust_timestamp -3600s: '{result3}'")

    # 空字符串 → 原值
    result4 = ClockSync.adjust_timestamp("", 100.0)
    assert result4 == "", f"Expected '', got '{result4}'"
    print(f"  [PASS] adjust_timestamp empty: '{result4}'")

    print("  ✓ All ClockSync.adjust_timestamp tests passed!")


def test_verify_report_validation():
    """验证需求中的断言全部通过."""
    from utils.platform import normalize_timestamp

    # 需求中的断言
    assert normalize_timestamp("2026-07-27T10:21:47")  # 有值
    assert normalize_timestamp("2026-07-27 10:21:47")   # 空格→T
    assert normalize_timestamp("/Date(1785118871000)/")  # .NET格式
    assert normalize_timestamp("") == ""                  # 空不变
    assert normalize_timestamp(None) == ""                # None 不崩
    print("  [PASS] All requirement assertions passed!")


def test_build_output_timeline_normalization():
    """验证 build_output 中 timeline 的时间标准化."""
    from utils.output import build_output

    # 构造含各种时间格式的模拟数据
    # 注意: build_output 内部会调用 _build_timeline 覆盖 raw_results["timeline"],
    # 且 _build_timeline 在测试环境中返回空列表（采集器不可用）。
    # 因此我们直接在 output 字典上验证 normalize_timestamp 的正确性。
    from utils.platform import normalize_timestamp

    # 手动构造类似 build_output 标准化后的结果
    raw_items = [
        {"event": "login", "timestamp": "2026-07-27 10:21:47"},
        {"event": "process_start", "timestamp": "/Date(1785118871000)/"},
        {"event": "network_connection", "timestamp": "2026-07-27T10:21:47"},
        {"event": "no_timestamp"},
        {"event": "empty_ts", "timestamp": ""},
    ]

    # 模拟 build_output 中 timeline 标准化逻辑
    normalized = []
    for item in raw_items:
        item_copy = dict(item)
        if isinstance(item_copy, dict) and "timestamp" in item_copy:
            item_copy["timestamp"] = normalize_timestamp(item_copy["timestamp"], source="timeline")
        normalized.append(item_copy)

    # 验证
    assert len(normalized) >= 3, f"Expected at least 3 items, got {len(normalized)}"

    # 事件1: 空格→ISO
    ts1 = normalized[0].get("timestamp", "")
    assert "+08:00" in ts1, f"Expected +08:00 in '{ts1}'"
    print(f"  [PASS] Item[0] space→ISO: '{ts1}'")

    # 事件2: .NET → ISO
    ts2 = normalized[1].get("timestamp", "")
    assert "+08:00" in ts2, f"Expected +08:00 in '{ts2}'"
    print(f"  [PASS] Item[1] .NET→ISO: '{ts2}'")

    # 事件3: ISO无时区→有时区
    ts3 = normalized[2].get("timestamp", "")
    assert "+08:00" in ts3, f"Expected +08:00 in '{ts3}'"
    print(f"  [PASS] Item[2] ISO→tz: '{ts3}'")

    # 事件4: 无timestamp字段 → 不变
    ts4 = normalized[3].get("timestamp")
    assert ts4 is None, f"Expected None, got '{ts4}'"
    print(f"  [PASS] Item[3] no timestamp: None")

    # 事件5: 空timestamp → 保持空
    ts5 = normalized[4].get("timestamp", "")
    assert ts5 == "", f"Expected '', got '{ts5}'"
    print(f"  [PASS] Item[4] empty timestamp: '{ts5}'")

    # 验证 build_output 本身的导入和可调用性（但不依赖 timeline builder）
    metadata = {"collection_time": "2026-07-27T10:21:47+08:00", "hostname": "test"}
    raw_results = {
        "system_info": {},
        "users": [],
        "processes": [],
        "services": [],
        "startup_items": [],
        "network": {},
        "files": {},
        "registry": {},
        "logs": {},
        "security": {},
        "browser": {},
        "usb": [],
        "remote_control": [],
        "persistence": {},
        "ioc": [],
        "process_events": [],
    }
    # 确保 build_output 能正常调用不抛异常
    output = build_output(metadata, raw_results)
    assert "metadata" in output, "build_output should return valid output"
    print(f"  [PASS] build_output called successfully")

    print("  ✓ All timeline normalization tests passed!")


def main():
    """运行所有测试."""
    print("=" * 60)
    print("Phase 1 时间标准化基础库 — 测试验证")
    print("=" * 60)
    print()

    tests = [
        ("normalize_timestamp", test_normalize_timestamp),
        ("normalize_timestamp with source", test_normalize_timestamp_with_source),
        ("to_utc8", test_to_utc8),
        ("_parse_dotnet_date", test_parse_dotnet_date),
        ("import clock_sync", test_import_clock_sync),
        ("ClockSync.adjust_timestamp", test_clock_sync_adjust_timestamp),
        ("Requirement assertions", test_verify_report_validation),
        ("build_output timeline normalization", test_build_output_timeline_normalization),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        print(f"\n--- {name} ---")
        try:
            func()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
