"""P0 阶段回归测试 —— 规则库真实性修复.

覆盖：
  P0-1 占位/静态 IOC 消除 + 动态情报引用
  P0-2 Windows 安全事件日志桥接（event_log_summary 规则类型）
  P0-3 死 exists 规则下线

对应文档：docs/rule-audit/p0/01-design.md（验收标准 AC-1 ~ AC-10）
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

RULES_DIR = BACKEND_DIR / "app" / "rules"

# 审计中确认的占位虚构指标字面量
PLACEHOLDER_PATTERNS = [
    "example.com", "example.net", "example.org",
    "attacker.net", "185.174.137.11",
]


def _load_json(name: str):
    with open(RULES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════
# P0-1 · 占位 IOC 消除与动态情报引用
# ══════════════════════════════════════════════════════════════

class TestP01PlaceholderIocRemoved:
    """AC-1：规则库中不存在占位虚构 IOC。"""

    def test_no_placeholder_in_matchable_values(self):
        """所有规则文件的可匹配 values 中不得出现占位指标。"""
        offenders = []

        def _walk(node, origin, path="$"):
            if isinstance(node, dict):
                for k, v in node.items():
                    # _meta 是文档性字段，不参与匹配，豁免
                    if k == "_meta":
                        continue
                    _walk(v, origin, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _walk(v, origin, f"{path}[{i}]")
            elif isinstance(node, str):
                low = node.lower()
                for pat in PLACEHOLDER_PATTERNS:
                    if pat in low:
                        offenders.append(f"{origin}:{path} -> {node}")

        for jf in sorted(RULES_DIR.glob("*.json")):
            data = json.loads(jf.read_text(encoding="utf-8"))
            _walk(data, jf.name)

        assert offenders == [], f"仍存在占位虚构 IOC: {offenders}"

    def test_c2_domain_rule_is_ioc_driven(self):
        """suspicious_c2_domain 改为动态情报驱动。"""
        rules = _load_json("default_rules.json")
        rule = next(r for r in rules if r["name"] == "suspicious_c2_domain")
        cond = rule["condition"]
        assert cond["values"] == [], "静态占位值应已清空"
        assert set(cond["ioc_types"]) == {"domain", "ip"}
        assert cond["_meta"]["requires_ioc"] is True
        assert rule["enabled"] is True, "规则应保持启用，由情报库驱动"

    def test_attack_chain_c2_step_is_ioc_driven(self):
        """AC-4 前置：攻击链 C2 步骤不再依赖占位值。"""
        chains = _load_json("default_attack_chain.json")
        chain = next(
            c for c in chains if c["name"] == "attack_chain_default_c2_persistence"
        )
        step2 = chain["condition"]["ordered_steps"][1]["match"]
        assert step2["values"] == []
        assert set(step2["ioc_types"]) == {"domain", "ip"}
        # remote_address 常带端口，必须用 contains 而非 exact
        assert step2["match_mode"] == "contains"


class TestP01ResolveIocTypes:
    """resolve_ioc_types 优先级与兼容性。"""

    def test_field_mapping_multi_type(self):
        from app.rules.rule_engine import resolve_ioc_types
        assert resolve_ioc_types("remote_address", {}) == ["ip", "domain"]

    def test_legacy_string_mapping_still_works(self):
        """存量 str 映射行为不变（向后兼容）。"""
        from app.rules.rule_engine import resolve_ioc_types
        assert resolve_ioc_types("url", {}) == ["url"]
        assert resolve_ioc_types("file_hash", {}) == ["hash"]

    def test_explicit_condition_overrides_field(self):
        from app.rules.rule_engine import resolve_ioc_types
        assert resolve_ioc_types("remote_address", {"ioc_types": ["domain"]}) == ["domain"]

    def test_unmapped_field_returns_empty(self):
        from app.rules.rule_engine import resolve_ioc_types
        assert resolve_ioc_types("some_random_field", {}) == []

    def test_dedup_and_order_preserved(self):
        from app.rules.rule_engine import resolve_ioc_types
        got = resolve_ioc_types("x", {"ioc_types": ["ip", "domain", "ip", "", None]})
        assert got == ["ip", "domain"]


class TestP01DynamicIocMatching:
    """AC-2 / AC-3：空情报库零命中；导入后即时命中。"""

    COND = {
        "field": "remote_address",
        "values": [],
        "ioc_types": ["domain", "ip"],
        "match_mode": "contains",
    }

    def test_empty_ioc_store_never_matches(self):
        """AC-2：情报库为空时任何输入都不命中（零误报）。"""
        from app.rules.rule_engine import RuleEngine
        for addr in ["malware-c2.example.com", "8.8.8.8", "any.host:443", ""]:
            assert RuleEngine._match_list(
                {"remote_address": addr}, self.COND, {"iocs_by_type": {}}
            ) is False

    def test_no_global_context_never_matches(self):
        from app.rules.rule_engine import RuleEngine
        assert RuleEngine._match_list(
            {"remote_address": "whatever"}, self.COND, None
        ) is False

    def test_domain_ioc_hits_after_import(self):
        """AC-3：导入 domain 情报后立即命中。"""
        from app.rules.rule_engine import RuleEngine
        ctx = {"iocs_by_type": {"domain": {"evil-c2.internal-test.lan"}}}
        assert RuleEngine._match_list(
            {"remote_address": "evil-c2.internal-test.lan:8443"}, self.COND, ctx
        ) is True

    def test_ip_ioc_hits_on_same_field(self):
        """同一 remote_address 字段上 ip 类情报也能命中（多类型合并的价值）。"""
        from app.rules.rule_engine import RuleEngine
        ctx = {"iocs_by_type": {"ip": {"203.0.113.55"}}}
        assert RuleEngine._match_list(
            {"remote_address": "203.0.113.55"}, self.COND, ctx
        ) is True

    def test_irrelevant_ioc_type_does_not_match(self):
        """hash 类情报不应影响 remote_address 规则。"""
        from app.rules.rule_engine import RuleEngine
        ctx = {"iocs_by_type": {"hash": {"deadbeef"}}}
        assert RuleEngine._match_list(
            {"remote_address": "deadbeef"}, self.COND, ctx
        ) is False

    def test_static_values_still_work(self):
        """向后兼容：仍带静态 values 的存量规则不受影响。"""
        from app.rules.rule_engine import RuleEngine
        cond = {"field": "remote_ip", "values": ["10.0.0.1"], "match_mode": "exact"}
        assert RuleEngine._match_list(
            {"remote_ip": "10.0.0.1"}, cond, {"iocs_by_type": {}}
        ) is True


# ══════════════════════════════════════════════════════════════
# P0-2 · Windows 安全事件日志桥接
# ══════════════════════════════════════════════════════════════

class TestP02TypeRegistration:
    """AC-5：类型注册链路完整。"""

    def test_rule_type_enum_contains_new_type(self):
        from app.schemas.analysis import RULE_TYPE_ENUM
        assert "event_log_summary" in RULE_TYPE_ENUM

    def test_matcher_registered(self):
        import app.rules.rule_engine  # noqa: F401  触发注册
        from app.rules.matchers.registry import MatcherRegistry
        assert MatcherRegistry.is_registered("event_log_summary")

    def test_confidence_default_present(self):
        from app.rules.rule_engine import _CONFIDENCE_DEFAULT
        assert _CONFIDENCE_DEFAULT["event_log_summary"] == 0.8


class TestP02ConditionValidation:
    """validate_condition 的 event_log_summary 分支。"""

    def _v(self, cond):
        from app.schemas.analysis import validate_condition
        validate_condition("event_log_summary", cond)

    def test_valid_single_event(self):
        self._v({"event_id": "4625", "operator": ">=", "count": 10})

    def test_valid_multi_event(self):
        self._v({"event_ids": ["4648", "4624"], "aggregate": "sum",
                 "operator": ">=", "count": 20})

    def test_defaults_are_accepted(self):
        """只给 event_id，operator/count/aggregate 走默认值。"""
        self._v({"event_id": "4625"})

    def test_missing_event_id_rejected(self):
        with pytest.raises(ValueError, match="event_id"):
            self._v({"operator": ">=", "count": 10})

    def test_empty_event_ids_rejected(self):
        with pytest.raises(ValueError, match="非空列表"):
            self._v({"event_ids": [], "count": 1})

    def test_bad_operator_rejected(self):
        with pytest.raises(ValueError, match="operator"):
            self._v({"event_id": "4625", "operator": "~=", "count": 1})

    def test_bad_aggregate_rejected(self):
        with pytest.raises(ValueError, match="aggregate"):
            self._v({"event_ids": ["4625"], "aggregate": "median"})

    def test_negative_count_rejected(self):
        with pytest.raises(ValueError, match="负数"):
            self._v({"event_id": "4625", "count": -1})

    def test_non_int_count_rejected(self):
        with pytest.raises(ValueError, match="整数"):
            self._v({"event_id": "4625", "count": "many"})


class TestP02Matcher:
    """AC-6：计数匹配语义。"""

    C_4625 = {"event_id": "4625", "operator": ">=", "count": 10}

    def _m(self, item, cond=None):
        from app.rules.rule_engine import RuleEngine
        return RuleEngine._match_event_log_summary(item, cond or self.C_4625)

    def test_above_threshold_matches(self):
        assert self._m({"event_ids_summary": {"4625": 37}}) is True

    def test_below_threshold_not_match(self):
        assert self._m({"event_ids_summary": {"4625": 3}}) is False

    def test_boundary_equal_matches_for_gte(self):
        assert self._m({"event_ids_summary": {"4625": 10}}) is True

    def test_int_key_normalized(self):
        assert self._m({"event_ids_summary": {4625: 37}}) is True

    def test_bare_summary_dict_supported(self):
        assert self._m({"4625": 37}) is True

    def test_empty_summary_not_match(self):
        assert self._m({"event_ids_summary": {}}) is False

    def test_missing_key_counts_as_zero(self):
        assert self._m({"event_ids_summary": {"4624": 999}}) is False

    def test_non_dict_input_not_match(self):
        assert self._m(None) is False
        assert self._m([]) is False

    def test_aggregate_sum(self):
        cond = {"event_ids": ["4648", "4624"], "aggregate": "sum",
                "operator": ">=", "count": 20}
        assert self._m({"event_ids_summary": {"4648": 8, "4624": 15}}, cond) is True
        assert self._m({"event_ids_summary": {"4648": 5, "4624": 5}}, cond) is False

    def test_aggregate_any(self):
        cond = {"event_ids": ["4648", "4624"], "aggregate": "any",
                "operator": ">=", "count": 20}
        # 8+15=23 但单个都不到 20 → any 应为 False
        assert self._m({"event_ids_summary": {"4648": 8, "4624": 15}}, cond) is False
        assert self._m({"event_ids_summary": {"4648": 25, "4624": 1}}, cond) is True

    def test_aggregate_max(self):
        cond = {"event_ids": ["4648", "4624"], "aggregate": "max",
                "operator": ">=", "count": 20}
        assert self._m({"event_ids_summary": {"4648": 8, "4624": 25}}, cond) is True

    def test_less_than_operator(self):
        cond = {"event_id": "4624", "operator": "<", "count": 5}
        assert self._m({"event_ids_summary": {"4624": 2}}, cond) is True
        assert self._m({"event_ids_summary": {"4624": 9}}, cond) is False

    def test_unknown_operator_returns_false(self):
        cond = {"event_id": "4625", "operator": "~=", "count": 1}
        assert self._m({"event_ids_summary": {"4625": 999}}, cond) is False

    def test_dispatch_via_registry(self):
        import app.rules.rule_engine  # noqa: F401
        from app.rules.matchers.registry import MatcherRegistry
        assert MatcherRegistry.dispatch(
            "event_log_summary", {"event_ids_summary": {"4625": 50}}, self.C_4625, None
        ) is True


class TestP02RulesFile:
    """event_log_rules.json 内容与阈值基线。"""

    # 来自 purge_snapshots 真实正常主机样本
    NORMAL_BASELINE = {"4672": 31, "4624": 33, "4648": 8, "4776": 2,
                       "4625": 1, "5024": 1, "5033": 1, "4902": 1, "4608": 1}

    def test_six_rules_defined(self):
        rules = _load_json("event_log_rules.json")
        assert len(rules) == 6
        assert all(r["rule_type"] == "event_log_summary" for r in rules)
        assert all(r["enabled"] for r in rules)

    def test_expected_event_ids_covered(self):
        rules = _load_json("event_log_rules.json")
        covered = {r["condition"]["event_id"] for r in rules}
        assert covered == {"4625", "4648", "4662", "4769", "4672", "4624"}

    def test_all_conditions_pass_validation(self):
        from app.schemas.analysis import validate_condition
        for r in _load_json("event_log_rules.json"):
            validate_condition("event_log_summary", r["condition"])

    def test_normal_baseline_produces_no_alert(self):
        """关键：真实正常主机样本不得触发任何规则（防上线即刷屏）。"""
        from app.services.security_event_rules import evaluate_summary
        rules = _load_json("event_log_rules.json")
        hits = evaluate_summary(self.NORMAL_BASELINE, rules=rules)
        assert hits == [], f"正常基线误报: {[h['name'] for h in hits]}"

    def test_attack_scenario_triggers_expected_rules(self):
        """爆破 + DCSync 场景应命中对应规则。"""
        from app.services.security_event_rules import evaluate_summary
        rules = _load_json("event_log_rules.json")
        attack = {"4625": 250, "4662": 3, "4624": 40}
        names = {h["name"] for h in evaluate_summary(attack, rules=rules)}
        assert "evt_4625_failed_logon_burst" in names
        assert "evt_4662_dcsync_suspect" in names
        assert "evt_4624_logon_volume_anomaly" not in names  # 40 < 100


class TestP02ExtractSummary:
    """载荷归一：兼容真实链路上的多种形态。"""

    def _e(self, payload):
        from app.services.security_event_rules import extract_event_summary
        return extract_event_summary(payload)

    def test_collector_object(self):
        assert self._e({"event_ids_summary": {"4625": 3}, "antivirus": []}) == {"4625": 3}

    def test_list_wrapped(self):
        assert self._e([{"event_ids_summary": {"4625": 3}}]) == {"4625": 3}

    def test_json_string(self):
        assert self._e('[{"event_ids_summary": {"4625": 3}}]') == {"4625": 3}

    def test_bare_counter_dict(self):
        assert self._e({"4625": 3}) == {"4625": 3}

    def test_multi_element_merged(self):
        got = self._e([{"event_ids_summary": {"4625": 3}},
                       {"event_ids_summary": {"4625": 4, "4624": 1}}])
        assert got == {"4625": 7, "4624": 1}

    def test_none_and_garbage(self):
        assert self._e(None) == {}
        assert self._e("not json") == {}
        assert self._e({"antivirus": [], "firewall_rules": []}) == {}

    def test_non_numeric_values_skipped(self):
        assert self._e({"event_ids_summary": {"4625": "abc", "4624": 2}}) == {"4624": 2}


class TestP02EndToEndAlert:
    """AC-7：端到端写告警 + 幂等聚合。"""

    @pytest.fixture()
    def temp_db(self):
        from app.config import settings
        original = settings.DB_PATH
        original_journal = getattr(settings, "DB_JOURNAL_MODE", "WAL")
        data_dir = BACKEND_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        path = str(data_dir / f"test_p0_{uuid.uuid4().hex[:8]}.db")
        settings.DB_PATH = path
        settings.DB_JOURNAL_MODE = "DELETE"
        from app.database import init_db
        init_db()
        # alerts.host_id 有外键约束，需先建 case + host（id 固定为 1 和 7）
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (id, name, case_number, status)"
                " VALUES (1, 'P0 测试案件', 'C-P0', 'open')"
            )
            for hid in (1, 7):
                conn.execute(
                    "INSERT INTO hosts (id, case_id, hostname) VALUES (?, 1, ?)",
                    [hid, f"host-{hid}"],
                )
        yield path
        settings.DB_PATH = original
        settings.DB_JOURNAL_MODE = original_journal
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    def _count_alerts(self):
        from app.database import get_connection
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

    def test_alert_created_from_payload(self, temp_db):
        from app.services.security_event_rules import evaluate_and_alert
        payload = {"event_ids_summary": {"4625": 120}, "antivirus": []}
        results = evaluate_and_alert(host_id=1, payload=payload)
        names = {r["rule_name"] for r in results}
        assert "evt_4625_failed_logon_burst" in names
        assert self._count_alerts() >= 1

    def test_repeat_call_is_idempotent(self, temp_db):
        """AC-7：5 分钟窗口内重复上报只聚合，不新增告警行。"""
        from app.services.security_event_rules import evaluate_and_alert
        payload = {"event_ids_summary": {"4625": 120}}
        evaluate_and_alert(host_id=1, payload=payload)
        first = self._count_alerts()
        second_results = evaluate_and_alert(host_id=1, payload=payload)
        assert self._count_alerts() == first, "重复上报不应新增告警行"
        assert all(r["is_new"] is False for r in second_results)

    def test_normal_payload_creates_no_alert(self, temp_db):
        from app.services.security_event_rules import evaluate_and_alert
        payload = {"event_ids_summary": {"4672": 31, "4624": 33, "4648": 8}}
        assert evaluate_and_alert(host_id=1, payload=payload) == []
        assert self._count_alerts() == 0

    def test_empty_payload_is_safe(self, temp_db):
        from app.services.security_event_rules import evaluate_and_alert
        assert evaluate_and_alert(host_id=1, payload=None) == []
        assert evaluate_and_alert(host_id=1, payload={}) == []

    def test_unknown_host_reports_no_false_success(self, temp_db):
        """告警因外键失败未落库时，不得返回"看起来成功"的假摘要。"""
        from app.services.security_event_rules import evaluate_and_alert
        results = evaluate_and_alert(host_id=99999,
                                     payload={"event_ids_summary": {"4625": 120}})
        assert results == []
        assert self._count_alerts() == 0

    def test_alert_detail_contains_evidence(self, temp_db):
        from app.services.security_event_rules import evaluate_and_alert
        from app.database import get_connection
        evaluate_and_alert(host_id=7, payload={"event_ids_summary": {"4662": 5}})
        with get_connection() as conn:
            row = conn.execute(
                "SELECT title, detail, severity FROM alerts WHERE host_id=7"
            ).fetchone()
        assert row is not None
        assert "4662" in row[0]
        detail = json.loads(row[1])
        assert detail["observed_counts"]["4662"] == 5
        assert detail["mitre_attack"] == "T1003/006"
        assert row[2] == "critical"


# ══════════════════════════════════════════════════════════════
# P0-3 · 死 exists 规则下线
# ══════════════════════════════════════════════════════════════

class TestP03DeadRulesDisabled:
    """AC-8：无采集器产出字段的 exists 规则必须显式下线。"""

    DEAD_RULES = {
        "suspicious_service_reg_exists": "service_image_path",
        "suspicious_scheduled_task_xml_exists": "scheduled_task_xml",
    }

    def test_dead_rules_disabled_with_reason(self):
        rules = {r["name"]: r for r in _load_json("default_rules.json")}
        for name, field in self.DEAD_RULES.items():
            rule = rules[name]
            assert rule["enabled"] is False, f"{name} 应为 enabled=false"
            meta = rule["condition"]["_meta"]
            assert meta["disabled_reason"] == "no_producer_field"
            assert meta["disabled_at"] == "P0-3"
            assert "depends_on" in meta
            assert rule["condition"]["field"] == field

    def test_label_marks_offline_state(self):
        rules = {r["name"]: r for r in _load_json("default_rules.json")}
        for name in self.DEAD_RULES:
            assert "已下线" in rules[name]["label"]

    def test_rules_not_deleted(self):
        """保留条目以便采集器补齐后复活。"""
        names = {r["name"] for r in _load_json("default_rules.json")}
        assert set(self.DEAD_RULES).issubset(names)


# ══════════════════════════════════════════════════════════════
# 全库一致性
# ══════════════════════════════════════════════════════════════

class TestP0LoaderIntegrity:
    """AC-9：全部规则文件通过 loader 校验，无静默丢弃。"""

    def test_all_rules_load_without_drop(self, caplog):
        import logging
        from app.rules.loader import load_default_rules
        with caplog.at_level(logging.WARNING, logger="app.rules.loader"):
            rules = load_default_rules()
        # revoked_ca.json 是数据文件（非规则数组），是唯一预期的跳过项
        unexpected = [
            r.message % r.args if r.args else r.message
            for r in caplog.records
            if "revoked_ca.json" not in str(r.getMessage())
        ]
        assert unexpected == [], f"存在非预期的规则丢弃: {unexpected}"
        assert len(rules) == 147, f"规则总数应为 147，实际 {len(rules)}"

    def test_rule_type_distribution(self):
        """规则类型分布快照 —— 作为"规则库被意外改动"的探测器。

        P1-1-C / P1-4 将 9 条规则从 regex 改造为更精确的类型（8 条 → composite，
        1 条 → exists），以消除宽泛正则造成的结构性误报：

        ============================  ==========  ==========
        变更                          改造前       改造后
        ============================  ==========  ==========
        regex                         62          53
        composite                     13          21
        exists                        2           3
        ============================  ==========  ==========

        总数保持 147 不变（只改类型不增删规则），由 test_loader_no_silent_drop 守护。
        """
        from collections import Counter
        from app.rules.loader import load_default_rules
        rules = load_default_rules()
        dist = Counter(r["rule_type"] for r in rules)
        assert dist["event_log_summary"] == 6
        assert dist["regex"] == 53
        assert dist["behavior"] == 40
        assert dist["composite"] == 21
        assert dist["list"] == 11
        assert dist["attack_chain"] == 10
        assert dist["exists"] == 3
        assert dist["threshold"] == 3
        # 分布之和必须等于总数：防止出现未被本用例覆盖的新类型
        assert sum(dist.values()) == len(rules) == 147

    def test_no_duplicate_rule_names(self):
        from app.rules.loader import load_default_rules
        names = [r["name"] for r in load_default_rules()]
        dupes = {n for n in names if names.count(n) > 1}
        assert dupes == set(), f"存在重名规则: {dupes}"


class TestP0IocDependencyScan:
    """情报依赖巡检模块。"""

    def test_scan_reports_c2_rule_as_dependent(self):
        from app.rules.ioc_dependency import scan_ioc_dependent_rules
        rules = _load_json("default_rules.json")
        report = scan_ioc_dependent_rules(rules=rules)
        names = {d["name"] for d in report["dependent_rules"]}
        assert "suspicious_c2_domain" in names

    def test_unsatisfied_when_ioc_store_empty(self):
        """情报库为空 + 无静态值 → 标记为未满足，可被巡检发现。"""
        from app.rules.ioc_dependency import scan_ioc_dependent_rules
        fake = [{
            "name": "t_rule", "rule_type": "list", "severity": "high",
            "condition": {"field": "remote_address", "values": [],
                          "ioc_types": ["domain"], "_meta": {"requires_ioc": True}},
        }]
        # 显式传入空情报库，避免受本地开发库中已有 IOC 影响（结果确定）
        report = scan_ioc_dependent_rules(rules=fake, inventory={})
        assert report["unsatisfied_count"] == 1
        assert "t_rule" in report["unsatisfied_rules"]

    def test_satisfied_once_ioc_imported(self):
        """情报导入后同一规则转为已满足。"""
        from app.rules.ioc_dependency import scan_ioc_dependent_rules
        fake = [{
            "name": "t_rule", "rule_type": "list", "severity": "high",
            "condition": {"field": "remote_address", "values": [],
                          "ioc_types": ["domain"]},
        }]
        report = scan_ioc_dependent_rules(rules=fake, inventory={"domain": 5})
        assert report["unsatisfied_count"] == 0
        assert report["dependent_rules"][0]["available"] == {"domain": 5}

    def test_attack_chain_steps_are_scanned(self):
        from app.rules.ioc_dependency import scan_ioc_dependent_rules
        chains = _load_json("default_attack_chain.json")
        report = scan_ioc_dependent_rules(rules=chains)
        paths = [d["path"] for d in report["dependent_rules"]]
        assert any("ordered_steps" in p for p in paths)
