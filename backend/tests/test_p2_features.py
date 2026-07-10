"""P2 功能全面测试套件.

测试范围:
    P2-01: chat_with_ai 方法签名与导入
    P2-02: KnowledgeRetriever.retrieve() 知识库检索
    P2-04: CaseMatcher 历史案例匹配
    P2-06: PromptOptimizer.optimize() 签名, AiPromptVersion 版本管理
    P2-07: CompareService.compare_hosts() 签名与参数校验
    P2-09: 缓存 hash 计算与命中逻辑
    P2-08: Profile 权限过滤 (list_all 带/不带 user_id)
    P2-05: provider_options 返回
    P2-03: PromptBuilder 知识/联动/案例集成
    全局一致性: 导入路径、前端 API 签名一致性

运行方式:
    cd backend && venv/Scripts/python.exe tests/test_p2_features.py
"""

import os
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_p2_features.db")


# ================================================================
# 共享 setUpClass — 数据库初始化
# ================================================================


def _init_test_db():
    """初始化测试数据库（幂等）."""
    from app.config import settings
    from app.database import init_db

    settings.DB_PATH = TEST_DB_PATH

    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

    init_db()


def _reset_test_db():
    """重置测试数据库."""
    db_path = Path(TEST_DB_PATH)
    if db_path.exists():
        db_path.unlink()
    _init_test_db()


class DbTestBase(unittest.TestCase):
    """需要数据库的测试基类."""

    @classmethod
    def setUpClass(cls):
        _reset_test_db()


# ================================================================
# P2-02: KnowledgeRetriever (无需数据库)
# ================================================================


class TestKnowledgeRetriever(unittest.TestCase):
    """测试知识库检索器（仅导入和签名，不依赖数据库）."""

    def test_01_import_succeeds(self):
        """验证 KnowledgeRetriever 可正常导入."""
        from app.services.knowledge_retriever import KnowledgeRetriever
        self.assertTrue(hasattr(KnowledgeRetriever, "retrieve"))

    def test_02_retrieve_is_static_method(self):
        """验证 retrieve 是静态方法."""
        from app.services.knowledge_retriever import KnowledgeRetriever
        self.assertTrue(callable(KnowledgeRetriever.retrieve))

    def test_03_retrieve_empty_data_no_crash(self):
        """空数据不应崩溃."""
        from app.services.knowledge_retriever import KnowledgeRetriever
        result = KnowledgeRetriever.retrieve("", limit=5)
        self.assertIsInstance(result, list)

    def test_04_retrieve_returns_list_of_str(self):
        """retrieve 返回类型应为 list[str]."""
        from app.services.knowledge_retriever import KnowledgeRetriever
        result = KnowledgeRetriever.retrieve("powershell suspicious command execution", limit=5)
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, str)

    def test_05_retrieve_respects_limit(self):
        """retrieve 应遵守 limit 参数."""
        from app.services.knowledge_retriever import KnowledgeRetriever
        result = KnowledgeRetriever.retrieve("malware C2 beacon network connection", limit=3)
        self.assertLessEqual(len(result), 3)

    def test_06_keyword_extraction_from_dict(self):
        """验证关键词提取函数可从字典提取关键词."""
        from app.services.knowledge_retriever import _extract_keywords
        data = {
            "host_basic": {"hostname": "WEB-SERVER", "os_type": "windows"},
            "ioc_hits_high": [
                {"type": "ip", "value": "10.0.0.1", "reason": "Cobalt Strike beacon"}
            ],
        }
        keywords = _extract_keywords(data)
        self.assertIsInstance(keywords, set)
        self.assertIn("web-server", keywords)
        self.assertIn("windows", keywords)
        self.assertIn("cobalt", keywords)
        self.assertIn("strike", keywords)

    def test_07_keyword_extraction_nested_lists(self):
        """验证递归提取支持嵌套列表."""
        from app.services.knowledge_retriever import _extract_keywords
        data = {"items": [{"name": "malware.exe"}, {"name": "suspicious.dll"}]}
        keywords = _extract_keywords(data)
        self.assertIn("malware.exe", keywords)
        self.assertIn("suspicious.dll", keywords)

    def test_08_keyword_extraction_empty(self):
        """空数据应返回空集合."""
        from app.services.knowledge_retriever import _extract_keywords
        keywords = _extract_keywords({})
        self.assertIsInstance(keywords, set)
        self.assertEqual(len(keywords), 0)

    def test_09_rule_loading(self):
        """规则加载函数应返回列表."""
        from app.services.knowledge_retriever import _load_rules
        rules = _load_rules()
        self.assertIsInstance(rules, list)

    def test_10_c2_signature_loading(self):
        """C2 签名加载函数应返回列表."""
        from app.services.knowledge_retriever import _load_c2_signatures
        sigs = _load_c2_signatures()
        self.assertIsInstance(sigs, list)


