"""案件编号自动生成 + 优先级选择 — 回归测试."""
import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app
from app.services.auth_service import get_current_user

# 使用 FastAPI 标准依赖覆盖
app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "test"}
client = TestClient(app)

total_tests = 0
passed_tests = 0


def print_result(name, ok, detail=""):
    global total_tests, passed_tests
    total_tests += 1
    if ok:
        passed_tests += 1
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}")
    if detail:
        print(f"     {detail}")


def cleanup():
    """清理测试创建的案件."""
    r = client.get("/api/cases?size=100")
    if r.status_code == 200:
        for item in r.json().get("data", {}).get("items", []):
            if item["name"].startswith("[Test]"):
                client.delete(f"/api/cases/{item['id']}")


def test_auto_generate_case_number():
    """Test 1: 案件编号自动生成（格式校验）"""
    r = client.post("/api/cases", json={"name": "[Test] 自动编号测试", "description": "test"})
    data = r.json()
    ok = r.status_code == 200 and data["data"]["case_number"].startswith("CASE-")
    print_result("自动生成编号", ok, f"编号: {data['data']['case_number']}")
    return data["data"]["id"] if ok else None


def test_manual_case_number():
    """Test 2: 手动填编号创建成功"""
    r = client.post("/api/cases", json={
        "name": "[Test] 手动编号测试",
        "case_number": "MANUAL-001",
        "description": "manual"
    })
    data = r.json()
    ok = r.status_code == 200 and data["data"]["case_number"] == "MANUAL-001"
    print_result("手动编号创建", ok, f"编号: {data['data']['case_number']}")
    return data["data"]["id"] if ok else None


def test_duplicate_case_number():
    """Test 3: 重复编号返回 409"""
    # 先创建一个
    client.post("/api/cases", json={
        "name": "[Test] 重复编号测试",
        "case_number": "DUP-001"
    })
    r = client.post("/api/cases", json={
        "name": "[Test] 重复编号测试2",
        "case_number": "DUP-001"
    })
    ok = r.status_code == 409
    print_result("重复编号返回409", ok, f"HTTP {r.status_code}")


def test_priority_save_and_return():
    """Test 4: 优先级保存后正确返回"""
    r = client.post("/api/cases", json={
        "name": "[Test] 优先级测试",
        "priority": "high",
        "description": "priority test"
    })
    data = r.json()
    ok = r.status_code == 200 and data["data"].get("priority") == "high"
    print_result("优先级保存(high)", ok, f"priority: {data['data'].get('priority')}")


def test_priority_default_medium():
    """Test 5: 优先级不选时默认 medium"""
    r = client.post("/api/cases", json={
        "name": "[Test] 默认优先级测试",
        "description": "default priority test"
    })
    data = r.json()
    ok = r.status_code == 200 and data["data"].get("priority") == "medium"
    print_result("默认优先级(medium)", ok, f"priority: {data['data'].get('priority')}")


# === 运行测试 ===
print("=" * 50)
print("案件编号自动生成 + 优先级 — 回归测试")
print("=" * 50)

cleanup()

test_auto_generate_case_number()
test_manual_case_number()
test_duplicate_case_number()
test_priority_save_and_return()
test_priority_default_medium()

cleanup()

print("=" * 50)
print(f"共执行 {total_tests} 个测试，通过 {passed_tests} 个，失败 {total_tests - passed_tests} 个")
print("=" * 50)

if passed_tests == total_tests:
    sys.exit(0)
else:
    sys.exit(1)
