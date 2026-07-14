"""日志检索 search 端点回归测试 — 验证 case_id 通过 host_id 间接匹配的修复"""
import sys
sys.path.insert(0, '.')

from app.services.log_importer import search


def test_search_with_case_id():
    """测试 case_id=1000 时能查到数据（修复前是 0）"""
    r = search(case_id=1000, page=1, page_size=20)
    assert r['total'] == 22, f"case_id=1000 应有 22 条，实际 {r['total']}"
    print(f"✓ case_id=1000 返回 {r['total']} 条（期望 22）")


def test_search_with_host_id():
    """测试 host_id 单条件搜索"""
    r = search(host_id=1002, page=1, page_size=20)
    assert r['total'] == 7, f"host_id=1002 应有 7 条"
    print(f"✓ host_id=1002 返回 {r['total']} 条（期望 7）")

    r = search(host_id=1001, page=1, page_size=20)
    assert r['total'] == 8, f"host_id=1001 应有 8 条"
    print(f"✓ host_id=1001 返回 {r['total']} 条（期望 8）")

    r = search(host_id=1000, page=1, page_size=20)
    assert r['total'] == 7, f"host_id=1000 应有 7 条"
    print(f"✓ host_id=1000 返回 {r['total']} 条（期望 7）")


def test_search_case_and_host():
    """测试 case_id + host_id 组合"""
    r = search(case_id=1000, host_id=1002, page=1, page_size=20)
    assert r['total'] == 7, f"组合查询应有 7 条"
    print(f"✓ case_id=1000 + host_id=1002 返回 {r['total']} 条（期望 7）")

    r = search(case_id=1000, host_id=1001, page=1, page_size=20)
    assert r['total'] == 8, f"组合查询应有 8 条"
    print(f"✓ case_id=1000 + host_id=1001 返回 {r['total']} 条（期望 8）")


def test_search_wrong_case_id():
    """测试错误的 case_id 返回 0（不应误判）"""
    r = search(case_id=99999, page=1, page_size=20)
    assert r['total'] == 0, f"错误 case_id 应返回 0"
    print(f"✓ case_id=99999 返回 0 条（边界正确）")


def test_search_collector_type():
    """测试 collector_type 过滤"""
    r = search(case_id=1000, collector_type='processes', page=1, page_size=20)
    assert r['total'] > 0, f"processes 采集器应有数据"
    print(f"✓ case_id=1000 + collector_type=processes 返回 {r['total']} 条")


def test_search_items_have_hostname():
    """测试返回 items 包含 hostname 字段（case_name 修复后）"""
    r = search(case_id=1000, host_id=1002, page=1, page_size=20)
    if r['items']:
        item = r['items'][0]
        assert 'hostname' in item, "items 应含 hostname"
        # case_name 可能为 None（因为 agent_imports.case_id 是 NULL）
        # 但 hostname 应该正确
        assert item.get('hostname') == 'DESKTOP-KLAUVOL', f"hostname 应为 DESKTOP-KLAUVOL，实际 {item.get('hostname')}"
        print(f"✓ items 包含 hostname=DESKTOP-KLAUVOL，case_name={item.get('case_name')}")


if __name__ == "__main__":
    print("=" * 60)
    print("日志检索 search 端点回归测试")
    print("=" * 60)
    test_search_with_case_id()
    test_search_with_host_id()
    test_search_case_and_host()
    test_search_wrong_case_id()
    test_search_collector_type()
    test_search_items_have_hostname()
    print("=" * 60)
    print("✓ 全部 6 项测试通过")
