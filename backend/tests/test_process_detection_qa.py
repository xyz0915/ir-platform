#!/usr/bin/env python3
"""进程树与异常进程检测增强 — 独立 QA 验证（严过关 / Yan）.

本文件由 QA 独立编写，目标是**对抗式地证明代码按设计工作**，而非复读工程师自测结论。
覆盖主理人指定的 10 类边界 / 对抗场景，并额外发现工程师自测未覆盖的误报缺陷。

测试范围：
  1. process_name_spoof：双扩展名 / 大小写混淆 / 编辑距离=1 / Unicode 同形（Cyrillic о） / 负向
  2. suspicious_path：临时/下载/AppData Roaming/伪装 system32/ADS/UNC 命中 + 白名单负向
     + 附加发现的缺陷：AppData\\Local\\Programs 应豁免却误报
  3. hidden_process：同名异路径命中、system32 不命中
  4. anomalous_net_process：脚本解释器/C2 端口命中、业务端口不误报、浏览器外连不命中、
     connections 经 global_context 按 pid 关联（端到端）
  5. zombie_process：threads==0/孤立超阈值命中、活跃正常进程不命中、reason 标注疑似/待人工确认
  6. orphan_process 修正：ppid==4 不误报、父不存在命中、ppid 0/1/None 不误报
  7. suspicious_parent 扩展：浏览器/PDF/压缩/IM/office 父生效、负向不误报
  8. 权重统一联动：RiskAssessor 阈值联动、单条 critical netcat 实质推高主机评级
  9. 种子机制：干净 DB 上 seed 5 条新行为规则并验证 _match_behavior 路由
 10. DDL 幂等：重复 init_db 不报错且三列存在
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ── 项目路径准备 ────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DOCS_DIR = BACKEND_DIR.parent / "docs"
DEFAULT_RULES_PATH = BACKEND_DIR / "app" / "rules" / "default_rules.json"
SEED_RULES_JSON = DOCS_DIR / "seed_rules_process.json"
SEED_RULES_PY = DOCS_DIR / "seed_rules.py"

from app.config import settings  # noqa: E402

# 设计文档 §4.1 统一权重
UNIFIED_WEIGHTS = {"critical": 35, "high": 20, "medium": 10, "low": 5, "info": 1}


def _behavior_rule(name, pattern, severity="high", **extra):
    """构造一条 behavior 规则 dict（供 match_rule / detect_processes 调用）."""
    condition = {"pattern": pattern, "description": f"qa test {pattern}"}
    condition.update(extra)
    return {
        "name": name,
        "rule_type": "behavior",
        "severity": severity,
        "category": "behavior",
        "description": f"qa description for {name}",
        "condition": condition,
    }


class QABase(unittest.TestCase):
    """共用：初始化临时 SQLite 数据库（与工程师测试隔离的独立库）."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls._orig_db = settings.DB_PATH
        settings.DB_PATH = cls.db_path
        from app.database import init_db

        init_db()

    @classmethod
    def tearDownClass(cls):
        settings.DB_PATH = cls._orig_db
        try:
            if os.path.exists(cls.db_path):
                os.unlink(cls.db_path)
        except OSError:
            pass


