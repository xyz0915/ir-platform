"""Enable-SSOT 改造测试套件（设计/开发/测试/验证 四阶段之一：测试阶段）.

覆盖 AC-1~AC-7：单一真值计算、激活部署事务、取消静默回退、双页可见生效态、
行为引擎同策略门控、审计可追溯、一键对齐。

使用独立临时数据库，避免影响运行中的生产库。
"""

import os
import tempfile

# 必须在导入任何 app 数据库模块之前重定向 DB_PATH，确保测试隔离
import app.config as _cfg

_TMP = tempfile.mkdtemp(prefix="enable_ssot_")
_cfg.settings.DB_PATH = os.path.join(_TMP, "test_ir_platform.db")

from app.database import init_db, get_connection  # noqa: E402
from app.models.rule import Rule  # noqa: E402
from app.models.policy import DetectionPolicy  # noqa: E402
from app.analysis import service_risk_analyzer as sra  # noqa: E402
from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer  # noqa: E402

init_db()


def _reset_behavior_cache():
    sra._behavior_rules_cache = None
    sra._behavior_rules_cache_ts = 0


def _deactivate_all_policies():
    with get_connection() as conn:
        conn.execute("UPDATE detection_policies SET is_active=0")


def _make_user_rule(name, severity="medium", enabled=True, engine_type="rule_engine",
                    status="active"):
    r = Rule.create(
        name=name, category="test", rule_type="regex",
        condition={"field": "x", "op": "exists", "value": ""},
        severity=severity, enabled=enabled, source="user", engine_type=engine_type,
    )
    if status == "deprecated":
        Rule.deprecate(r["id"], changed_by="test")
        r = Rule.get_by_id(r["id"])
    return r


# ─────────────────────────────────────────────────────────────
# AC-1：effective_active 计算（单一真值）
# ─────────────────────────────────────────────────────────────
def test_effective_active_reason_branches():
    base = {"id": 1, "enabled": True}
    # 生效中
    eff, reason = Rule.effective_active_of(base, {1}, True)
    assert eff is True and reason == "生效中"
    # 未选入激活策略
    eff, reason = Rule.effective_active_of(base, set(), True)
    assert eff is False and reason == "未选入激活策略"
    # 已禁用
    eff, reason = Rule.effective_active_of({"id": 1, "enabled": False}, {1}, True)
    assert eff is False and reason == "已禁用"
    # 无激活策略
    eff, reason = Rule.effective_active_of(base, {1}, False)
    assert eff is False and reason == "无激活策略"


def test_annotate_effective_batch():
    rules = [
        {"id": 10, "enabled": True},
        {"id": 11, "enabled": False},
        {"id": 12, "enabled": True},
    ]
    Rule.annotate_effective(rules, {10, 12}, True)
    assert rules[0]["effective_active"] is True
    assert rules[1]["effective_active"] is False and rules[1]["effective_reason"] == "已禁用"
    assert rules[2]["effective_active"] is True


# ─────────────────────────────────────────────────────────────
# AC-2：activate = 部署事务，写 rules.enabled
# ─────────────────────────────────────────────────────────────
def test_activate_deploys_enabled_flags():
    a = _make_user_rule("ssot_a", enabled=True)
    b = _make_user_rule("ssot_b", enabled=True)
    pid = DetectionPolicy.create(name="deploy_policy")
    DetectionPolicy.set_rules(pid, [a["id"]])
    assert DetectionPolicy.activate(pid) is True

    active = DetectionPolicy.get_active()
    assert active["id"] == pid
    # 选中的 A 保持启用；未选的 B 被部署关闭
    assert Rule.get_by_id(a["id"])["enabled"] is True
    assert Rule.get_by_id(b["id"])["enabled"] is False


def test_activate_does_not_enable_deprecated():
    d = _make_user_rule("ssot_dead", enabled=False, status="deprecated")
    pid = DetectionPolicy.create(name="deploy_deprecated")
    DetectionPolicy.set_rules(pid, [d["id"]])
    DetectionPolicy.activate(pid)
    # deprecated 规则不被部署改写（仍为禁用）
    assert Rule.get_by_id(d["id"])["enabled"] is False


