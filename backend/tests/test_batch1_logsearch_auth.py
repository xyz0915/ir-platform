"""第①批 T-C1 日志检索模块鉴权加固测试（安全关键）.

验证 ``app/api/log_search.py`` 的 9 个端点全部依赖 ``get_current_user``：
- 无 Token / 伪造 Token → 401（被拒绝，未到达业务处理）。
- 合法 Token → 通过鉴权（200 或 404 等，证明已授权，未返回 401/403）。

使用 FastAPI TestClient + 临时隔离 SQLite（绝不触碰 backend/data/ir.db）。
测试用户写入临时库并签发 JWT，走真实 ``get_current_user`` 链路。
"""

import unittest

from fastapi.testclient import TestClient

import app.config as config
from app.database import init_db
from app.models.user import User
from app.services.auth_service import create_token, hash_password

import app.main as main_app_mod


# 9 个端点定义：(method, path, query_params, json_body)
_ENDPOINTS = [
    ("GET", "/api/log-search/search", {}, None),
    ("GET", "/api/log-search/imports", {}, None),
    ("GET", "/api/log-search/imports/99999", {}, None),
    ("GET", "/api/log-search/search/advanced", {"query": 'severity=="high"'}, None),
    ("GET", "/api/log-search/search/raw", {"id": 99999}, None),
    ("GET", "/api/log-search/search/export", {"format": "json"}, None),
    ("GET", "/api/log-search/trend", {}, None),
    ("POST", "/api/log-search/import", None, {"host_id": 1}),
    ("POST", "/api/log-search/imports/99999/to-event", None, None),
]


def _make_isolated_db():
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_auth_")
    os.close(fd)
    config.settings.DB_PATH = path
    init_db()
    return path


def _cleanup_db(path):
    import os
    import gc
    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


class TestLogSearchAuth(unittest.TestCase):
    def setUp(self):
        self._db_path = _make_isolated_db()
        self.user = User.create("qa_auth_user", hash_password("secret-pw"), "admin")
        self.token = create_token(
            {"id": self.user["id"], "username": self.user["username"], "role": "admin"}
        )

    def tearDown(self):
        _cleanup_db(self._db_path)
        self._db_path = None

    def _request(self, client, method, path, params=None, json_body=None, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if method == "GET":
            return client.get(path, params=params, headers=headers)
        return client.post(path, json=json_body or {}, headers=headers)

    def test_all_endpoints_reject_missing_token(self):
        """无 Token → 全部 401（鉴权拦截，未到达业务）。"""
        with TestClient(main_app_mod.app) as client:
            for method, path, params, body in _ENDPOINTS:
                r = self._request(client, method, path, params, body, token=None)
                self.assertEqual(
                    r.status_code, 401,
                    f"{method} {path} 无 Token 应返回 401，实际 {r.status_code}",
                )

    def test_all_endpoints_reject_forged_token(self):
        """伪造/无效 Token → 全部 401。"""
        with TestClient(main_app_mod.app) as client:
            for method, path, params, body in _ENDPOINTS:
                r = self._request(client, method, path, params, body, token="not.a.real.jwt")
                self.assertEqual(
                    r.status_code, 401,
                    f"{method} {path} 伪造 Token 应返回 401，实际 {r.status_code}",
                )

    def test_all_endpoints_allow_valid_token(self):
        """合法 Token → 全部通过鉴权（不返回 401/403；404 表示已授权但资源不存在）。"""
        with TestClient(main_app_mod.app) as client:
            for method, path, params, body in _ENDPOINTS:
                r = self._request(client, method, path, params, body, token=self.token)
                self.assertNotIn(
                    r.status_code, (401, 403),
                    f"{method} {path} 合法 Token 不应被拒绝，实际 {r.status_code}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