# ────────────────────────────────────────────────────────────────────────
# 1. process_name_spoof
# ────────────────────────────────────────────────────────────────────────
class TestProcessNameSpoofQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("process_name_spoof", "process_name_spoof")

    def test_double_extension(self):
        # 双扩展名：良性文档叠加 exe（invoice.pdf.exe）
        self.assertTrue(self.engine.match_rule({"name": "invoice.pdf.exe"}, self.rule))
        # 可执行叠加可执行
        self.assertTrue(self.engine.match_rule({"name": "svchost.exe.exe"}, self.rule))
        # 脚本扩展名叠加 exe
        self.assertTrue(self.engine.match_rule({"name": "update.ps1.exe"}, self.rule))

    def test_case_confusion_and_edit_distance(self):
        # 大小写混淆（Svch0st 实际由编辑距离=1 命中，仍应报）
        self.assertTrue(self.engine.match_rule({"name": "Svch0st"}, self.rule))
        # 编辑距离==1：svch0st → svchost
        self.assertTrue(self.engine.match_rule({"name": "svch0st.exe"}, self.rule))
        # 编辑距离==1：cxmd → cmd
        self.assertTrue(self.engine.match_rule({"name": "cxmd.exe"}, self.rule))
        # 编辑距离==1：taSkmgr → taskmgr
        self.assertTrue(self.engine.match_rule({"name": "taSkmgr.exe"}, self.rule))

    def test_unicode_homoglyph_cyrillic(self):
        # Unicode 同形：Cyrillic о (U+043E) 的 svchοst。
        # 设计文档要求经 NFKC/同形归一后命中系统进程白名单。
        cyrillic_name = "svch\u043est"  # svch + Cyrillic о + st
        self.assertTrue(self.engine.match_rule({"name": cyrillic_name}, self.rule))
        # 全角同形（工程师已覆盖，此处复测确保稳健）
        self.assertTrue(self.engine.match_rule({"name": "\uFF53\uFF56\uFF43\uFF48\uFF4F\uFF53\uFF54.exe"}, self.rule))

    def test_negative_no_false_positive(self):
        # 合法系统进程（精确同名，无伪装）不误报
        self.assertFalse(self.engine.match_rule({"name": "svchost.exe"}, self.rule))
        self.assertFalse(self.engine.match_rule({"name": "explorer.exe"}, self.rule))
        self.assertFalse(self.engine.match_rule({"name": "lsass.exe"}, self.rule))
        # 普通进程与文档文件不误报
        self.assertFalse(self.engine.match_rule({"name": "notepad.exe"}, self.rule))
        self.assertFalse(self.engine.match_rule({"name": "report.pdf"}, self.rule))
        self.assertFalse(self.engine.match_rule({"name": "photo.jpg"}, self.rule))


# ────────────────────────────────────────────────────────────────────────
# 2. suspicious_path
# ────────────────────────────────────────────────────────────────────────
class TestSuspiciousPathQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("suspicious_process_path", "suspicious_path")

    def test_hits(self):
        cases = {
            "temp": r"C:\Temp\evil.exe",
            "tmp": r"C:\Windows\Temp\x.exe",
            "downloads": r"C:\Users\user\Downloads\x.exe",
            "appdata_roaming": r"C:\Users\user\AppData\Roaming\evil.exe",
            "appdata_local": r"C:\Users\user\AppData\Local\evil.exe",
            "disguised_system32_exe": r"C:\Windows\system32.exe\svchost.exe",
            "drive_spoof_system32": r"D:\Windows\System32\evil.exe",
            "ads_stream": r"C:\test\file.txt:stream",
            "ads_stream_exe": r"C:\test\file.txt:stream.exe",
            "abnormal_unc": r"\\server\share\x.exe",
            "public": r"C:\Users\Public\evil.exe",
        }
        for label, path in cases.items():
            with self.subTest(label=label):
                self.assertTrue(
                    self.engine.match_rule({"name": "x.exe", "path": path}, self.rule),
                    f"expected HIT for {label}: {path}",
                )

    def test_whitelist_negatives(self):
        # 主理人指定白名单负向用例：均不应误报
        cases = {
            "program_files": r"C:\Program Files\App\app.exe",
            "program_files_x86": r"C:\Program Files (x86)\App\app.exe",
            "system32": r"C:\Windows\System32\svchost.exe",
            "syswow64": r"C:\Windows\SysWOW64\x.dll",
            "programdata_install": r"C:\ProgramData\Vendor.install\upd.exe",
        }
        for label, path in cases.items():
            with self.subTest(label=label):
                self.assertFalse(
                    self.engine.match_rule({"name": "x.exe", "path": path}, self.rule),
                    f"expected NO hit for {label}: {path}",
                )

    def test_appdata_local_programs_should_be_excluded(self):
        # ★ 独立 QA 发现的设计违背缺陷：
        # 设计文档 §3.2 step 3 明确要求「用户目录 exe 且【非】appdata\local\programs」才命中，
        # 但实现中 step 1 的标记 'appdata\\local' 会在 step 3 的排除逻辑之前先行命中，
        # 导致合法用户安装程序（Teams / Discord / Slack / Python launcher 等位于
        # AppData\Local\Programs 的程序）被误报为 high 级可疑路径。
        # 此处断言设计预期（不应命中）；当前实现会命中 → 暴露源码缺陷。
        path = r"C:\Users\user\AppData\Local\Programs\Microsoft\Teams\teams.exe"
        hit = self.engine.match_rule({"name": "teams.exe", "path": path}, self.rule)
        self.assertFalse(
            hit,
            "AppData\\Local\\Programs 下的合法安装程序不应被 suspicious_path 命中 "
            "(设计 §3.2 明确排除)；当前实现误报，属源码缺陷。",
        )