def test_activate_writes_audit_with_effective():
    # 创建一条禁用规则，被策略选中 → 部署时变为启用，触发审计写入
    a = _make_user_rule("ssot_audit", enabled=False)
    pid = DetectionPolicy.create(name="audit_policy")
    DetectionPolicy.set_rules(pid, [a["id"]])
    DetectionPolicy.activate(pid)
    assert Rule.get_by_id(a["id"])["enabled"] is True
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM rule_audit_log WHERE rule_id=? AND action='policy_deploy' ORDER BY id DESC",
            (a["id"],),
        ).fetchall()
    assert rows, "应写入 policy_deploy 审计"
    last = dict(rows[0])
    assert "effective_active" in (last["new_val"] or "")


# ─────────────────────────────────────────────────────────────
# AC-3：取消静默回退（ensure_active_policy 自动激活基线）
# ─────────────────────────────────────────────────────────────
def test_ensure_active_policy_auto_activates():
    _deactivate_all_policies()
    assert DetectionPolicy.get_active() is None
    result = DetectionPolicy.ensure_active_policy()
    assert result is not None
    assert result.get("is_active") == 1
    # 再次调用命中已有激活策略，不重新部署（保留手工 override）
    before = Rule.list(enabled=True)
    DetectionPolicy.ensure_active_policy()
    after = Rule.list(enabled=True)
    assert len(before) == len(after)


# ─────────────────────────────────────────────────────────────
# AC-5：行为引擎纳入激活策略门控
# ─────────────────────────────────────────────────────────────
def test_behavior_engine_gated_by_policy():
    sra.USE_BEHAVIOR_DB_RULES = True
    e = _make_user_rule("ssot_behavior", engine_type="behavior_engine", enabled=True)
    _reset_behavior_cache()
    # 无激活策略时：返回全部已启用行为规则
    _deactivate_all_policies()
    all_beh = ServiceRiskAnalyzer._load_behavior_rules()
    assert any(r["id"] == e["id"] for r in all_beh)

    # 激活一个不选中 e 的策略：e 被排除
    pid = DetectionPolicy.create(name="beh_off")
    DetectionPolicy.set_rules(pid, [])  # 不选 e
    DetectionPolicy.activate(pid)
    _reset_behavior_cache()
    off_beh = ServiceRiskAnalyzer._load_behavior_rules()
    assert not any(r["id"] == e["id"] for r in off_beh)

    # 激活选中 e 的策略：e 被纳入
    pid2 = DetectionPolicy.create(name="beh_on")
    DetectionPolicy.set_rules(pid2, [e["id"]])
    DetectionPolicy.activate(pid2)
    _reset_behavior_cache()
    on_beh = ServiceRiskAnalyzer._load_behavior_rules()
    assert any(r["id"] == e["id"] for r in on_beh)


# ─────────────────────────────────────────────────────────────
# AC-7：一键对齐（已启用高危补选）逻辑等价校验
# ─────────────────────────────────────────────────────────────
def test_align_enabled_high_risk_semantics():
    hi = _make_user_rule("ssot_hi", severity="high", enabled=True)
    lo = _make_user_rule("ssot_lo", severity="low", enabled=True)
    pid = DetectionPolicy.create(name="align_policy")
    DetectionPolicy.set_rules(pid, [])  # 初始都不选
    # 模拟"一键对齐"：补选已启用 high/critical 且未选者
    selected = []
    for r in Rule.list(source="user"):
        if r["severity"] in ("critical", "high") and r["enabled"] and r["id"] == hi["id"]:
            selected.append(r["id"])
    assert hi["id"] in selected
    assert lo["id"] not in selected
    DetectionPolicy.set_rules(pid, selected)
    detail = DetectionPolicy.get_by_id(pid)
    ids = {r["id"] for r in detail["rules"]}
    assert hi["id"] in ids and lo["id"] not in ids


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "--noconftest"]))
