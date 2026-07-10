#!/usr/bin/env python3
"""独立 QA 功能点验证脚本（软件-qa-engineer-5）.

使用 FastAPI TestClient 实跑规则管理模块 API，逐项验证 PRD/设计验收点。
不依赖工程师自带测试，独立证明功能可用。

运行: cd backend && venv/Scripts/python.exe qa_functional_verify.py
"""

import json
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 准备临时隔离数据库 ─────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="qa_func_"))
TEST_DB = str(TMP / "qa_verify.db")

from app.config import settings  # noqa: E402

settings.DB_PATH = TEST_DB
settings.DATA_DIR = TMP
settings.UPLOAD_DIR = TMP / "uploads"
settings.AGENT_DIR = TMP / "agents"

import sqlite3  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.rules import loader  # noqa: E402
from app.rules.rule_engine import RuleEngine, BEHAVIOR_PATTERNS  # noqa: E402

# 显式初始化隔离数据库（TestClient startup 事件不一定触发）
init_db()

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"[PASS] {name} {detail}")
    else:
        FAIL.append(name)
        print(f"[FAIL] {name} {detail}")


def conn():
    c = sqlite3.connect(TEST_DB)
    c.row_factory = sqlite3.Row
    return c


client = TestClient(app)

# ── 登录获取 token ────────────────────────────────────────────────
resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
token = resp.json()["data"]["token"]
H = {"Authorization": f"Bearer {token}"}

print("=" * 70)
print("  软件-qa-engineer-5 独立功能验证")
print("=" * 70)

# ── 1. 规则导入：导入后规则数 == JSON 条数 (102) ──────────────────
json_rules = loader.load_default_rules()
check("default_rules.json 解析条数==102", len(json_rules) == 102, f"(实际={len(json_rules)})")

c = conn()
default_count = c.execute("SELECT COUNT(*) FROM rules WHERE source='default'").fetchone()[0]
check("DB 中 source='default' 规则数==102", default_count == 102, f"(实际={default_count})")

# ── 2. 100% 有 MITRE ─────────────────────────────────────────────
rows = c.execute("SELECT name, mitre_attack, condition, severity FROM rules WHERE source='default'").fetchall()
no_mitre = []
for r in rows:
    cond = r["condition"]
    if isinstance(cond, str):
        cond = json.loads(cond)
    meta = cond.get("_meta", {}) if isinstance(cond, dict) else {}
    mitre = r["mitre_attack"] or (meta.get("mitre_attack") if isinstance(meta, dict) else None) \
        or (cond.get("mitre_attack") if isinstance(cond, dict) else None)
    if not mitre:
        no_mitre.append(r["name"])
check("所有默认规则均有 MITRE 映射", len(no_mitre) == 0, f"(缺失={no_mitre[:5]})")

# ── 3. severity 取值均在枚举内 ──────────────────────────────────
valid_sev = {"critical", "high", "medium", "low"}
bad_sev = [r["name"] for r in rows if r["severity"] not in valid_sev]
check("severity 均在枚举内", len(bad_sev) == 0, f"(非法={bad_sev[:5]})")

# ── 11. 本地化：API 返回的规则含中文 label ──────────────────────
rlist = client.get("/api/rules", headers=H).json()["data"]
label_missing = [r["name"] for r in rlist if not r.get("label")]
check("GET /api/rules 返回规则均含 label(中文)", len(label_missing) == 0,
      f"(缺失={label_missing[:5]})")
sample_label = next((r["label"] for r in rlist if r.get("label")), "")
check("label 为非空中文字符串", bool(sample_label) and any(ord(ch) > 127 for ch in sample_label),
      f"(样例={sample_label!r})")

# ── 4. behavior pattern 校验：非法 pattern → 422 ─────────────────
bad_resp = client.post("/api/rules", headers=H, json={
    "name": "qa_bad_behavior",
    "category": "behavior",
    "rule_type": "behavior",
    "condition": {"pattern": "totally_made_up_pattern"},
    "severity": "medium",
})
check("创建 behavior 规则非法 pattern → 422", bad_resp.status_code == 422,
      f"(code={bad_resp.status_code})")