# ────────────────────────────────────────────────────────────────────────
# 3. hidden_process
# ────────────────────────────────────────────────────────────────────────
class TestHiddenProcessQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("hidden_or_spoofed_service_process", "hidden_process")

    def test_same_name_different_path_hits(self):
        # 退化判定：同名不同路径（仿冒系统服务）命中
        self.assertTrue(
            self.engine.match_rule(
                {"name": "svchost.exe", "path": r"C:\Temp\svchost.exe"}, self.rule
            )
        )
        self.assertTrue(
            self.engine.match_rule(
                {"name": "lsass.exe", "path": r"C:\Users\user\lsass.exe"}, self.rule
            )
        )

    def test_hidden_no_window_hits(self):
        # 增强判定：交互式进程无窗口标题且 session>0 → 疑似隐藏
        self.assertTrue(
            self.engine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": r"C:\Windows\System32\powershell.exe",
                    "window_title": "",
                    "session": 1,
                },
                self.rule,
            )
        )

    def test_negatives(self):
        # 系统服务在正确路径 → 不命中
        self.assertFalse(
            self.engine.match_rule(
                {"name": "svchost.exe", "path": r"C:\Windows\System32\svchost.exe"}, self.rule
            )
        )
        # 非系统服务名在临时目录 → 不命中（hidden 仅针对系统服务名仿冒）
        self.assertFalse(
            self.engine.match_rule(
                {"name": "notepad.exe", "path": r"C:\Temp\notepad.exe"}, self.rule
            )
        )
        # 有窗口标题（非隐藏）→ 不命中
        self.assertFalse(
            self.engine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": r"C:\Windows\System32\powershell.exe",
                    "window_title": "PowerShell",
                    "session": 1,
                },
                self.rule,
            )
        )