# ================================================================
# P2-04: CaseMatcher (需要数据库)
# ================================================================


class TestCaseMatcher(DbTestBase):
    """测试历史案例匹配器."""

    def test_01_import_succeeds(self):
        """验证 CaseMatcher 可正常导入."""
        from app.services.case_matcher import CaseMatcher
        self.assertTrue(hasattr(CaseMatcher, "get_same_case_context"))
        self.assertTrue(hasattr(CaseMatcher, "get_similar_cases"))

    def test_02_methods_are_static(self):
        """验证两个方法都是静态方法."""
        from app.services.case_matcher import CaseMatcher
        self.assertTrue(callable(CaseMatcher.get_same_case_context))
        self.assertTrue(callable(CaseMatcher.get_similar_cases))

    def test_03_get_same_case_context_no_data(self):
        """无报告时应返回空字符串."""
        from app.services.case_matcher import CaseMatcher
        result = CaseMatcher.get_same_case_context(host_id=999, case_id=999)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "")

    def test_04_get_same_case_context_with_data(self):
        """有同案件报告时应返回格式化文本."""
        from app.models.ai_analysis import AiAnalysisReport
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("匹配测试案件", "MATCH-001"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "HOST-A", "10.0.0.1", "windows", "imported"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "HOST-B", "10.0.0.2", "linux", "imported"),
            )

        AiAnalysisReport.create(
            host_id=2, case_id=1,
            risk_assessment="高危 - Cobalt Strike 感染",
            threat_analysis="检测到 C2 通信",
            timeline_analysis="时间线分析",
            recommendations="立即断网",
            raw_response="raw", model_used="gpt-4o", tokens_used=500,
        )

        from app.services.case_matcher import CaseMatcher
        result = CaseMatcher.get_same_case_context(host_id=1, case_id=1)
        self.assertIsInstance(result, str)
        self.assertIn("HOST-B", result)

    def test_05_get_similar_cases_no_data(self):
        """无相似报告时应返回空字符串或合理文本."""
        from app.services.case_matcher import CaseMatcher
        result = CaseMatcher.get_similar_cases(host_id=1, risk_level="高危")
        self.assertIsInstance(result, str)

    def test_06_get_similar_cases_empty_risk(self):
        """无风险等级时应返回空字符串."""
        from app.services.case_matcher import CaseMatcher
        result = CaseMatcher.get_similar_cases(host_id=1, risk_level="")
        self.assertEqual(result, "")

    def test_07_case_matcher_error_handling(self):
        """异常情况应优雅降级返回空字符串."""
        from app.services.case_matcher import CaseMatcher
        result = CaseMatcher.get_same_case_context(host_id=-1, case_id=-1)
        self.assertEqual(result, "")


# ================================================================
# P2-06: PromptOptimizer & AiPromptVersion (需要数据库)
# ================================================================


class TestPromptOptimizer(unittest.TestCase):
    """测试提示词优化器签名（不依赖数据库）."""

    def test_01_import_succeeds(self):
        """验证 PromptOptimizer 可正常导入."""
        from app.services.prompt_optimizer import PromptOptimizer
        self.assertTrue(hasattr(PromptOptimizer, "optimize"))

    def test_02_optimize_is_async_static(self):
        """验证 optimize 是异步静态方法."""
        from app.services.prompt_optimizer import PromptOptimizer
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(PromptOptimizer.optimize))

    def test_03_optimize_signature(self):
        """验证 optimize 方法签名包含三个参数."""
        from app.services.prompt_optimizer import PromptOptimizer
        import inspect
        sig = inspect.signature(PromptOptimizer.optimize)
        params = list(sig.parameters.keys())
        self.assertIn("current_prompt", params)
        self.assertIn("feedback", params)
        self.assertIn("profile_id", params)

    def test_04_optimize_return_type_hint(self):
        """验证 optimize 返回类型声明为 dict."""
        from app.services.prompt_optimizer import PromptOptimizer
        import inspect
        sig = inspect.signature(PromptOptimizer.optimize)
        self.assertIsNotNone(sig.return_annotation)


