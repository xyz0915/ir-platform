"""模块化 AI 分析独立回归测试套件.

测试范围:
    - PromptBuilder.build_module() 有效性 & 数据过滤
    - 非法 module_type 异常处理
    - TOKEN_BUDGET_MAP 与 MODULE_DATA_MAP 覆盖一致性
    - AiAnalysisReport.create() analysis_type/module_type 全链路
    - is_latest UPDATE 加 analysis_type 条件后全量/模块互不覆盖
"""

import os
import unittest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_module_ai_analysis.db")


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


# ==================================================================
# 常量校验测试（不依赖数据库）
# ==================================================================


class TestModuleConstants(unittest.TestCase):
    """测试 MODULE_DATA_MAP / TOKEN_BUDGET_MAP / MODULE_SYSTEM_PROMPTS 一致性."""

    def test_01_module_data_map_has_12_keys(self):
        """MODULE_DATA_MAP 含 12 个模块 key."""
        from app.services.prompt_builder import MODULE_DATA_MAP
        self.assertEqual(len(MODULE_DATA_MAP), 12)
        expected_keys = {
            "profile", "process_list", "abnormal_processes",
            "connections", "persistence", "startup",
            "ioc", "timeline", "users", "services", "usb", "remote_control",
        }
        self.assertEqual(set(MODULE_DATA_MAP.keys()), expected_keys)

    def test_02_token_budget_map_has_12_keys(self):
        """TOKEN_BUDGET_MAP 含 12 个模块 key."""
        from app.services.prompt_builder import TOKEN_BUDGET_MAP
        self.assertEqual(len(TOKEN_BUDGET_MAP), 12)
        from app.services.prompt_builder import MODULE_DATA_MAP
        self.assertEqual(set(TOKEN_BUDGET_MAP.keys()), set(MODULE_DATA_MAP.keys()))

    def test_03_token_budget_map_three_tiers(self):
        """TOKEN_BUDGET_MAP 分三档：4000（重型,3个）/ 2000（中型,5个）/ 1500（轻型,4个）."""
        from app.services.prompt_builder import TOKEN_BUDGET_MAP

        heavy = [k for k, v in TOKEN_BUDGET_MAP.items() if v == 4000]
        medium = [k for k, v in TOKEN_BUDGET_MAP.items() if v == 2000]
        light = [k for k, v in TOKEN_BUDGET_MAP.items() if v == 1500]

        self.assertEqual(len(heavy), 3, f"重型(4000)应有3个，实际: {heavy}")
        self.assertEqual(len(medium), 5, f"中型(2000)应有5个，实际: {medium}")
        self.assertEqual(len(light), 4, f"轻型(1500)应有4个，实际: {light}")

        self.assertIn("process_list", heavy)
        self.assertIn("abnormal_processes", heavy)
        self.assertIn("timeline", heavy)

        self.assertIn("connections", medium)
        self.assertIn("persistence", medium)
        self.assertIn("ioc", medium)
        self.assertIn("startup", medium)
        self.assertIn("profile", medium)

        self.assertIn("users", light)
        self.assertIn("services", light)
        self.assertIn("usb", light)
        self.assertIn("remote_control", light)

    def test_04_module_system_prompts_has_12_keys(self):
        """MODULE_SYSTEM_PROMPTS 含 12 个模块 key."""
        from app.services.prompt_builder import MODULE_SYSTEM_PROMPTS
        self.assertEqual(len(MODULE_SYSTEM_PROMPTS), 12)
        from app.services.prompt_builder import MODULE_DATA_MAP
        self.assertEqual(set(MODULE_SYSTEM_PROMPTS.keys()), set(MODULE_DATA_MAP.keys()))

    def test_05_build_module_invalid_type_raises_valueerror(self):
        """非法 module_type 应抛出 ValueError 并列出有效值."""
        from app.services.prompt_builder import PromptBuilder

        with self.assertRaises(ValueError) as ctx:
            PromptBuilder.build_module(host_id=1, module_type="nonexistent_module")
        self.assertIn("无效的模块类型", str(ctx.exception))
        self.assertIn("nonexistent_module", str(ctx.exception))


# ==================================================================
# PromptBuilder.build_module() 数据库依赖测试
# ==================================================================