# ────────────────────────────────────────────────────────────────────────
# 4. anomalous_net_process
# ────────────────────────────────────────────────────────────────────────
class TestAnomalousNetProcessQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("anomalous_network_process", "anomalous_net_process")

    def test_script_interpreter_c2_port_hits(self):
        for port in (4444, 8443, 1337):
            with self.subTest(port=port):
                self.assertTrue(
                    self.engine.match_rule(
                        {
                            "name": "powershell.exe",
                            "path": r"C:\Temp\x.exe",
                            "connections": [{"remote_port": port}],
                        },
                        self.rule,
                    )
                )

    def test_unsigned_non_system_non_business_hits(self):
        self.assertTrue(
            self.engine.match_rule(
                {
                    "name": "weird.exe",
                    "path": r"C:\Temp\weird.exe",
                    "connections": [{"remote_port": 9000}],
                },
                self.rule,
            )
        )

    def test_business_port_no_false_positive(self):
        # 脚本解释器连业务端口（80/443/53/3389）→ 不误报
        for port in (80, 443, 53, 3389):
            with self.subTest(port=port):
                self.assertFalse(
                    self.engine.match_rule(
                        {
                            "name": "powershell.exe",
                            "path": r"C:\Temp\x.exe",
                            "connections": [{"remote_port": port}],
                        },
                        self.rule,
                    )
                )

    def test_browser_outbound_no_false_positive(self):
        # 正常浏览器外连（业务端口）→ 不命中
        self.assertFalse(
            self.engine.match_rule(
                {
                    "name": "chrome.exe",
                    "path": r"C:\Windows\System32\chrome.exe",
                    "connections": [{"remote_port": 443}],
                },
                self.rule,
            )
        )
        self.assertFalse(
            self.engine.match_rule(
                {
                    "name": "msedge.exe",
                    "path": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    "connections": [{"remote_port": 80}],
                },
                self.rule,
            )
        )

    def test_no_connection_no_hit(self):
        self.assertFalse(
            self.engine.match_rule(
                {"name": "powershell.exe", "path": r"C:\Temp\x.exe", "connections": []},
                self.rule,
            )
        )

    def test_global_context_pid_association_e2e(self):
        # 端到端：进程的 connections 不在自身字段，而在 raw_data.network.connections，
        # 经 detect_processes 注入 global_context 后按 pid 关联应生效。
        from app.analysis.anomaly_detector import AnomalyDetector

        rule = {
            "name": "anomalous_network_process",
            "rule_type": "behavior",
            "severity": "high",
            "category": "behavior",
            "description": "异常网络连接进程",
            "condition": {"pattern": "anomalous_net_process", "description": "异常网络"},
        }
        raw = {
            "processes": [
                {
                    # 注意：进程自身无 connections 字段
                    "pid": 700,
                    "name": "powershell.exe",
                    "path": r"C:\Temp\x.exe",
                    "command_line": "powershell.exe",
                    "ppid": 4,
                }
            ],
            "network": {
                "connections": [
                    {"pid": 700, "remote_port": 4444, "remote_address": "1.2.3.4"}
                ]
            },
        }
        result = AnomalyDetector.detect_processes(raw, [rule])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["process_name"], "powershell.exe")
        self.assertEqual(result[0]["severity"], "high")


# ────────────────────────────────────────────────────────────────────────
# 5. zombie_process
# ────────────────────────────────────────────────────────────────────────
class TestZombieProcessQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("zombie_process_suspect", "zombie_process", threshold_days=7)

    def test_threads_zero_old_hits(self):
        self.assertTrue(
            self.engine.match_rule(
                {
                    "name": "svchost.exe",
                    "path": r"C:\Windows\System32\svchost.exe",
                    "threads": 0,
                    "start_time": "2020-01-01 00:00:00",
                },
                self.rule,
            )
        )

    def test_isolated_old_hits(self):
        # 完全孤立（无外连）且启动超阈值 → 命中
        self.assertTrue(
            self.engine.match_rule(
                {
                    "name": "orphan.exe",
                    "path": r"C:\Temp\orphan.exe",
                    "threads": 5,
                    "start_time": "2020-01-01 00:00:00",
                    "connections": [],
                },
                self.rule,
            )
        )

    def test_recent_start_no_hit(self):
        # 启动时间较近（未超阈值）→ 不命中
        self.assertFalse(
            self.engine.match_rule(
                {"name": "svchost.exe", "threads": 0, "start_time": "2099-01-01 00:00:00"},
                self.rule,
            )
        )

    def test_active_with_connections_no_hit(self):
        # 活跃正常进程：线程数正常且有外连 → 不命中
        self.assertFalse(
            self.engine.match_rule(
                {
                    "name": "svchost.exe",
                    "threads": 4,
                    "start_time": "2020-01-01 00:00:00",
                    "connections": [{"remote_port": 445}],
                },
                self.rule,
            )
        )

    def test_reason_marks_suspected_e2e(self):
        # 命中 reason 应标注「疑似 / 待人工确认」（端到端）。
        from app.analysis.anomaly_detector import AnomalyDetector

        rule = {
            "name": "zombie_process_suspect",
            "rule_type": "behavior",
            "severity": "high",
            "category": "behavior",
            # 与设计 §3.5 / seed 规则一致，描述含「疑似 / 待人工确认」
            "description": "疑似僵尸/残留进程（数据受限启发式：线程数为0或完全孤立且启动超阈值，需人工确认）",
            "condition": {
                "pattern": "zombie_process",
                "threshold_days": 7,
                "description": "疑似僵尸/残留进程（启发式，待人工确认）",
            },
        }
        raw = {
            "processes": [
                {
                    "pid": 30,
                    "name": "svchost.exe",
                    "path": r"C:\Windows\System32\svchost.exe",
                    "command_line": "svchost.exe",
                    "ppid": 4,
                    "threads": 0,
                    "start_time": "2020-01-01 00:00:00",
                }
            ],
            "network": {"connections": []},
        }
        result = AnomalyDetector.detect_processes(raw, [rule])
        self.assertEqual(len(result), 1)
        reason = result[0]["reason"]
        # 设计 §3.5 / §2.2 要求 reason 明示「疑似 + 待人工确认」。
        # seed 规则主描述用「需人工确认」、condition 描述用「待人工确认」，语义一致，均满足要求。
        self.assertIn("疑似", reason)
        self.assertTrue(
            "待人工确认" in reason or "需人工确认" in reason,
            f"reason 应标注'疑似'与'待人工确认/需人工确认'，实际: {reason}",
        )


