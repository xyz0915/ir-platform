#!/usr/bin/env python3
"""独立验证脚本 — 规则引擎动态引用 iocs 表 + IOC 启用开关闭环.

本脚本由 QA 独立编写，**实跑**而非读码验证前任工程师的改动：
  1. 动态引用命中：往 iocs 表插一个 enabled 的 ip 指标，取 known_bad_ip_1 规则
     (field=remote_address, list) evaluate 一条 remote_address=该 IP 的数据 → 断言命中。
  2. 静态兜底不变：iocs 表清空时，规则自带 values 仍命中；domain 类型 ioc 经 host
     字段映射命中。
  3. 禁用不命中：插一个 disabled 的 ip ioc (enabled=0) → 断言同数据不命中。
  4. 开关闭环：用 PUT /api/iocs/{id} 把 enabled 置 0 → 后续 evaluate 不命中；改回 1 → 命中恢复。
  5. 降级安全：iocs 表为空 / 缺类型 / 未映射 field → 现有 values 匹配行为不受影响。
  6. 无回归：known_bad_ip_1/2/3 经默认 values 仍按原逻辑命中（与改造前一致）。

设计：
  - 使用独立临时库，setuptools init_db() 载入默认规则与默认 IOC 种子。
  - 每个用例前清空 iocs 表，保证互相隔离。
  - 不修改任何业务源码，只做断言验证。

运行：backend/venv/Scripts/python.exe qa_ioc_verify.py
退出码：0=全部通过，1=存在失败项。
"""

import json
import sys
import traceback
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 必须在导入任何 app 模块前设置独立测试库 ──────────────────────────
from app.config import settings  # noqa: E402

QA_DB_PATH = str(BACKEND_DIR / "data" / "qa_ioc_verify.db")
db_file = Path(QA_DB_PATH)
if db_file.exists():
    db_file.unlink()

settings.DB_PATH = QA_DB_PATH

from app.database import init_db  # noqa: E402

init_db()

from app.models.ioc import Ioc  # noqa: E402
from app.rules.rule_engine import RuleEngine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

DEFAULT_RULES_PATH = BACKEND_DIR / "app" / "rules" / "default_rules.json"


def _load_default_rules() -> list:
    with open(DEFAULT_RULES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _find_rule(rules: list, name: str) -> dict:
    for r in rules:
        if r.get("name") == name:
            return r
    raise AssertionError(f"默认规则中未找到 {name}")


def _clear_iocs():
    """清空 iocs 表，保证用例隔离（仅依赖种子/用例自插数据）。"""
    for it in Ioc.list():
        Ioc.delete(it["id"])


def _conn_item(remote_address: str) -> dict:
    return {
        "remote_address": remote_address,
        "remote_port": 443,
        "protocol": "tcp",
        "process_name": "evil.exe",
    }


# ── 结果收集 ─────────────────────────────────────────────────────────
RESULTS: list = []


def _record(name: str, passed: bool, detail: str):
    RESULTS.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name}")
    print(f"       {detail}")


# ── 1. 动态引用命中 ──────────────────────────────────────────────────
def check_dynamic_enabled_hit(default_rules):
    _clear_iocs()
    rule = _find_rule(default_rules, "known_bad_ip_1")
    ip = "203.0.113.66"
    Ioc.create(ioc_type="ip", ioc_value=ip, source="user",
               description="QA动态引用", enabled=True)
    matches = RuleEngine.evaluate([_conn_item(ip)], [rule])
    passed = len(matches) == 1 and matches[0]["item"]["remote_address"] == ip
    _record("1.动态引用命中(enabled ip ioc)", passed,
            f"evaluate(remote_address={ip}) 命中数={len(matches)} "
            f"(期望1, 值={matches[0]['item']['remote_address'] if matches else None})")


# ── 2. 静态兜底 + domain 经 host 映射 ────────────────────────────────
def check_static_fallback_and_domain(default_rules):
    _clear_iocs()
    # 2a 静态兜底：iocs 为空，已知_bad_ip_1 自带 values[0] 仍命中
    rule = _find_rule(default_rules, "known_bad_ip_1")
    static_ip = rule["condition"]["values"][0]
    m = RuleEngine.evaluate([_conn_item(static_ip)], [rule])
    ok_a = len(m) == 1

    # 2b domain 经 host 字段映射：插入 enabled domain ioc，构造 field=host 规则
    dom = "evil-qa-static.example.com"
    Ioc.create(ioc_type="domain", ioc_value=dom, source="user", enabled=True)
    host_rule = {
        "name": "qa_domain_rule",
        "rule_type": "list",
        "condition": {"field": "host", "values": [], "match_mode": "exact"},
    }
    m2 = RuleEngine.evaluate([{"host": dom, "remote_address": "1.2.3.4"}], [host_rule])
    ok_b = len(m2) == 1

    passed = ok_a and ok_b
    _record("2.静态兜底 + domain@host映射", passed,
            f"静态values命中={ok_a}(ip={static_ip}); domain@host命中={ok_b}(dom={dom})")


# ── 3. 禁用不命中 ────────────────────────────────────────────────────
def check_disabled_no_hit(default_rules):
    _clear_iocs()
    rule = _find_rule(default_rules, "known_bad_ip_1")
    ip = "203.0.113.99"
    Ioc.create(ioc_type="ip", ioc_value=ip, source="user",
               description="QA禁用态", enabled=False)
    m = RuleEngine.evaluate([_conn_item(ip)], [rule])
    passed = len(m) == 0
    _record("3.禁用 ioc 不命中(disabled)", passed,
            f"evaluate(remote_address={ip}) 命中数={len(m)} (期望0)")