class TestBuildModuleWithData(unittest.TestCase):
    """测试 build_module() 对真实数据的过滤行为."""

    @classmethod
    def setUpClass(cls):
        """初始化测试 DB 并创建测试主机与数据."""
        _reset_test_db()

        from app.database import get_connection
        with get_connection() as conn:
            # 创建案件
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("模块分析测试案件", "MOD-TEST-001"),
            )
            # 创建主机
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, os_version, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (1, "MOD-HOST", "192.168.1.100", "windows", "Windows 10 Pro", "imported"),
            )

        # 创建分析结果 (create_or_replace 用位置参数)
        from app.models.analysis import AnalysisResult
        AnalysisResult.create_or_replace(
            host_id=1,
            risk_level="high",
            risk_score=80,
            total_findings=5,
            summary="测试分析摘要：发现恶意后门程序",
            details={
                "abnormal_processes": [],
                "suspicious_connections": [],
                "startup_items": [],
                "ioc_hits": [],
                "timeline_events": [],
            },
        )

        # 创建主机画像 (create_or_replace 用位置参数)
        from app.models.analysis import HostProfile
        HostProfile.create_or_replace(
            host_id=1,
            cpu_info="Intel Core i7",
            memory_info="16GB",
            disk_info="512GB SSD",
            network_info="Ethernet 1Gbps",
            installed_software="Python 3.11, Chrome, Notepad++",
            user_accounts="admin, guest",
            security_products="Windows Defender",
            system_summary="正常 Windows 工作站",
        )

        # 创建 IOC 命中数据 (batch_create 接收 list of dict)
        from app.models.analysis import IocHit
        IocHit.batch_create(host_id=1, items=[
            {
                "ioc_type": "domain",
                "ioc_value": "malware-c2.example.com",
                "matched_in": "suspicious_connections",
                "context": "检测到与已知 C2 域名的外连",
                "severity": "high",
            },
            {
                "ioc_type": "ip",
                "ioc_value": "185.220.101.1",
                "matched_in": "suspicious_connections",
                "context": "Tor 出口节点连接",
                "severity": "medium",
            },
        ])

        # 创建异常进程数据 (batch_create 接收 list of dict)
        from app.models.analysis import AbnormalProcess
        AbnormalProcess.batch_create(host_id=1, items=[
            {
                "pid": 8888,
                "process_name": "suspicious.exe",
                "process_path": "C:\\Temp\\suspicious.exe",
                "command_line": "suspicious.exe -c config.dat",
                "parent_pid": 1234,
                "parent_name": "explorer.exe",
                "reason": "疑似挖矿程序",
                "severity": "high",
            },
        ])

        # 创建可疑外连数据 (batch_create)
        from app.models.analysis import SuspiciousConnection
        SuspiciousConnection.batch_create(host_id=1, items=[
            {
                "protocol": "tcp",
                "local_address": "192.168.1.100",
                "local_port": 49152,
                "remote_address": "malware-c2.example.com",
                "remote_port": 443,
                "state": "ESTABLISHED",
                "process_name": "suspicious.exe",
                "pid": 8888,
                "reason": "连接到已知恶意 C2 服务器",
                "severity": "high",
            },
        ])

    def test_01_build_module_ioc_returns_prompts(self):
        """build_module('ioc') 返回 system_prompt + user_prompt，且不含进程/外连数据."""
        from app.services.prompt_builder import PromptBuilder

        result = PromptBuilder.build_module(host_id=1, module_type="ioc")

        self.assertIn("system_prompt", result)
        self.assertIn("user_prompt", result)
        self.assertIsInstance(result["system_prompt"], str)
        self.assertIsInstance(result["user_prompt"], str)
        self.assertGreater(len(result["system_prompt"]), 100)
        self.assertGreater(len(result["user_prompt"]), 10)

        # user_prompt 应包含 IOC 数据，但不含无关模块数据
        user_prompt = result["user_prompt"]
        self.assertIn("ioc_hits_all", user_prompt,
                      "user_prompt 应包含 IOC 命中数据")
        self.assertIn("malware-c2.example.com", user_prompt,
                      "user_prompt 应包含具体 IOC 值")

        # 不应包含异常进程数据（abnormal_processes_all）
        self.assertNotIn("abnormal_processes_all", user_prompt,
                         "IOC 模块的 user_prompt 不应包含异常进程数据")
        # 不应包含可疑外连数据（suspicious_connections_all）
        self.assertNotIn("suspicious_connections_all", user_prompt,
                         "IOC 模块的 user_prompt 不应包含外连数据")

    def test_02_build_module_profile_returns_prompts(self):
        """build_module('profile') 返回包含主机画像数据的 prompt."""
        from app.services.prompt_builder import PromptBuilder

        result = PromptBuilder.build_module(host_id=1, module_type="profile")

        self.assertIn("system_prompt", result)
        self.assertIn("user_prompt", result)

        user_prompt = result["user_prompt"]
        # 应包含主机基础信息
        self.assertIn("MOD-HOST", user_prompt)
        self.assertIn("192.168.1.100", user_prompt)
        # 应包含分析结果
        self.assertIn("analysis_result", user_prompt)

        # 不应包含 IOC 数据
        self.assertNotIn("ioc_hits_all", user_prompt,
                         "profile 模块不应包含 IOC 数据")

    def test_03_build_module_connections_only_contains_connections(self):
        """build_module('connections') 只含外连数据，不含 IOC."""
        from app.services.prompt_builder import PromptBuilder

        result = PromptBuilder.build_module(host_id=1, module_type="connections")

        user_prompt = result["user_prompt"]
        self.assertIn("suspicious_connections_all", user_prompt,
                      "connections 模块应包含外连数据")
        self.assertNotIn("ioc_hits_all", user_prompt,
                         "connections 模块不应含 IOC 数据")
        self.assertNotIn("abnormal_processes_all", user_prompt,
                         "connections 模块不应含进程数据")

    def test_04_build_module_nonexistent_host_raises_valueerror(self):
        """不存在的 host_id 应抛出 ValueError."""
        from app.services.prompt_builder import PromptBuilder

        with self.assertRaises(ValueError) as ctx:
            PromptBuilder.build_module(host_id=99999, module_type="ioc")
        self.assertIn("不存在", str(ctx.exception))