good_resp = client.post("/api/rules", headers=H, json={
    "name": "qa_good_behavior",
    "category": "behavior",
    "rule_type": "behavior",
    "condition": {"pattern": "orphan_process"},
    "severity": "medium",
    "label": "QA合法行为规则",
})
check("创建 behavior 规则合法 pattern → 200", good_resp.status_code == 200,
      f"(code={good_resp.status_code})")
good_user_id = good_resp.json()["data"]["id"] if good_resp.status_code == 201 else None

# ── 10. condition 结构校验：缺字段 / composite 错 → 422 ──────────
regex_no_field = client.post("/api/rules", headers=H, json={
    "name": "qa_bad_regex",
    "category": "process",
    "rule_type": "regex",
    "condition": {"pattern": "foo.*bar"},  # 缺 field
    "severity": "medium",
})
check("regex 缺 field → 422", regex_no_field.status_code == 422,
      f"(code={regex_no_field.status_code})")

comp_no_sub = client.post("/api/rules", headers=H, json={
    "name": "qa_bad_composite",
    "category": "process",
    "rule_type": "composite",
    "condition": {"logic": "AND"},  # 缺 sub_rules
    "severity": "medium",
})
check("composite 缺 sub_rules → 422", comp_no_sub.status_code == 422,
      f"(code={comp_no_sub.status_code})")

# ── 5. DELETE 默认规则 → 403；用户自建 → 成功 ───────────────────
# 找一个默认规则
default_rule = c.execute("SELECT id FROM rules WHERE source='default' LIMIT 1").fetchone()
del_default = client.delete(f"/api/rules/{default_rule['id']}", headers=H)
check("DELETE 默认规则(source=default) → 403", del_default.status_code == 403,
      f"(code={del_default.status_code})")

user_rule = client.post("/api/rules", headers=H, json={
    "name": "qa_user_deletable",
    "category": "process",
    "rule_type": "list",
    "condition": {"field": "remote_address", "values": ["8.8.8.8"]},
    "severity": "low",
    "source": "user",
}).json()["data"]
del_user = client.delete(f"/api/rules/{user_rule['id']}", headers=H)
check("DELETE 用户规则(source=user) → 200", del_user.status_code == 200,
      f"(code={del_user.status_code})")
still = c.execute("SELECT COUNT(*) FROM rules WHERE id=?", (user_rule["id"],)).fetchone()[0]
check("用户规则删除后数据库中不存在", still == 0, f"(残留={still})")

# ── 6. IOC：POST/GET/DELETE /api/iocs 与 POST /api/iocs/import ──
ioc_create = client.post("/api/iocs", headers=H, json={
    "ioc_type": "ip", "ioc_value": "1.2.3.4", "description": "qa ioc"
})
check("POST /api/iocs 创建 → 200", ioc_create.status_code == 200,
      f"(code={ioc_create.status_code})")
ioc_id = ioc_create.json()["data"]["id"]
ioc_get = client.get("/api/iocs", headers=H)
check("GET /api/iocs 列表 → 200", ioc_get.status_code == 200 and len(ioc_get.json()["data"]) >= 1,
      f"(code={ioc_get.status_code})")
ioc_import = client.post("/api/iocs/import", headers=H, json={
    "items": [
        {"ioc_type": "domain", "ioc_value": "evil1.test"},
        {"ioc_type": "domain", "ioc_value": "evil2.test"},
    ]
})
check("POST /api/iocs/import → 200", ioc_import.status_code == 200,
      f"(code={ioc_import.status_code})")
imported = ioc_import.json()["data"]["inserted"]
check("POST /api/iocs/import 实际插入 2 条", imported == 2, f"(inserted={imported})")
ioc_del = client.delete(f"/api/iocs/{ioc_id}", headers=H)
check("DELETE /api/iocs/{id} → 200", ioc_del.status_code == 200,
      f"(code={ioc_del.status_code})")

# ── 7. GET /rules?q= 模糊搜索 name/label/description ─────────────
# 用一条已知默认规则的关键字搜索
probe = rlist[0]
q_term = (probe.get("label") or probe.get("name") or "")[:3]
qs = client.get("/api/rules", headers=H, params={"q": q_term})
check(f"GET /rules?q={q_term!r} 模糊搜命中", qs.status_code == 200 and len(qs.json()["data"]) >= 1,
      f"(code={qs.status_code}, 命中={len(qs.json()['data']) if qs.status_code==200 else 0})")