# ── 4. 开关闭环（PUT 端点）──────────────────────────────────────────
def check_toggle_closed_loop_via_api(client, headers, default_rules):
    _clear_iocs()
    rule = _find_rule(default_rules, "known_bad_ip_1")
    ip = "203.0.113.77"
    created = Ioc.create(ioc_type="ip", ioc_value=ip, source="user", enabled=True)
    ioc_id = created["id"]

    # 启用态 → 命中
    m_on = RuleEngine.evaluate([_conn_item(ip)], [rule])
    hit_on = len(m_on) == 1

    # PUT 关闭启用
    r1 = client.put(f"/api/iocs/{ioc_id}", json={"enabled": False}, headers=headers)
    updated_off = (r1.status_code == 200 and r1.json().get("data", {}).get("enabled") is False)
    m_off = RuleEngine.evaluate([_conn_item(ip)], [rule])
    hit_off = len(m_off) == 0

    # PUT 改回启用
    r2 = client.put(f"/api/iocs/{ioc_id}", json={"enabled": True}, headers=headers)
    updated_on = (r2.status_code == 200 and r2.json().get("data", {}).get("enabled") is True)
    m_back = RuleEngine.evaluate([_conn_item(ip)], [rule])
    hit_back = len(m_back) == 1

    passed = hit_on and updated_off and hit_off and updated_on and hit_back
    _record("4.开关闭环(PUT /api/iocs/{id})", passed,
            f"启用命中={hit_on}; PUT禁用 resp={r1.status_code}/enabled={updated_off}; "
            f"禁用后命中={hit_off}; PUT启用 resp={r2.status_code}/enabled={updated_on}; "
            f"恢复命中={hit_back}")


# ── 5. 降级安全：空表 / 缺类型 / 未映射 field ─────────────────────────
def check_degradation_safety(default_rules):
    _clear_iocs()
    rule = _find_rule(default_rules, "known_bad_ip_1")
    # 5a 空表：values[0] 仍命中（同 2a，已在 2 覆盖，这里再独立确认）
    static_ip = rule["condition"]["values"][0]
    ok_a = len(RuleEngine.evaluate([_conn_item(static_ip)], [rule])) == 1

    # 5b 缺类型/跨类型隔离：插入一个 hash 类型 ioc，ip 规则不应被污染
    # 用某个既不在静态 values 也不在 ip ioc 的 IP
    Ioc.create(ioc_type="hash", ioc_value="abc123def456", source="user", enabled=True)
    probe_ip = "198.51.100.23"
    ok_b = len(RuleEngine.evaluate([_conn_item(probe_ip)], [rule])) == 0

    # 5c 未映射 field 兜底：field=process_name 不在 FIELD_TO_IOC_TYPE，
    # 即便存在 ip ioc，也不会并入；仅依赖自身 values
    Ioc.create(ioc_type="ip", ioc_value="203.0.113.200", source="user", enabled=True)
    unmapped_rule = {
        "name": "qa_unmapped",
        "rule_type": "list",
        "condition": {"field": "process_name", "values": [], "match_mode": "exact"},
    }
    # evaluate 一条 process_name=203.0.113.200 的数据：因 field 不映射，不应命中
    ok_c = len(RuleEngine.evaluate(
        [{"process_name": "203.0.113.200"}], [unmapped_rule])) == 0

    passed = ok_a and ok_b and ok_c
    _record("5.降级安全(空表/跨类型/未映射field)", passed,
            f"空表values命中={ok_a}; hash类型不污染ip规则={ok_b}; "
            f"未映射field不并入ioc={ok_c}")


# ── 6. 无回归：known_bad_ip_1/2/3 经默认 values 命中 ──────────────────
def check_no_regression(default_rules):
    _clear_iocs()
    ok_all = True
    detail_parts = []
    for name in ("known_bad_ip_1", "known_bad_ip_2", "known_bad_ip_3"):
        rule = _find_rule(default_rules, name)
        val = rule["condition"]["values"][0]
        m = RuleEngine.evaluate([_conn_item(val)], [rule])
        ok = len(m) == 1
        ok_all = ok_all and ok
        detail_parts.append(f"{name}={ok}({val})")
    passed = ok_all
    _record("6.无回归(已知ip规则静态命中)", passed, "; ".join(detail_parts))


def main():
    print("=" * 70)
    print("QA 独立验证：规则引擎动态引用 iocs 表 + IOC 启用开关闭环")
    print(f"独立测试库: {QA_DB_PATH}")
    print("=" * 70)

    default_rules = _load_default_rules()

    # 准备 TestClient + 登录获取 token（PUT 端点需鉴权）
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json().get("data", {}).get("token")
    headers = {"Authorization": f"Bearer {token}"}
    if not token:
        _record("0.登录获取token", False, f"login resp={login.status_code} {login.text[:200]}")
        _print_summary_and_exit()

    try:
        check_dynamic_enabled_hit(default_rules)
        check_static_fallback_and_domain(default_rules)
        check_disabled_no_hit(default_rules)
        check_toggle_closed_loop_via_api(client, headers, default_rules)
        check_degradation_safety(default_rules)
        check_no_regression(default_rules)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 验证脚本执行异常: {exc}")
        traceback.print_exc()
        RESULTS.append(("EXCEPTION", False, str(exc)))

    _print_summary_and_exit()


def _print_summary_and_exit():
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print("-" * 70)
    print(f"总结: 共 {total} 项，通过 {passed}，失败 {failed}")
    print("-" * 70)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