# ==================================================================
# AiAnalysisReport.create() analysis_type/module_type 全链路测试
# ==================================================================


class TestReportAnalysisTypeModuleType(unittest.TestCase):
    """测试报告创建时 analysis_type/module_type 字段全链路."""

    @classmethod
    def setUpClass(cls):
        _reset_test_db()

        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("分析类型测试案件", "ATYPE-TEST-001"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "ATYPE-HOST", "10.0.0.10", "linux", "imported"),
            )

    def test_01_create_report_default_analysis_type_full(self):
        """默认 analysis_type='full', module_type=None."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="默认全量分析",
        )
        self.assertEqual(report["analysis_type"], "full")
        self.assertIsNone(report["module_type"])

    def test_02_create_report_explicit_module_type(self):
        """显式 analysis_type='module', module_type='ioc'."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="模块 IOC 分析",
            analysis_type="module",
            module_type="ioc",
        )
        self.assertEqual(report["analysis_type"], "module")
        self.assertEqual(report["module_type"], "ioc")

    def test_03_db_readback_analysis_type_module_type(self):
        """DB 直读确认 analysis_type / module_type 持久化正确."""
        from app.database import get_connection

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT analysis_type, module_type FROM ai_analysis_reports ORDER BY id"
            ).fetchall()
            results = [dict(r) for r in rows]

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["analysis_type"], "full")
        self.assertIsNone(results[0]["module_type"])
        self.assertEqual(results[1]["analysis_type"], "module")
        self.assertEqual(results[1]["module_type"], "ioc")


# ==================================================================
# is_latest UPDATE 加 analysis_type 隔离测试
# ==================================================================