# ────────────────────────────────────────────────────────────────────────
# 6. orphan_process 修正
# ────────────────────────────────────────────────────────────────────────
class TestOrphanProcessCorrectionQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("orphan_process", "orphan_process")

    def _ctx(self, pids):
        return {"process_map": {pid: {"pid": pid, "name": f"p{pid}.exe"} for pid in pids}}

    def test_ppid_4_no_false_positive(self):
        # Windows System(4) 合法父 → 不误报
        self.assertFalse(
            self.engine.match_rule(
                {"name": "x.exe", "ppid": 4}, self.rule, global_context=self._ctx([4])
            )
        )

    def test_ppid_not_in_map_hits(self):
        # 父 PID 不在进程列表 → 真孤儿命中
        self.assertTrue(
            self.engine.match_rule(
                {"name": "x.exe", "ppid": 9999},
                self.rule,
                global_context=self._ctx([4, 100]),
            )
        )

    def test_ppid_0_1_none_no_flag(self):
        # ppid=0/1/None 排除，避免误报
        for ppid in (0, 1, None):
            with self.subTest(ppid=ppid):
                self.assertFalse(
                    self.engine.match_rule(
                        {"name": "x.exe", "ppid": ppid},
                        self.rule,
                        global_context=self._ctx([4]),
                    )
                )

    def test_real_parent_present_no_orphan(self):
        # 父 PID 在进程列表 → 非孤儿
        self.assertFalse(
            self.engine.match_rule(
                {"name": "x.exe", "ppid": 100},
                self.rule,
                global_context=self._ctx([4, 100]),
            )
        )


# ────────────────────────────────────────────────────────────────────────
# 7. suspicious_parent 扩展
# ────────────────────────────────────────────────────────────────────────
class TestSuspiciousParentExtensionQA(QABase):
    def setUp(self):
        from app.rules.rule_engine import RuleEngine

        self.engine = RuleEngine
        self.rule = _behavior_rule("suspicious_parent", "suspicious_parent")

    def test_browser_parent(self):
        # 浏览器父（chrome）→ powershell 子
        self.assertTrue(
            self.engine.match_rule(
                {"name": "powershell.exe", "parent_name": "chrome.exe"}, self.rule
            )
        )
        # edge / firefox 父
        self.assertTrue(
            self.engine.match_rule(
                {"name": "cmd.exe", "parent_name": "firefox.exe"}, self.rule
            )
        )

    def test_pdf_parent(self):
        # PDF 阅读器父（acrord32）→ wscript 子
        self.assertTrue(
            self.engine.match_rule(
                {"name": "wscript.exe", "parent_name": "acrord32.exe"}, self.rule
            )
        )

    def test_compression_and_im_parent(self):
        # 压缩父（winrar）→ powershell 子
        self.assertTrue(
            self.engine.match_rule(
                {"name": "powershell.exe", "parent_name": "winrar.exe"}, self.rule
            )
        )
        # IM 父（wechat / qq）→ 脚本子
        self.assertTrue(
            self.engine.match_rule(
                {"name": "wscript.exe", "parent_name": "wechat.exe"}, self.rule
            )
        )
        self.assertTrue(
            self.engine.match_rule(
                {"name": "cscript.exe", "parent_name": "qq.exe"}, self.rule
            )
        )

    def test_office_parent_still_works(self):
        # 原 office 父仍生效
        self.assertTrue(
            self.engine.match_rule(
                {"name": "cmd.exe", "parent_name": "winword.exe"}, self.rule
            )
        )

    def test_negatives(self):
        # explorer 父（非可疑父清单）→ 不命中
        self.assertFalse(
            self.engine.match_rule(
                {"name": "powershell.exe", "parent_name": "explorer.exe"}, self.rule
            )
        )
        # 浏览器父但子非脚本解释器 → 不命中
        self.assertFalse(
            self.engine.match_rule(
                {"name": "notepad.exe", "parent_name": "chrome.exe"}, self.rule
            )
        )