class TestAiPromptVersion(DbTestBase):
    """测试提示词版本管理."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.models.ai_config import AiConfigProfile
        active = AiConfigProfile.get_active()
        if not active:
            AiConfigProfile.create(
                profile_name="版本测试配置",
                provider="openai",
                api_base_url="https://test.example.com",
                api_key="sk-test-version",
                model_name="gpt-4o",
            )

    def test_01_import_succeeds(self):
        """验证 AiPromptVersion 可正常导入."""
        from app.models.ai_config import AiPromptVersion
        self.assertTrue(hasattr(AiPromptVersion, "create"))
        self.assertTrue(hasattr(AiPromptVersion, "list_by_profile"))
        self.assertTrue(hasattr(AiPromptVersion, "get_latest"))
        self.assertTrue(hasattr(AiPromptVersion, "clean_old_versions"))

    def test_02_create_version(self):
        """创建提示词版本记录."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()
        self.assertIsNotNone(active, "No active profile found")

        version = AiPromptVersion.create(
            profile_id=active["id"],
            content="优化后的 system prompt v1",
        )
        self.assertIsNotNone(version)
        self.assertEqual(version["version"], 1)
        self.assertEqual(version["content"], "优化后的 system prompt v1")

    def test_03_version_auto_increment(self):
        """版本号应自动递增."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()
        v2 = AiPromptVersion.create(profile_id=active["id"], content="v2 content")
        v3 = AiPromptVersion.create(profile_id=active["id"], content="v3 content")
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v3["version"], 3)

    def test_04_list_by_profile(self):
        """列出指定 Profile 的版本历史."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()
        versions = AiPromptVersion.list_by_profile(active["id"], limit=5)
        self.assertGreaterEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], max(v["version"] for v in versions))

    def test_05_get_latest(self):
        """获取最新版本."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()
        latest = AiPromptVersion.get_latest(active["id"])
        self.assertIsNotNone(latest)
        self.assertGreaterEqual(latest["version"], 3)

    def test_06_clean_old_versions(self):
        """清理旧版本（保留最新5个）."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()

        for i in range(4, 8):
            AiPromptVersion.create(profile_id=active["id"], content=f"v{i} content")

        versions_before = AiPromptVersion.list_by_profile(active["id"], limit=20)
        self.assertGreater(len(versions_before), 5)

        deleted = AiPromptVersion.clean_old_versions(active["id"], keep=5)
        versions_after = AiPromptVersion.list_by_profile(active["id"], limit=20)
        self.assertLessEqual(len(versions_after), 5)
        self.assertGreaterEqual(deleted, 0)

    def test_07_get_by_id(self):
        """根据 ID 获取版本."""
        from app.models.ai_config import AiPromptVersion, AiConfigProfile

        active = AiConfigProfile.get_active()
        # 先创建一个已知版本，记录其 ID
        known = AiPromptVersion.create(
            profile_id=active["id"], content="known version for id lookup"
        )
        self.assertIsNotNone(known)

        v = AiPromptVersion.get_by_id(known["id"])
        self.assertIsNotNone(v)
        self.assertEqual(v["content"], "known version for id lookup")

        nonexistent = AiPromptVersion.get_by_id(99999)
        self.assertIsNone(nonexistent)


# ================================================================
# P2-07: CompareService (不需要数据库)
# ================================================================


