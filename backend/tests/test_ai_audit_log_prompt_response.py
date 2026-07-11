"""AI 审计日志 prompt/response 字段修复验证测试套件.

本测试针对 IR Platform 后端的一个 Bug 修复：
    Bug：AI 分析模块的审计日志中「用户提示词(prompt)」与「响应内容(response)」字段显示为空。
    根因：ai_audit_log 表原先没有 prompt/response 列，模型层与 service 层未接收/写入，调用方也未传入。

测试策略：
    - 全部使用真实 SQLite（不 mock 数据库层），以证明落库正确。
    - 每个测试均指向临时库文件（tempfile.mkstemp），绝不指向生产库。
    - 覆盖：正常中文请求、空串边界、默认值边界、超长文本边界、迁移幂等性、schema 兜底。

运行方式：
    python -m pytest backend/tests/test_ai_audit_log_prompt_response.py -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import app.database as db  # noqa: E402
from app.config import settings  # noqa: E402
from app.models.ai_audit_log import AiAuditLog  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402


def _new_temp_db_path() -> str:
    """生成一个临时 SQLite 文件路径（不创建文件，仅取路径）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_audit_prompt_")
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)
    return path


class TestAiAuditLogPromptResponse(unittest.TestCase):
    """验证 ai_audit_log 表的 prompt / response 字段落库与读回一致."""

    # 主测试库（所有普通用例共享，参照 test_ai_audit.py 风格）
    TMP_DB: str = ""

    @classmethod
    def setUpClass(cls):
        """初始化一个真实的临时 SQLite 库（通过 init_db）。"""
        cls.TMP_DB = _new_temp_db_path()
        settings.DB_PATH = cls.TMP_DB

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        # 使用真实的 init_db 建表 + 执行迁移，确保与生产路径完全一致
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        if cls.TMP_DB and os.path.exists(cls.TMP_DB):
            os.unlink(cls.TMP_DB)

    # ── 1. 正常请求：非空中文 prompt / response 落库后读回一致 ──────────
    def test_01_normal_chinese_prompt_response(self):
        prompt = "请分析主机 192.168.1.10 的安全风险，包括登录日志、进程与网络连接。"
        response = "经分析，该主机存在 3 项高风险：暴力破解、可疑进程、异常外连。"

        log = AuditService.log_call(
            host_id=1,
            host_name="WEB-01",
            profile_id=1,
            profile_name="默认配置",
            model_name="gpt-4o",
            status="success",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            latency_ms=1500,
            masked_mode=0,
            prompt=prompt,
            response=response,
            ip_address="127.0.0.1",
        )
        self.assertIsNotNone(log)
        self.assertIn("id", log)

        # 通过 get_by_id 读回
        fetched = AiAuditLog.get_by_id(log["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["prompt"], prompt)
        self.assertEqual(fetched["response"], response)

        # 通过 list_all 读回
        result = AiAuditLog.list_all(page=1, page_size=10)
        self.assertIn(log["id"], [item["id"] for item in result["items"]])
        match = next(it for it in result["items"] if it["id"] == log["id"])
        self.assertEqual(match["prompt"], prompt)
        self.assertEqual(match["response"], response)

    # ── 2. 空串边界：传入空串，读回应是 "" 而非 None ────────────────
    def test_02_empty_string_boundary(self):
        log = AuditService.log_call(
            host_id=2,
            host_name="EMPTY-01",
            model_name="gpt-4o",
            status="success",
            prompt="",
            response="",
        )
        fetched = AiAuditLog.get_by_id(log["id"])
        # 关键断言：必须是空串，而不是 NULL/None
        self.assertIsNotNone(fetched["prompt"])
        self.assertIsNotNone(fetched["response"])
        self.assertEqual(fetched["prompt"], "")
        self.assertEqual(fetched["response"], "")

    # ── 3. 默认值边界：不传 prompt/response，读回应均为空串 ──────────
    def test_03_default_value_empty(self):
        log = AuditService.log_call(
            host_id=3,
            host_name="DEFAULT-01",
            model_name="gpt-4o",
            status="success",
        )
        fetched = AiAuditLog.get_by_id(log["id"])
        self.assertIsNotNone(fetched["prompt"])
        self.assertIsNotNone(fetched["response"])
        self.assertEqual(fetched["prompt"], "")
        self.assertEqual(fetched["response"], "")

    # ── 4. 超长文本边界：数千字符中文长文本，读回完整一致（TEXT 不截断）──
    def test_04_long_text_chinese(self):
        long_prompt = "安全分析请求：" + ("主机进程监控数据与网络连接日志快照。" * 600)
        long_response = "分析报告：" + ("发现异常外连行为与可疑计划任务，建议立即隔离。" * 600)
        self.assertGreater(len(long_prompt), 5000)
        self.assertGreater(len(long_response), 5000)

        log = AuditService.log_call(
            host_id=4,
            host_name="LONG-01",
            model_name="gpt-4o",
            status="success",
            prompt=long_prompt,
            response=long_response,
        )
        fetched = AiAuditLog.get_by_id(log["id"])
        self.assertEqual(fetched["prompt"], long_prompt)
        self.assertEqual(fetched["response"], long_response)
        # 长度完全一致，证明未被截断
        self.assertEqual(len(fetched["prompt"]), len(long_prompt))
        self.assertEqual(len(fetched["response"]), len(long_response))

    # ── 5. 迁移幂等性：旧表无 prompt/response 列，调用迁移补齐；二次调用不报错且列仅一份 ──
    def test_05_migration_idempotent(self):
        # 构造一个不含 prompt/response 列的旧版本 ai_audit_log 表
        old_db = _new_temp_db_path()
        conn = sqlite3.connect(old_db)
        # 注意：_alter_ai_audit_log_table 内部使用 row["name"]，依赖 sqlite3.Row，
        # 这与生产调用方 init_db 设置 conn.row_factory = sqlite3.Row 保持一致。
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE ai_audit_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id             INTEGER,
                host_name           TEXT,
                profile_id          INTEGER,
                profile_name        TEXT,
                model_name          TEXT,
                status              TEXT    NOT NULL DEFAULT 'success',
                prompt_tokens       INTEGER DEFAULT 0,
                completion_tokens   INTEGER DEFAULT 0,
                total_tokens        INTEGER DEFAULT 0,
                latency_ms          INTEGER DEFAULT 0,
                masked_mode         INTEGER DEFAULT 0,
                error_message       TEXT,
                ip_address          TEXT,
                user_id             INTEGER,
                created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()

        # 首次迁移：应补齐 prompt / response 列
        db._alter_ai_audit_log_table(conn)
        cols_after_first = {
            row["name"] for row in conn.execute("PRAGMA table_info(ai_audit_log)").fetchall()
        }
        self.assertIn("prompt", cols_after_first)
        self.assertIn("response", cols_after_first)

        # 二次迁移：应保持幂等——不抛错且列仅存在一份
        db._alter_ai_audit_log_table(conn)  # 不应抛出异常
        rows = conn.execute("PRAGMA table_info(ai_audit_log)").fetchall()
        prompt_count = sum(1 for r in rows if r["name"] == "prompt")
        response_count = sum(1 for r in rows if r["name"] == "response")
        self.assertEqual(prompt_count, 1, "prompt 列不应重复")
        self.assertEqual(response_count, 1, "response 列不应重复")

        conn.close()
        if os.path.exists(old_db):
            os.unlink(old_db)

    # ── 6. 数据库 schema 兜底：真实 init_db() 初始化临时库，PRAGMA 确认列存在 ──
    def test_06_schema_has_prompt_response_columns(self):
        fresh_db = _new_temp_db_path()
        saved_db_path = settings.DB_PATH
        try:
            settings.DB_PATH = fresh_db
            Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
            Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
            Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

            # 用真实的 init_db() 初始化一个全新临时库
            db.init_db()

            # 用独立连接核对 schema
            verify_conn = sqlite3.connect(fresh_db)
            columns = {
                row[1]
                for row in verify_conn.execute("PRAGMA table_info(ai_audit_log)").fetchall()
            }
            self.assertIn("prompt", columns, "ai_audit_log 缺少 prompt 列")
            self.assertIn("response", columns, "ai_audit_log 缺少 response 列")
            verify_conn.close()
        finally:
            # 还原，避免影响其它用例 / 类清理逻辑
            settings.DB_PATH = saved_db_path
            if os.path.exists(fresh_db):
                os.unlink(fresh_db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