# ────────────────────────────────────────────────────────────────────────
# 8. 权重统一联动
# ────────────────────────────────────────────────────────────────────────
class TestUnifiedWeightsQA(QABase):
    def test_weights_aligned(self):
        from app.analysis.anomaly_detector import SEVERITY_SCORES
        from app.analysis.risk_assessor import RiskAssessor

        self.assertEqual(dict(SEVERITY_SCORES), UNIFIED_WEIGHTS)
        self.assertEqual(dict(RiskAssessor.SEVERITY_WEIGHTS), UNIFIED_WEIGHTS)

    def test_risk_level_thresholds(self):
        from app.analysis.risk_assessor import RiskAssessor

        # critical >= 80（3 critical = 105 → 上限 100）
        self.assertEqual(
            RiskAssessor.assess({"abnormal_processes": [{"severity": "critical"}] * 3})[
                "risk_level"
            ],
            "critical",
        )
        # high >= 60（3 high = 60）
        self.assertEqual(
            RiskAssessor.assess({"abnormal_processes": [{"severity": "high"}] * 3})[
                "risk_level"
            ],
            "high",
        )
        # medium >= 40（4 medium = 40）
        self.assertEqual(
            RiskAssessor.assess({"abnormal_processes": [{"severity": "medium"}] * 4})[
                "risk_level"
            ],
            "medium",
        )
        # low >= 20（4 low = 20）
        self.assertEqual(
            RiskAssessor.assess({"abnormal_processes": [{"severity": "low"}] * 4})[
                "risk_level"
            ],
            "low",
        )

    def test_netcat_critical_substantially_raises_host(self):
        # 设计核心诉求：单条 critical（netcat 监听后门）应实质推高主机评级，
        # 不再被权重稀释（旧：nc 为 medium=8，主机几乎不可能升 high）。
        from app.analysis.risk_assessor import RiskAssessor

        others = [{"severity": "high"}, {"severity": "high"}]
        # 新行为：netcat 监听后门 = critical(35)
        new_res = RiskAssessor.assess({"abnormal_processes": others + [{"severity": "critical"}]})
        # 旧行为模拟：netcat 仍为 medium(10)
        old_res = RiskAssessor.assess({"abnormal_processes": others + [{"severity": "medium"}]})

        self.assertEqual(new_res["risk_score"], 75)  # 35 + 20 + 20
        self.assertEqual(new_res["risk_level"], "high")
        self.assertEqual(old_res["risk_score"], 50)  # 20 + 20 + 10
        self.assertEqual(old_res["risk_level"], "medium")
        # 单条 critical netcat 把主机从 medium 抬升到 high（实质性推高）
        self.assertGreater(new_res["risk_score"], old_res["risk_score"])

    def test_single_critical_contribution(self):
        from app.analysis.risk_assessor import RiskAssessor

        # 单条 critical 贡献 35（远超旧 netcat medium=8 / 旧权重 critical=25）
        res = RiskAssessor.assess({"abnormal_processes": [{"severity": "critical"}]})
        self.assertEqual(res["risk_score"], 35)