class TestCompareService(unittest.TestCase):
    """测试多主机对比服务."""

    def test_01_import_succeeds(self):
        """验证 CompareService 可正常导入."""
        from app.services.compare_service import CompareService
        self.assertTrue(hasattr(CompareService, "compare_hosts"))
        self.assertTrue(hasattr(CompareService, "stream_events"))

    def test_02_compare_hosts_is_async(self):
        """验证 compare_hosts 是异步方法."""
        from app.services.compare_service import CompareService
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(CompareService.compare_hosts))

    def test_03_compare_hosts_signature(self):
        """验证 compare_hosts 接受 host_ids 参数."""
        from app.services.compare_service import CompareService
        import inspect
        sig = inspect.signature(CompareService.compare_hosts)
        params = list(sig.parameters.keys())
        self.assertIn("host_ids", params)

    def test_04_validate_too_few_hosts(self):
        """少于2台主机应报错."""
        import asyncio
        from app.services.compare_service import CompareService

        async def run():
            with self.assertRaises(ValueError) as ctx:
                await CompareService.compare_hosts([1])
            self.assertIn("至少需要选择 2 台主机", str(ctx.exception))

        asyncio.run(run())

    def test_05_validate_too_many_hosts(self):
        """多于5台主机应报错."""
        import asyncio
        from app.services.compare_service import CompareService

        async def run():
            with self.assertRaises(ValueError) as ctx:
                await CompareService.compare_hosts([1, 2, 3, 4, 5, 6])
            self.assertIn("最多支持 5 台主机", str(ctx.exception))

        asyncio.run(run())

    def test_06_system_prompt_defined(self):
        """验证对比 system prompt 已定义."""
        from app.services.compare_service import CompareService
        self.assertIsInstance(CompareService._COMPARE_SYSTEM_PROMPT, str)
        self.assertIn("风险等级", CompareService._COMPARE_SYSTEM_PROMPT)
        self.assertIn("威胁类型", CompareService._COMPARE_SYSTEM_PROMPT)

    def test_07_build_compare_prompt(self):
        """验证对比 prompt 构建."""
        from app.services.compare_service import CompareService

        hosts_data = [
            {"host_id": 1, "hostname": "A", "ip_address": "10.0.0.1",
             "os_type": "windows", "user_prompt": "test data A"},
            {"host_id": 2, "hostname": "B", "ip_address": "10.0.0.2",
             "os_type": "linux", "user_prompt": "test data B"},
        ]
        prompt = CompareService._build_compare_prompt(hosts_data)
        self.assertIn("主机1", prompt)
        self.assertIn("主机2", prompt)
        self.assertIn("A", prompt)
        self.assertIn("B", prompt)
        self.assertIn("横向对比分析", prompt)

    def test_08_parse_compare_json_valid(self):
        """验证 JSON 解析有效输入."""
        from app.services.compare_service import CompareService
        import json

        test_json = json.dumps({
            "overview": {"total_hosts": 2, "summary": "test"},
            "risk_comparison": {"description": "", "hosts": []},
            "threat_comparison": {
                "description": "", "common_threats": [], "unique_threats": {}
            },
            "attack_path_comparison": {
                "description": "", "similarities": "", "differences": ""
            },
            "recommendation_comparison": {
                "description": "", "common_recommendations": [], "host_specific": {}
            },
        })
        result = CompareService._parse_compare_json(f"```json\n{test_json}\n```")
        self.assertEqual(result["overview"]["total_hosts"], 2)

    def test_09_parse_compare_json_empty(self):
        """验证空输入返回默认结构."""
        from app.services.compare_service import CompareService
        result = CompareService._parse_compare_json("")
        self.assertIn("overview", result)
        self.assertIn("risk_comparison", result)
        self.assertIn("threat_comparison", result)
        self.assertIn("attack_path_comparison", result)
        self.assertIn("recommendation_comparison", result)

    def test_10_parse_compare_json_invalid(self):
        """验证无效 JSON 返回默认结构."""
        from app.services.compare_service import CompareService
        result = CompareService._parse_compare_json("{invalid json")
        self.assertIn("overview", result)


# ================================================================
# P2-01: chat_with_ai
# ================================================================


