#!/usr/bin/env python3
"""改密码后无法登录 Bug 的回归测试.

背景：密码哈希方案此前不一致 —— 登录校验用 bcrypt，而 create_user / reset_password
原本用 werkzeug 的 pbkdf2，导致改密码后库里存的是 pbkdf2 串，bcrypt verify 永远失败，
用户登不进。修复后两处都改用 auth_service.hash_password（bcrypt）。

本测试：独立临时 SQLite 库 + FastAPI TestClient（startup 触发 init_db 种入默认 admin）。
断言全部必须 PASS：
  a. admin/admin123 登录拿 token
  b. 带 admin token 创建 qa_user，断言库里 password_hash 以 $2 开头（bcrypt，非 pbkdf2$）
  c. qa_user/Pass@123 登录成功
  d. 带 admin token reset-password 为 NewPass@456 成功
  e. qa_user/NewPass@456 登录成功；旧密码 Pass@123 登录必须失败 (401)
  f. users.py 源码不再出现 generate_password_hash / werkzeug.security

运行方式:
    cd backend
    venv\\Scripts\\python.exe -m pytest tests\\test_password_login_regression.py -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 关键：在任何 app 导入之前，将数据库路径指向独立临时库，绝不触碰生产库 ──
_TMP = tempfile.TemporaryDirectory()
_TMP_DIR = _TMP.name
_TEMP_DB_PATH = os.path.join(_TMP_DIR, "ir_platform.db")

from app.config import settings  # noqa: E402

# 注意：DATA_DIR 必须保持 Path 类型（其它模块会做 DATA_DIR / "xxx" 运算），
# 只把需要字符串落盘的路径（DB_PATH / UPLOAD_DIR / AGENT_DIR）转为 str。
_TMP_PATH = Path(_TMP_DIR)
settings.DB_PATH = str(_TMP_PATH / "ir_platform.db")
settings.DATA_DIR = _TMP_PATH
settings.UPLOAD_DIR = str(_TMP_PATH / "imports")
settings.AGENT_DIR = str(_TMP_PATH / "agent")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

USERS_SOURCE = BACKEND_DIR / "app" / "api" / "users.py"


class TestPasswordLoginRegression(unittest.TestCase):
    """改密码后无法登录 Bug 的回归测试."""

    @classmethod
    def setUpClass(cls):
        """启动 TestClient（触发 startup -> init_db 种入默认 admin）."""
        cls.client = TestClient(app)
        cls.client.__enter__()  # 等价于 `with TestClient(app) as client`
        cls.admin_token = None
        cls.qa_user_id = None

    @classmethod
    def tearDownClass(cls):
        """关闭客户端并清理临时库."""
        try:
            cls.client.__exit__(None, None, None)
        except Exception:
            pass
        _TMP.cleanup()

    # ── a. 默认管理员（bcrypt）可登录 ──────────────────────────
    def test_01_admin_login_success(self):
        """admin/admin123 登录拿到 token（说明默认管理员本身是 bcrypt）."""
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(resp.status_code, 200, f"admin 登录失败: {resp.text}")
        body = resp.json()
        self.assertEqual(body.get("code"), 0, f"admin 登录 code 非 0: {body}")
        token = body.get("data", {}).get("token")
        self.assertTrue(token, "admin 登录未返回 token")
        TestPasswordLoginRegression.admin_token = token

    # ── b. 创建新用户，断言存的是 bcrypt 哈希 ──────────────────
    def test_02_create_user_stores_bcrypt_hash(self):
        """带 admin token 创建 qa_user，库里 password_hash 必须以 $2 开头."""
        self.assertIsNotNone(
            TestPasswordLoginRegression.admin_token, "前置 admin 登录未成功，无法继续"
        )
        headers = {"Authorization": f"Bearer {TestPasswordLoginRegression.admin_token}"}
        resp = self.client.post(
            "/api/users",
            json={"username": "qa_user", "password": "Pass@123", "role": "analyst"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, f"创建用户失败: {resp.text}")
        body = resp.json()
        self.assertEqual(body.get("code"), 0, f"创建用户 code 非 0: {body}")
        new_id = body.get("data", {}).get("id")
        self.assertIsNotNone(new_id, "创建用户未返回 id")
        TestPasswordLoginRegression.qa_user_id = new_id

        # 直连测试库读取该用户行
        conn = sqlite3.connect(settings.DB_PATH)
        try:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", ("qa_user",)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "测试库中未找到 qa_user")
        password_hash = row[0]
        self.assertTrue(
            password_hash.startswith("$2"),
            f"新用户密码哈希不是 bcrypt（应以 $2 开头）：{password_hash}",
        )
        self.assertFalse(
            password_hash.startswith("pbkdf2$"),
            f"新用户密码哈希错误地使用了 pbkdf2：{password_hash}",
        )

    # ── c. 新用户用明文密码可登录 ─────────────────────────────
    def test_03_new_user_login_success(self):
        """qa_user/Pass@123 登录成功（证明 bcrypt 哈希可被 verify）."""
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "qa_user", "password": "Pass@123"},
        )
        self.assertEqual(resp.status_code, 200, f"新用户登录失败: {resp.text}")
        body = resp.json()
        self.assertEqual(body.get("code"), 0, f"新用户登录 code 非 0: {body}")
        token = body.get("data", {}).get("token")
        self.assertTrue(token, "新用户登录未返回 token")

    # ── d. 管理员重置密码成功 ─────────────────────────────────
    def test_04_reset_password_success(self):
        """带 admin token reset-password 为 NewPass@456 返回成功."""
        self.assertIsNotNone(
            TestPasswordLoginRegression.qa_user_id, "前置创建用户未成功，无法继续"
        )
        self.assertIsNotNone(
            TestPasswordLoginRegression.admin_token, "前置 admin 登录未成功，无法继续"
        )
        headers = {"Authorization": f"Bearer {TestPasswordLoginRegression.admin_token}"}
        resp = self.client.post(
            f"/api/users/{TestPasswordLoginRegression.qa_user_id}/reset-password",
            json={"new_password": "NewPass@456"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, f"重置密码失败: {resp.text}")
        body = resp.json()
        self.assertEqual(body.get("code"), 0, f"重置密码 code 非 0: {body}")

    # ── e. 新密码可登录，旧密码不可登录 ───────────────────────
    def test_05_new_password_works_old_password_fails(self):
        """qa_user/NewPass@456 登录成功；qa_user/Pass@123 登录必须失败 (401)."""
        resp_new = self.client.post(
            "/api/auth/login",
            json={"username": "qa_user", "password": "NewPass@456"},
        )
        self.assertEqual(resp_new.status_code, 200, f"新密码登录失败: {resp_new.text}")
        body_new = resp_new.json()
        self.assertEqual(body_new.get("code"), 0, f"新密码登录 code 非 0: {body_new}")
        self.assertTrue(
            body_new.get("data", {}).get("token"), "新密码登录未返回 token"
        )

        resp_old = self.client.post(
            "/api/auth/login",
            json={"username": "qa_user", "password": "Pass@123"},
        )
        self.assertEqual(
            resp_old.status_code,
            401,
            f"旧密码应登录失败(401)，实际: {resp_old.status_code} {resp_old.text}",
        )

    # ── f. 源码层面确认不再使用 werkzeug/generate_password_hash ──
    def test_06_source_no_werkzeug_hash(self):
        """users.py 源码不再出现 generate_password_hash / werkzeug.security."""
        self.assertTrue(USERS_SOURCE.exists(), f"未找到源码: {USERS_SOURCE}")
        text = USERS_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn(
            "generate_password_hash",
            text,
            "users.py 仍包含 generate_password_hash，修复不彻底",
        )
        self.assertNotIn(
            "werkzeug.security",
            text,
            "users.py 仍引用 werkzeug.security，修复不彻底",
        )
        self.assertNotIn(
            "from werkzeug",
            text,
            "users.py 仍 import werkzeug，修复不彻底",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