# ────────────────────────────────────────────────────────────────────────
# 9. 种子机制（独立：干净 DB 上 seed 5 条新行为规则并验证路由）
# ────────────────────────────────────────────────────────────────────────
class TestSeedMechanismQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_db = settings.DB_PATH
        cls.db_path = tempfile.mktemp(suffix=".db")
        settings.DB_PATH = cls.db_path
        from app.database import init_db

        init_db()
        spec = importlib.util.spec_from_file_location("seed_rules_qa_mod", SEED_RULES_PY)
        cls.seed_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.seed_mod)
        cls.seed_result = cls.seed_mod.seed(str(SEED_RULES_JSON))

    @classmethod
    def tearDownClass(cls):
        settings.DB_PATH = cls._orig_db
        try:
            if os.path.exists(cls.db_path):
                os.unlink(cls.db_path)
        except OSError:
            pass

    def test_seed_created_all_five(self):
        self.assertEqual(self.seed_result["failed"], 0)
        # 种子机制幂等：规则可能已由 loader 预注入（created=0）或本次新建（created=5）
        self.assertIn(self.seed_result["created"], (0, 5))

    def test_patterns_in_engine_whitelist(self):
        from app.rules.rule_engine import BEHAVIOR_PATTERNS

        for pat in (
            "zombie_process",
            "process_name_spoof",
            "suspicious_path",
            "hidden_process",
            "anomalous_net_process",
        ):
            self.assertIn(pat, BEHAVIOR_PATTERNS)

    def test_loaded_rules_routable(self):
        # 入库后 load_rules 能读到 5 条，且每条能被 _match_behavior 路由到对应 pattern
        from app.rules.rule_engine import RuleEngine, validate_behavior_pattern

        loaded = RuleEngine.load_rules()
        by_name = {r["name"]: r for r in loaded}

        expected = {
            "process_name_spoof": (
                {"name": "invoice.pdf.exe"},
                True,
            ),
            "suspicious_process_path": (
                {"name": "x.exe", "path": r"C:\Temp\x.exe"},
                True,
            ),
            "hidden_or_spoofed_service_process": (
                {"name": "svchost.exe", "path": r"C:\Temp\svchost.exe"},
                True,
            ),
            "anomalous_network_process": (
                {
                    "name": "powershell.exe",
                    "path": r"C:\Temp\x.exe",
                    "connections": [{"remote_port": 4444}],
                },
                True,
            ),
            "zombie_process_suspect": (
                {
                    "name": "svchost.exe",
                    "threads": 0,
                    "start_time": "2020-01-01 00:00:00",
                },
                True,
            ),
        }
        for name, (sample, want) in expected.items():
            with self.subTest(rule=name):
                self.assertIn(name, by_name, f"{name} 未入库")
                rule = by_name[name]
                # pattern 在引擎白名单中（路由可达）
                self.assertTrue(
                    validate_behavior_pattern(rule["condition"]["pattern"])
                )
                # 实际路由命中
                self.assertEqual(
                    RuleEngine.match_rule(sample, rule), want
                )

    def test_seed_idempotent(self):
        # 再次 seed 应全部 skipped（幂等）
        again = self.seed_mod.seed(str(SEED_RULES_JSON))
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 5)
        self.assertEqual(again["failed"], 0)


# ────────────────────────────────────────────────────────────────────────
# 10. DDL 幂等
# ────────────────────────────────────────────────────────────────────────
class TestDDLIdempotentQA(QABase):
    def test_init_db_idempotent(self):
        from app.database import init_db, get_connection

        # 首次已在 setUpClass 执行；此处再次执行应不抛异常
        init_db()
        with get_connection() as conn:
            cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(abnormal_processes)").fetchall()
            }
        for c in ("risk_score", "matched_rules", "attack_path"):
            self.assertIn(c, cols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