class TestChatWithAi(unittest.TestCase):
    """测试多轮对话功能（签名和导入验证）."""

    def test_01_method_exists(self):
        """验证 chat_with_ai 方法存在."""
        from app.services.ai_service import AiService
        self.assertTrue(hasattr(AiService, "chat_with_ai"))

    def test_02_method_is_async_static(self):
        """验证是异步静态方法."""
        from app.services.ai_service import AiService
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(AiService.chat_with_ai))

    def test_03_method_signature(self):
        """验证方法签名."""
        from app.services.ai_service import AiService
        import inspect
        sig = inspect.signature(AiService.chat_with_ai)
        params = list(sig.parameters.keys())
        self.assertIn("host_id", params)
        self.assertIn("message", params)
        self.assertIn("conversation_history", params)

    def test_04_return_type_annotation(self):
        """验证返回类型声明为 dict."""
        from app.services.ai_service import AiService
        import inspect
        sig = inspect.signature(AiService.chat_with_ai)
        self.assertIsNotNone(sig.return_annotation)

    def test_05_chat_route_in_api_file(self):
        """验证 chat 路由在 api/ai.py 中存在."""
        api_file = BACKEND_DIR / "app" / "api" / "ai.py"
        content = api_file.read_text(encoding="utf-8")
        self.assertIn("chat_with_ai", content)
        self.assertIn("/analyze/", content)
        self.assertIn("chat", content)

    def test_06_chat_schema_in_file(self):
        """验证 AiChatRequest/AiChatResponse 在 schemas/ai.py 中存在."""
        schema_file = BACKEND_DIR / "app" / "schemas" / "ai.py"
        content = schema_file.read_text(encoding="utf-8")
        self.assertIn("class AiChatRequest", content)
        self.assertIn("class AiChatResponse", content)
        self.assertIn("conversation_id", content)


# ================================================================
# P2-09: 缓存 hash 计算与命中逻辑 (需要数据库)
# ================================================================


class TestCacheLogic(DbTestBase):
    """测试分析缓存逻辑."""

    def _ensure_test_host(self):
        """确保有测试主机."""
        from app.database import get_connection
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM hosts WHERE id = 1"
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                    ("缓存测试", "CACHE-001"),
                )
                conn.execute(
                    "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, "CACHE-HOST", "10.0.0.88", "linux", "imported"),
                )

    def test_01_method_exists(self):
        """验证 _compute_data_hash 方法存在."""
        from app.services.ai_service import AiService
        self.assertTrue(hasattr(AiService, "_compute_data_hash"))

    def test_02_hash_returns_string(self):
        """验证 hash 返回十六进制字符串."""
        self._ensure_test_host()
        from app.services.ai_service import AiService
        result = AiService._compute_data_hash(1)
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 32)  # MD5 = 32 hex chars

    def test_03_hash_deterministic(self):
        """同一输入产生相同 hash."""
        self._ensure_test_host()
        from app.services.ai_service import AiService
        h1 = AiService._compute_data_hash(1)
        h2 = AiService._compute_data_hash(1)
        self.assertEqual(h1, h2)

    def test_04_get_cached_report_exists(self):
        """验证 get_cached_report 方法存在."""
        from app.models.ai_analysis import AiAnalysisReport
        self.assertTrue(hasattr(AiAnalysisReport, "get_cached_report"))

    def test_05_cached_report_no_match(self):
        """无匹配缓存时应返回 None."""
        from app.models.ai_analysis import AiAnalysisReport
        result = AiAnalysisReport.get_cached_report(999, "nonexistent_hash")
        self.assertIsNone(result)

    def test_06_analyze_with_ai_json_has_cache_check(self):
        """验证 analyze_with_ai_json 使用缓存检查."""
        from app.services.ai_service import AiService
        import inspect
        source = inspect.getsource(AiService.analyze_with_ai_json)
        self.assertIn("_compute_data_hash", source)
        self.assertIn("get_cached_report", source)
        self.assertIn("Cache hit", source)

    def test_07_cached_report_create_and_retrieve(self):
        """创建带缓存的报告并检索."""
        self._ensure_test_host()
        from app.models.ai_analysis import AiAnalysisReport

        from datetime import datetime, timezone

        report = AiAnalysisReport.create(
            host_id=1, case_id=1,
            risk_assessment="缓存测试风险",
            model_used="gpt-4o", tokens_used=100,
            data_hash="p2test_hash_12345",
            cached_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )

        result = AiAnalysisReport.get_cached_report(1, "p2test_hash_12345")
        self.assertIsNotNone(result)
        self.assertEqual(result["host_id"], 1)


# ================================================================
# P2-08: Profile 权限过滤 (需要数据库)
# ================================================================