class TestIsLatestIsolationByAnalysisType(unittest.TestCase):
    """验证 is_latest UPDATE 加 AND analysis_type=? 后全量/模块互不覆盖."""

    @classmethod
    def setUpClass(cls):
        _reset_test_db()

        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("隔离测试案件", "ISO-TEST-001"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "ISO-HOST", "10.0.0.20", "windows", "imported"),
            )

    def test_01_full_and_module_both_latest(self):
        """同一主机：全量报告和模块报告各自 is_latest=1 互不影响."""
        from app.models.ai_analysis import AiAnalysisReport

        # 创建全量报告 v1
        full1 = AiAnalysisReport.create(
            host_id=1, case_id=1,
            risk_assessment="全量分析 v1",
            analysis_type="full", module_type=None,
        )
        self.assertEqual(full1["is_latest"], 1)
        self.assertEqual(full1["analysis_type"], "full")

        # 创建模块报告 v1
        mod1 = AiAnalysisReport.create(
            host_id=1, case_id=1,
            risk_assessment="模块 IOC 分析 v1",
            analysis_type="module", module_type="ioc",
        )
        self.assertEqual(mod1["is_latest"], 1)
        self.assertEqual(mod1["analysis_type"], "module")

        # 验证两条报告都是 is_latest=1
        from app.database import get_connection
        with get_connection() as conn:
            latest = conn.execute(
                "SELECT id, analysis_type, module_type, is_latest FROM ai_analysis_reports WHERE host_id = ?",
                (1,),
            ).fetchall()
            latest_list = [dict(r) for r in latest]

        self.assertEqual(len(latest_list), 2)
        for row in latest_list:
            self.assertEqual(row["is_latest"], 1,
                             f"报告 {row['analysis_type']} 应为 is_latest=1")

    def test_02_second_full_does_not_affect_module_latest(self):
        """创建第二个全量报告后：旧全量 is_latest=0，模块报告 still is_latest=1."""
        from app.models.ai_analysis import AiAnalysisReport

        # 创建第二个全量报告
        full2 = AiAnalysisReport.create(
            host_id=1, case_id=1,
            risk_assessment="全量分析 v2",
            analysis_type="full", module_type=None,
        )
        self.assertEqual(full2["is_latest"], 1)
        self.assertEqual(full2["analysis_type"], "full")

        # DB 直查
        from app.database import get_connection
        with get_connection() as conn:
            all_rows = conn.execute(
                "SELECT id, analysis_type, module_type, is_latest, version "
                "FROM ai_analysis_reports WHERE host_id = ? ORDER BY id",
                (1,),
            ).fetchall()
            results = [dict(r) for r in all_rows]

        self.assertEqual(len(results), 3)

        # 分类
        full_reports = [r for r in results if r["analysis_type"] == "full"]
        mod_reports = [r for r in results if r["analysis_type"] == "module"]

        # 全量：应有 2 条，只有最新 is_latest=1
        self.assertEqual(len(full_reports), 2)
        full_latest = [r for r in full_reports if r["is_latest"] == 1]
        self.assertEqual(len(full_latest), 1, "全量报告应有且仅有一条 is_latest=1")
        self.assertEqual(full_latest[0]["id"], full2["id"])

        full_old = [r for r in full_reports if r["is_latest"] == 0]
        self.assertEqual(len(full_old), 1, "旧全量报告应为 is_latest=0")

        # 模块：应有 1 条，still is_latest=1
        self.assertEqual(len(mod_reports), 1)
        self.assertEqual(mod_reports[0]["is_latest"], 1,
                         "模块报告应保持 is_latest=1，不被全量报告覆盖")

    def test_03_second_module_does_not_affect_full_latest(self):
        """创建第二个模块报告后：旧模块 is_latest=0，全量报告 still is_latest=1."""
        from app.models.ai_analysis import AiAnalysisReport

        # 创建第二个模块报告（同 module_type）
        mod2 = AiAnalysisReport.create(
            host_id=1, case_id=1,
            risk_assessment="模块 IOC 分析 v2",
            analysis_type="module", module_type="ioc",
        )
        self.assertEqual(mod2["is_latest"], 1)

        from app.database import get_connection
        with get_connection() as conn:
            all_rows = conn.execute(
                "SELECT id, analysis_type, module_type, is_latest "
                "FROM ai_analysis_reports WHERE host_id = ? ORDER BY id",
                (1,),
            ).fetchall()
            results = [dict(r) for r in all_rows]

        self.assertEqual(len(results), 4)

        full_reports = [r for r in results if r["analysis_type"] == "full"]
        mod_reports = [r for r in results if r["analysis_type"] == "module"]

        # 全量：full v2 仍应保持 is_latest=1
        full_latest = [r for r in full_reports if r["is_latest"] == 1]
        self.assertEqual(len(full_latest), 1,
                         "全量报告应仍有一条 is_latest=1")

        # 模块：应有 2 条，只有最新 is_latest=1
        self.assertEqual(len(mod_reports), 2)
        mod_latest = [r for r in mod_reports if r["is_latest"] == 1]
        self.assertEqual(len(mod_latest), 1, "模块报告应有且仅有一条 is_latest=1")
        self.assertEqual(mod_latest[0]["id"], mod2["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
