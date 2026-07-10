"""ExplainabilityService 三个缺失方法的单元测试.

测试范围:
    - normalize_section: None / 非 dict / 正常 dict / 嵌套字段不污染原对象
    - ensure_structured_timeline: AI 给出 events / AI 未给但 tiered_data 有 timeline_* / 空输入
    - build_evidence_trace: 必含 evidence_trace 与 recommended_questions 两键；
      knowledge_items 为空、parsed 为空均不崩
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


class TestNormalizeSection(unittest.TestCase):
    """normalize_section 防御性测试."""

    def test_none_returns_empty_dict(self):
        from app.services.explainability_service import ExplainabilityService

        self.assertEqual(ExplainabilityService.normalize_section(None), {})

    def test_non_dict_returns_empty_dict(self):
        from app.services.explainability_service import ExplainabilityService

        self.assertEqual(ExplainabilityService.normalize_section("not a dict"), {})
        self.assertEqual(ExplainabilityService.normalize_section(123), {})
        self.assertEqual(ExplainabilityService.normalize_section([]), {})

    def test_normal_dict_returns_copy(self):
        from app.services.explainability_service import ExplainabilityService

        src = {"risk_level": "high", "risk_score": 80}
        out = ExplainabilityService.normalize_section(src)
        self.assertEqual(out, src)
        self.assertIsNot(out, src)  # 必须是新对象

    def test_nested_mutation_does_not_pollute_original(self):
        from app.services.explainability_service import ExplainabilityService

        original = {"risk_assessment": {"nested": {"a": 1}}, "list": [1, 2, 3]}
        out = ExplainabilityService.normalize_section(original)
        # 在新对象上做顶层与嵌套修改
        out["risk_level"] = "高危"
        out["risk_assessment"]["nested"]["a"] = 999
        out["list"].append(4)
        # 原始对象必须完全不受影响
        self.assertNotIn("risk_level", original)
        self.assertEqual(original["risk_assessment"]["nested"]["a"], 1)
        self.assertEqual(original["list"], [1, 2, 3])


class TestEnsureStructuredTimeline(unittest.TestCase):
    """ensure_structured_timeline 测试."""

    def test_ai_provided_key_events_preserved(self):
        from app.services.explainability_service import ExplainabilityService

        section = {
            "attack_chain": "入口→执行→外联",
            "confidence_level": "high",
            "key_events": [
                {"timestamp": "10:00", "event": "进程创建", "phase": "high", "significance": "可疑"},
            ],
        }
        out = ExplainabilityService.ensure_structured_timeline(section, {})
        # 保留原有字段
        self.assertEqual(out["attack_chain"], "入口→执行→外联")
        self.assertEqual(out["confidence_level"], "high")
        # key_events 透传并归一化
        self.assertEqual(len(out["key_events"]), 1)
        self.assertEqual(out["key_events"][0]["event"], "进程创建")

    def test_ai_provided_events_renamed_to_key_events(self):
        from app.services.explainability_service import ExplainabilityService

        section = {
            "events": [
                {"time": "11:00", "type": "外联", "desc": "连接到 C2", "severity": "high"},
            ],
        }
        out = ExplainabilityService.ensure_structured_timeline(section, {})
        self.assertEqual(len(out["key_events"]), 1)
        self.assertEqual(out["key_events"][0]["event"], "连接到 C2")
        self.assertEqual(out["key_events"][0]["phase"], "外联")
        # 旧字段 events 已被收敛为 key_events
        self.assertNotIn("events", out)

    def test_build_from_tiered_data_when_ai_missing(self):
        from app.services.explainability_service import ExplainabilityService

        tiered = {
            "timeline_high": [
                {"time": "09:00", "type": "进程注入", "desc": "注入恶意 DLL", "severity": "high"},
            ],
            "timeline_medium": [
                {"time": "09:05", "type": "外联", "desc": "DNS 查询", "severity": "medium"},
            ],
            "timeline_low": [],
        }
        out = ExplainabilityService.ensure_structured_timeline({}, tiered)
        self.assertEqual(len(out["key_events"]), 2)
        # 字段已映射到前端结构
        self.assertEqual(out["key_events"][0]["timestamp"], "09:00")
        self.assertEqual(out["key_events"][0]["event"], "注入恶意 DLL")
        self.assertEqual(out["key_events"][0]["phase"], "进程注入")

    def test_empty_input_returns_safe_dict(self):
        from app.services.explainability_service import ExplainabilityService

        out = ExplainabilityService.ensure_structured_timeline(None, None)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["key_events"], [])

    def test_non_dict_inputs_do_not_crash(self):
        from app.services.explainability_service import ExplainabilityService

        out = ExplainabilityService.ensure_structured_timeline("bad", 123)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["key_events"], [])


class TestBuildEvidenceTrace(unittest.TestCase):
    """build_evidence_trace 测试."""

    def test_returns_both_required_keys(self):
        from app.services.explainability_service import ExplainabilityService

        out = ExplainabilityService.build_evidence_trace({}, [], {})
        self.assertIn("evidence_trace", out)
        self.assertIn("recommended_questions", out)

    def test_evidence_trace_has_frontend_fields(self):
        from app.services.explainability_service import ExplainabilityService

        out = ExplainabilityService.build_evidence_trace({}, [], {})
        ev = out["evidence_trace"]
        self.assertIsInstance(ev, dict)
        self.assertIn("knowledge_evidence", ev)
        self.assertIn("local_evidence", ev)
        self.assertIn("explainability_labels", ev)

    def test_empty_knowledge_items_does_not_crash(self):
        from app.services.explainability_service import ExplainabilityService

        parsed = {
            "risk_assessment": {"risk_level": "high"},
            "threat_analysis": {"attack_vector": "钓鱼邮件"},
            "timeline_analysis": {"attack_chain": "点击→下载→执行"},
        }
        out = ExplainabilityService.build_evidence_trace(parsed, [], {})
        self.assertEqual(out["evidence_trace"]["knowledge_evidence"], [])
        # 空知识库时仍有兜底标签
        self.assertTrue(len(out["evidence_trace"]["explainability_labels"]) >= 1)
        # 本地证据由 parsed 提炼
        self.assertTrue(len(out["evidence_trace"]["local_evidence"]) >= 1)
        # 推荐追问基于 parsed 生成，且必须为对象列表（前端 DeepDiveQuestionPanel 契约）
        self.assertIsInstance(out["recommended_questions"], list)
        self.assertTrue(len(out["recommended_questions"]) >= 1)
        for q in out["recommended_questions"]:
            self.assertIsInstance(q, dict)
            self.assertTrue(q.get("title"))
            self.assertTrue(q.get("question"))
            self.assertTrue(q.get("focus_area"))

    def test_knowledge_items_populated(self):
        from app.services.explainability_service import ExplainabilityService

        knowledge = [
            {
                "source": "vector",
                "title": "C2 通信特征",
                "rule_name": "c2_sig",
                "severity": "high",
                "summary": "检测到与已知 C2 框架匹配的流量",
                "evidence_text": "匹配 C2 框架特征",
                "match_reason": "语义相似检索命中",
            },
        ]
        out = ExplainabilityService.build_evidence_trace({}, knowledge, {})
        self.assertEqual(len(out["evidence_trace"]["knowledge_evidence"]), 1)
        # 来源标签应包含 vector
        labels = out["evidence_trace"]["explainability_labels"]
        self.assertTrue(any("vector" in label for label in labels))

    def test_empty_parsed_does_not_crash(self):
        from app.services.explainability_service import ExplainabilityService

        out = ExplainabilityService.build_evidence_trace(None, None, None)
        self.assertIn("evidence_trace", out)
        self.assertIn("recommended_questions", out)
        self.assertEqual(out["recommended_questions"], [])

    def test_build_suggested_questions_returns_objects(self):
        from app.services.explainability_service import ExplainabilityService

        parsed = {
            "risk_assessment": {"risk_level": "高危"},
            "threat_analysis": {"attack_vector": "钓鱼邮件"},
            "timeline_analysis": {"attack_chain": "点击→下载→执行"},
        }
        gaps = {"missing_data": ["缺时间线"], "blind_spots": ["缺外联证据"]}
        questions = ExplainabilityService.build_suggested_questions(parsed, gaps)
        self.assertIsInstance(questions, list)
        # 5 条候选应全部命中
        self.assertEqual(len(questions), 5)
        expected_focus = {
            "attack_vector",
            "attack_chain",
            "missing_data",
            "blind_spots",
            "risk",
        }
        got_focus = set()
        for q in questions:
            self.assertIsInstance(q, dict)
            self.assertTrue(q.get("title"), "title 必须非空")
            self.assertTrue(q.get("question"), "question 必须非空")
            self.assertTrue(q.get("focus_area"), "focus_area 必须非空")
            # focus_area 必须是预期取值之一
            self.assertIn(q["focus_area"], expected_focus)
            got_focus.add(q["focus_area"])
        self.assertEqual(got_focus, expected_focus)

    def test_build_suggested_questions_title_is_short_summary(self):
        from app.services.explainability_service import ExplainabilityService

        # 现有 5 条预置问题均 > 18 字，故 title 会被截断为「前 18 字 + '…'」
        parsed = {"threat_analysis": {"attack_vector": "X" * 5}}
        questions = ExplainabilityService.build_suggested_questions(parsed, {})
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual(q["focus_area"], "attack_vector")
        self.assertTrue(q["question"].startswith("这个攻击入口"))
        # 长问题被截断：title 以 '…' 结尾，且不含完整问题
        self.assertTrue(q["title"].endswith("…"))
        self.assertNotEqual(q["title"], q["question"])
        # title（去掉省略号）应为 question 的前缀，且长度 = 18 + 1
        self.assertTrue(q["question"].startswith(q["title"][:-1]))
        self.assertEqual(len(q["title"]), 19)

    def test_build_suggested_questions_dedup(self):
        from app.services.explainability_service import ExplainabilityService

        # 同一触发条件只产生一条，不会重复
        parsed = {
            "threat_analysis": {"attack_vector": "A"},
            "timeline_analysis": {"attack_chain": "B"},
        }
        questions = ExplainabilityService.build_suggested_questions(parsed, {})
        self.assertEqual(len(questions), 2)
        titles = [q["question"] for q in questions]
        self.assertEqual(len(titles), len(set(titles)))

    def test_does_not_mutate_inputs(self):
        from app.services.explainability_service import ExplainabilityService

        knowledge = [{"source": "keyword", "title": "测试规则"}]
        parsed = {"threat_analysis": {"attack_vector": "X"}}
        ExplainabilityService.build_evidence_trace(parsed, knowledge, {})
        # 输入对象不应被修改
        self.assertEqual(knowledge, [{"source": "keyword", "title": "测试规则"}])
        self.assertEqual(parsed, {"threat_analysis": {"attack_vector": "X"}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