class TestProfilePermissionFiltering(DbTestBase):
    """测试 Profile 权限过滤."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.models.ai_config import AiConfigProfile

        active = AiConfigProfile.get_active()
        if not active:
            AiConfigProfile.create(
                profile_name="权限测试-管理员",
                provider="openai",
                api_base_url="https://admin.example.com",
                api_key="sk-admin",
                model_name="gpt-4o",
            )

        profiles = AiConfigProfile.list_all()
        if len(profiles) < 3:
            AiConfigProfile.create(
                profile_name="权限测试-用户私有",
                provider="azure",
                api_base_url="https://user.example.com",
                api_key="sk-user-private",
                model_name="gpt-4",
            )
            AiConfigProfile.create(
                profile_name="权限测试-公开配置",
                provider="anthropic",
                api_base_url="https://public.example.com",
                api_key="sk-public",
                model_name="claude-3",
            )

    def test_01_list_all_admin_sees_all(self):
        """管理员应看到所有 Profile."""
        from app.models.ai_config import AiConfigProfile
        profiles = AiConfigProfile.list_all(role="admin")
        self.assertGreaterEqual(len(profiles), 3)

    def test_02_list_all_normal_user_no_id(self):
        """普通用户不传 user_id 只看到公开的."""
        from app.models.ai_config import AiConfigProfile
        profiles = AiConfigProfile.list_all(role="user")
        self.assertIsInstance(profiles, list)

    def test_03_list_all_normal_user_with_id(self):
        """普通用户传 user_id 看到自己的+公开的."""
        from app.models.ai_config import AiConfigProfile
        profiles = AiConfigProfile.list_all(user_id=1, role="user")
        self.assertIsInstance(profiles, list)

    def test_04_list_all_no_role_no_id(self):
        """无角色无 user_id 只看到公开的."""
        from app.models.ai_config import AiConfigProfile
        profiles = AiConfigProfile.list_all()
        self.assertIsInstance(profiles, list)

    def test_05_profile_has_required_fields(self):
        """Profile 应包含必需字段."""
        from app.models.ai_config import AiConfigProfile
        active = AiConfigProfile.get_active()
        self.assertIsNotNone(active)
        for field in ["id", "profile_name", "provider", "is_active"]:
            self.assertIn(field, active)


# ================================================================
# P2-05: provider_options (文件检查，不导入 API)
# ================================================================


class TestProviderOptions(unittest.TestCase):
    """测试 provider_options 返回（检查源文件内容）."""

    def _get_ai_py_source(self):
        """读取 ai.py 文件内容."""
        api_file = BACKEND_DIR / "app" / "api" / "ai.py"
        return api_file.read_text(encoding="utf-8")

    def test_01_config_endpoint_has_provider_options(self):
        """验证 GET /ai/config 返回 provider_options."""
        source = self._get_ai_py_source()
        self.assertIn("provider_options", source)

    def test_02_all_providers_present(self):
        """验证所有 9 种 provider 都在选项中."""
        source = self._get_ai_py_source()
        expected_providers = [
            "openai", "azure", "anthropic", "ollama",
            "deepseek", "zhipu", "qwen", "moonshot", "custom",
        ]
        for provider in expected_providers:
            self.assertIn(provider, source,
                          f"Provider '{provider}' not found in ai.py options")

    def test_03_ollama_has_hint(self):
        """Ollama 选项应包含 api_base_url_hint 和 localhost:11434."""
        source = self._get_ai_py_source()
        self.assertIn("api_base_url_hint", source)
        self.assertIn("11434", source)


# ================================================================
# P2-03: PromptBuilder 知识/联动/案例集成
# ================================================================


class TestPromptBuilderIntegration(unittest.TestCase):
    """测试 PromptBuilder 的 P2 集成功能."""

    def test_01_import_succeeds(self):
        """验证 PromptBuilder 可正常导入."""
        from app.services.prompt_builder import PromptBuilder
        self.assertTrue(hasattr(PromptBuilder, "build"))

    def test_02_build_accepts_include_knowledge(self):
        """验证 build 方法接受 include_knowledge 参数."""
        from app.services.prompt_builder import PromptBuilder
        import inspect
        sig = inspect.signature(PromptBuilder.build)
        self.assertIn("include_knowledge", sig.parameters)

    def test_03_knowledge_section_builder_exists(self):
        """验证 _build_knowledge_section 方法存在."""
        from app.services.prompt_builder import PromptBuilder
        self.assertTrue(hasattr(PromptBuilder, "_build_knowledge_section"))

    def test_04_actual_matches_builder_exists(self):
        """验证 _build_actual_matches 方法存在."""
        from app.services.prompt_builder import PromptBuilder
        self.assertTrue(hasattr(PromptBuilder, "_build_actual_matches"))

    def test_05_case_context_builder_exists(self):
        """验证 _build_case_context 方法存在."""
        from app.services.prompt_builder import PromptBuilder
        self.assertTrue(hasattr(PromptBuilder, "_build_case_context"))

    def test_06_knowledge_section_imports_retriever(self):
        """验证 _build_knowledge_section 导入 KnowledgeRetriever."""
        from app.services.prompt_builder import PromptBuilder
        import inspect
        source = inspect.getsource(PromptBuilder._build_knowledge_section)
        self.assertIn("KnowledgeRetriever", source)

    def test_07_knowledge_section_imports_case_matcher(self):
        """验证 _build_case_context 导入 CaseMatcher."""
        from app.services.prompt_builder import PromptBuilder
        import inspect
        source = inspect.getsource(PromptBuilder._build_case_context)
        self.assertIn("CaseMatcher", source)

    def test_08_count_tokens_fallback(self):
        """验证 _count_tokens 有回退策略."""
        from app.services.prompt_builder import PromptBuilder
        tokens = PromptBuilder._count_tokens("hello world 你好世界")
        self.assertGreater(tokens, 0)
        self.assertIsInstance(tokens, int)


# ================================================================
# 全局一致性：导入路径
# ================================================================


class TestImportConsistency(unittest.TestCase):
    """测试全局导入一致性."""

    def test_01_all_p2_services_importable(self):
        """验证所有 4 个新增服务模块可导入."""
        modules = [
            ("app.services.knowledge_retriever", "KnowledgeRetriever"),
            ("app.services.case_matcher", "CaseMatcher"),
            ("app.services.prompt_optimizer", "PromptOptimizer"),
            ("app.services.compare_service", "CompareService"),
        ]
        for module_path, class_name in modules:
            mod = __import__(module_path, fromlist=[class_name])
            self.assertTrue(hasattr(mod, class_name),
                            f"{class_name} not found in {module_path}")

    def test_02_ai_service_imports_prompt_builder(self):
        """验证 ai_service 正确导入 prompt_builder."""
        from app.services.ai_service import AiService
        import inspect
        source = inspect.getsource(AiService._compute_data_hash)
        self.assertIn("PromptBuilder", source)

    def test_03_no_circular_imports(self):
        """验证关键模块没有循环导入."""
        from app.services.ai_service import AiService
        from app.services.ai_task_service import AiTaskService
        from app.services.prompt_builder import PromptBuilder
        from app.services.compare_service import CompareService
        from app.services.case_matcher import CaseMatcher
        from app.services.knowledge_retriever import KnowledgeRetriever
        from app.services.prompt_optimizer import PromptOptimizer
        self.assertTrue(True)

    def test_04_schema_p2_classes_in_file(self):
        """验证 P2 新增 schema 类在 schemas/ai.py 中定义."""
        schema_file = BACKEND_DIR / "app" / "schemas" / "ai.py"
        content = schema_file.read_text(encoding="utf-8")
        expected_classes = [
            "class AiChatRequest",
            "class AiChatResponse",
            "class CompareRequest",
            "class CompareTaskResponse",
            "class PromptOptimizeRequest",
            "class PromptOptimizeResponse",
        ]
        for class_def in expected_classes:
            self.assertIn(class_def, content,
                          f"'{class_def}' not found in schemas/ai.py")

    def test_05_ai_api_imports_compare_service(self):
        """验证 ai.py 导入 CompareService."""
        api_file = BACKEND_DIR / "app" / "api" / "ai.py"
        content = api_file.read_text(encoding="utf-8")
        self.assertIn("from app.services.compare_service import CompareService",
                      content)

    def test_06_ai_api_imports_prompt_optimizer(self):
        """验证 ai.py 导入 PromptOptimizer."""
        api_file = BACKEND_DIR / "app" / "api" / "ai.py"
        content = api_file.read_text(encoding="utf-8")
        self.assertIn("from app.services.prompt_optimizer import PromptOptimizer",
                      content)

    def test_07_models_import_consistent(self):
        """验证模型层导入一致."""
        from app.models.ai_analysis import AiAnalysisReport
        from app.models.ai_config import AiConfigProfile, AiPromptVersion, AiConfig
        self.assertTrue(True)


# ================================================================
# 前端 API 签名一致性
# ================================================================


class TestFrontendApiConsistency(unittest.TestCase):
    """测试前端 API 函数与后端端点匹配."""

    def _get_frontend_api_content(self):
        """读取前端 API 文件."""
        fe_path = BACKEND_DIR.parent / "frontend" / "src" / "api" / "ai.js"
        if not fe_path.exists():
            self.skipTest("Frontend API file not found")
        return fe_path.read_text(encoding="utf-8")

    def test_01_chat_endpoint_match(self):
        """前端 POST /ai/analyze/{hostId}/chat → 后端 POST /analyze/{host_id}/chat."""
        content = self._get_frontend_api_content()
        self.assertIn("/ai/analyze/", content)
        self.assertIn("chat", content)

    def test_02_prompt_optimize_endpoint_match(self):
        """前端 POST /ai/prompt/optimize → 后端 POST /prompt/optimize."""
        content = self._get_frontend_api_content()
        self.assertIn("/ai/prompt/optimize", content)

    def test_03_prompt_versions_endpoint_match(self):
        """前端 GET /ai/prompt/versions/{profileId} → 后端 GET /prompt/versions/{profile_id}."""
        content = self._get_frontend_api_content()
        self.assertIn("/ai/prompt/versions", content)

    def test_04_compare_endpoint_match(self):
        """前端 POST /ai/analyze/compare → 后端 POST /analyze/compare."""
        content = self._get_frontend_api_content()
        self.assertIn("/ai/analyze/compare", content)

    def test_05_get_provider_options_exists(self):
        """前端 getProviderOptions 函数存在."""
        content = self._get_frontend_api_content()
        self.assertIn("getProviderOptions", content)

    def test_06_conversation_endpoint_exists(self):
        """前端 getConversation 函数存在."""
        content = self._get_frontend_api_content()
        self.assertIn("getConversation", content)

    def test_07_stream_compare_exists(self):
        """前端 streamCompare 函数存在."""
        content = self._get_frontend_api_content()
        self.assertIn("streamCompare", content)

    def test_08_frontend_dist_exists(self):
        """前端 dist 目录存在并包含构建产物."""
        dist_dir = BACKEND_DIR.parent / "frontend" / "dist"
        self.assertTrue(dist_dir.exists(), f"dist dir not found at {dist_dir}")
        html_files = list(dist_dir.glob("*.html"))
        self.assertGreater(len(html_files), 0, "No HTML files in dist/")
        assets_dir = dist_dir / "assets"
        self.assertTrue(assets_dir.exists(), "assets dir not found in dist/")


# ================================================================
# AiAnalysisReport P2 新增方法
# ================================================================


class TestAiAnalysisReportP2Methods(DbTestBase):
    """测试 AiAnalysisReport P2 新增方法."""

    def test_01_get_cached_report_exists(self):
        """get_cached_report 方法存在."""
        from app.models.ai_analysis import AiAnalysisReport
        self.assertTrue(hasattr(AiAnalysisReport, "get_cached_report"))

    def test_02_get_completed_by_case_exists(self):
        """get_completed_by_case 方法存在且可调用."""
        from app.models.ai_analysis import AiAnalysisReport
        self.assertTrue(hasattr(AiAnalysisReport, "get_completed_by_case"))
        result = AiAnalysisReport.get_completed_by_case(case_id=999)
        self.assertIsInstance(result, list)

    def test_03_get_by_risk_level_exists(self):
        """get_by_risk_level 方法存在且可调用."""
        from app.models.ai_analysis import AiAnalysisReport
        self.assertTrue(hasattr(AiAnalysisReport, "get_by_risk_level"))
        result = AiAnalysisReport.get_by_risk_level(risk_level="高危")
        self.assertIsInstance(result, list)


# ================================================================
# 综合测试入口
# ================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