# 搜索不存在的关键字应返回空集(不为报错)
qs_empty = client.get("/api/rules", headers=H, params={"q": "zzz_no_such_rule_xyz"})
check("GET /rules?q=不存在关键字 → 空集200", qs_empty.status_code == 200 and len(qs_empty.json()["data"]) == 0,
      f"(code={qs_empty.status_code})")

# ── 8. PUT /rules/bulk-enable 批量切换 ──────────────────────────
# 取两条默认规则做禁用再启用
two = c.execute("SELECT id FROM rules WHERE source='default' LIMIT 2").fetchall()
ids = [r["id"] for r in two]
be = client.put("/api/rules/bulk-enable", headers=H, json={"ids": ids, "enabled": False})
check("PUT /rules/bulk-enable 禁用 → 200", be.status_code == 200, f"(code={be.status_code})")
disabled = c.execute("SELECT COUNT(*) FROM rules WHERE id IN (?,?) AND enabled=0", ids).fetchone()[0]
check("批量禁用生效", disabled == 2, f"(生效={disabled})")
be2 = client.put("/api/rules/bulk-enable", headers=H, json={"ids": ids, "enabled": True})
enabled = c.execute("SELECT COUNT(*) FROM rules WHERE id IN (?,?) AND enabled=1", ids).fetchone()[0]
check("批量启用生效", enabled == 2, f"(生效={enabled})")

# ── 9. POST /rules/reset：仅 upsert default，保留 user 规则 ──────
# 先插入一条 user 规则
user_keep = client.post("/api/rules", headers=H, json={
    "name": "qa_keep_user",
    "category": "process",
    "rule_type": "list",
    "condition": {"field": "remote_address", "values": ["9.9.9.9"]},
    "severity": "low",
    "source": "user",
}).json()["data"]
before = c.execute("SELECT COUNT(*) FROM rules WHERE source='default'").fetchone()[0]
reset = client.post("/api/rules/reset", headers=H)
check("POST /rules/reset → 200", reset.status_code == 200, f"(code={reset.status_code})")
after = c.execute("SELECT COUNT(*) FROM rules WHERE source='default'").fetchone()[0]
check("reset 后 default 规则数不变(102)", after == 102, f"(before={before}, after={after})")
kept = c.execute("SELECT COUNT(*) FROM rules WHERE name='qa_keep_user' AND source='user'").fetchone()[0]
check("reset 后用户规则被保留", kept == 1, f"(保留={kept})")

# ── 12. 审计：update/delete 后 rule_audit_log 有记录 ────────────
audit_before = c.execute("SELECT COUNT(*) FROM rule_audit_log").fetchone()[0]
upd = client.put(f"/api/rules/{user_keep['id']}", headers=H, json={"severity": "high"})
check("PUT 更新用户规则 → 200", upd.status_code == 200, f"(code={upd.status_code})")
client.delete(f"/api/rules/{user_keep['id']}", headers=H)
audit_after = c.execute("SELECT COUNT(*) FROM rule_audit_log").fetchone()[0]
check("update+delete 后 rule_audit_log 写入记录", audit_after > audit_before,
      f"(before={audit_before}, after={audit_after})")

# ── 引擎匹配逻辑未被改动：list 规则使用自身 condition.values ────
list_rule = {"rule_type": "list", "condition": {"field": "remote_address", "values": ["1.2.3.4"]}}
hit = RuleEngine.match_rule({"remote_address": "1.2.3.4"}, list_rule)
miss = RuleEngine.match_rule({"remote_address": "5.6.7.8"}, list_rule)
check("RuleEngine list 规则命中自身 values", hit is True and miss is False,
      f"(hit={hit}, miss={miss})")
# behavior 白名单校验函数
check("validate_behavior_pattern 白名单 20 种", len(BEHAVIOR_PATTERNS) == 20,
      f"(size={len(BEHAVIOR_PATTERNS)})")
check("非法 pattern 被白名单拒绝", RuleEngine is not None and
      __import__("app.rules.rule_engine", fromlist=["validate_behavior_pattern"]).validate_behavior_pattern("xxx") is False)

# ── 汇总 ─────────────────────────────────────────────────────────
print("=" * 70)
print(f"  通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    print("  失败项:")
    for f in FAIL:
        print(f"   - {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
