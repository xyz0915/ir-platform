#!/usr/bin/env python3
"""数据采集增强（5 项）独立回归测试.

测试范围:
  1. NetworkConnection 模型 CRUD（batch_create → list_by_host → delete_by_host）
  2. FileHash 模型 CRUD（含 is_signed 字段验证）
  3. WmiSubscription 模型 CRUD（含 event_filter/event_consumer JSON 序列化/反序列化）
  4. RegistryKey 模型 CRUD
  5. clear_analysis_by_host 清理新表
  6. 4 个新 API 端点返回 200（网络连接、文件哈希、WMI 订阅、注册表键值）

运行方式:
    cd backend
    venv\\Scripts\\python.exe tests\\test_data_collection_enhance.py
"""

import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ir_platform.db")


class TestDataCollectionEnhance(unittest.TestCase):
    """数据采集增强模型层独立测试."""

    @classmethod
    def setUpClass(cls):
        """初始化测试数据库."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        os.environ["IR_TEST_DB"] = TEST_DB_PATH

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

        # 创建测试主机（需要 host_id 用于外键）
        from app.models.host import Host
        # 先创建 case
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("增强测试案件", "ENHANCE-TEST-001"),
            )
            case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO hosts (case_id, hostname, ip_address, os_type, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (case_id, "ENHANCE-HOST", "10.0.0.5", "windows", "imported"),
            )
            cls.host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ── NetworkConnection ──────────────────────────────────────────────

    def test_01_network_connection_batch_create(self):
        """NetworkConnection.batch_create 写 2 条 → 返回 2."""
        from app.models.analysis import NetworkConnection

        items = [
            {
                "protocol": "TCP",
                "local_addr": "10.0.0.5",
                "local_port": 50432,
                "remote_addr": "93.184.216.34",
                "remote_port": 443,
                "state": "ESTABLISHED",
                "pid": 1234,
                "process_name": "chrome.exe",
                "collected_at": "2026-07-01 10:00:00",
            },
            {
                "protocol": "UDP",
                "local_addr": "10.0.0.5",
                "local_port": 5353,
                "remote_addr": "224.0.0.251",
                "remote_port": 5353,
                "state": "LISTEN",
                "pid": 5678,
                "process_name": "svchost.exe",
                "collected_at": "2026-07-01 10:00:05",
            },
        ]
        count = NetworkConnection.batch_create(self.host_id, items)
        self.assertEqual(count, 2, f"应写入 2 条，实际写入 {count} 条")

    def test_02_network_connection_list_by_host(self):
        """NetworkConnection.list_by_host 返回 2 条."""
        from app.models.analysis import NetworkConnection

        results = NetworkConnection.list_by_host(self.host_id)
        self.assertEqual(len(results), 2, f"应返回 2 条，实际返回 {len(results)} 条")
        # 验证字段
        conn = results[0]
        self.assertEqual(conn["protocol"], "TCP")
        self.assertEqual(conn["remote_addr"], "93.184.216.34")
        self.assertEqual(conn["pid"], 1234)

    def test_03_network_connection_delete_by_host(self):
        """NetworkConnection.delete_by_host 清空后 list_by_host 返回 []."""
        from app.models.analysis import NetworkConnection

        NetworkConnection.delete_by_host(self.host_id)
        results = NetworkConnection.list_by_host(self.host_id)
        self.assertEqual(len(results), 0, f"删除后应返回 0 条，实际返回 {len(results)} 条")

    # ── FileHash ───────────────────────────────────────────────────────

    def test_04_file_hash_batch_create_with_signed(self):
        """FileHash.batch_create 写 1 条（is_signed=1）."""
        from app.models.analysis import FileHash

        items = [
            {
                "file_path": "C:\\Windows\\System32\\cmd.exe",
                "file_name": "cmd.exe",
                "sha256": "abc123def456abc123def456abc123def456abc123def456abc123def456abc123",
                "is_signed": True,
                "signer": "Microsoft Windows",
                "file_size": 289792,
                "product_name": "Microsoft Windows Operating System",
                "product_version": "10.0.19041.1",
                "collected_at": "2026-07-01 10:00:00",
            },
        ]
        count = FileHash.batch_create(self.host_id, items)
        self.assertEqual(count, 1)

    def test_05_file_hash_list_by_host_verify_signed(self):
        """FileHash.list_by_host 返回 is_signed=1."""
        from app.models.analysis import FileHash

        results = FileHash.list_by_host(self.host_id)
        self.assertEqual(len(results), 1)
        fh = results[0]
        self.assertEqual(fh["is_signed"], 1, f"is_signed 应为 1，实际为 {fh['is_signed']}")
        self.assertEqual(fh["signer"], "Microsoft Windows")
        self.assertEqual(fh["sha256"], "abc123def456abc123def456abc123def456abc123def456abc123def456abc123")

    def test_06_file_hash_delete_by_host(self):
        """FileHash.delete_by_host 清空."""
        from app.models.analysis import FileHash

        FileHash.delete_by_host(self.host_id)
        results = FileHash.list_by_host(self.host_id)
        self.assertEqual(len(results), 0)

    # ── WmiSubscription ────────────────────────────────────────────────

    def test_07_wmi_subscription_json_serialization(self):
        """WmiSubscription.batch_create: event_filter 传 dict → 内部 json.dumps."""
        from app.models.analysis import WmiSubscription

        event_filter_dict = {
            "query": "SELECT * FROM __InstanceCreationEvent WITHIN 5 WHERE TargetInstance ISA 'Win32_Process'",
            "namespace": "root\\subscription",
            "event_type": "__InstanceCreationEvent",
        }
        event_consumer_dict = {
            "type": "CommandLineEventConsumer",
            "command": "cmd.exe /c echo malicious > C:\\temp\\test.txt",
        }

        items = [
            {
                "name": "MaliciousEventSubscription",
                "event_filter": event_filter_dict,
                "event_consumer": event_consumer_dict,
                "binding_type": "Permanent",
                "risk_level": "high",
                "collected_at": "2026-07-01 10:00:00",
            },
        ]
        count = WmiSubscription.batch_create(self.host_id, items)
        self.assertEqual(count, 1)

        # 直接查数据库确认存的是 JSON 字符串
        from app.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT event_filter, event_consumer FROM wmi_subscriptions WHERE host_id = ?",
                (self.host_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            raw_filter = row["event_filter"]
            raw_consumer = row["event_consumer"]
            # 应为 JSON 字符串
            self.assertIsInstance(raw_filter, str, "event_filter 应为 JSON 字符串")
            self.assertIsInstance(raw_consumer, str, "event_consumer 应为 JSON 字符串")
            # 验证可反序列化
            parsed_filter = json.loads(raw_filter)
            self.assertEqual(parsed_filter["query"], event_filter_dict["query"])
            parsed_consumer = json.loads(raw_consumer)
            self.assertEqual(parsed_consumer["command"], event_consumer_dict["command"])

    def test_08_wmi_subscription_list_by_host_deserialization(self):
        """WmiSubscription.list_by_host: event_filter 已反序列化为 dict."""
        from app.models.analysis import WmiSubscription

        results = WmiSubscription.list_by_host(self.host_id)
        self.assertEqual(len(results), 1)
        sub = results[0]
        self.assertIsInstance(sub["event_filter"], dict,
                              f"event_filter 应为 dict，实际为 {type(sub['event_filter'])}")
        self.assertIsInstance(sub["event_consumer"], dict,
                              f"event_consumer 应为 dict，实际为 {type(sub['event_consumer'])}")
        self.assertEqual(sub["event_filter"]["query"],
                         "SELECT * FROM __InstanceCreationEvent WITHIN 5 WHERE TargetInstance ISA 'Win32_Process'")
        self.assertEqual(sub["event_consumer"]["type"], "CommandLineEventConsumer")
        self.assertEqual(sub["name"], "MaliciousEventSubscription")
        self.assertEqual(sub["risk_level"], "high")

    def test_09_wmi_subscription_delete_by_host(self):
        """WmiSubscription.delete_by_host 清空."""
        from app.models.analysis import WmiSubscription

        WmiSubscription.delete_by_host(self.host_id)
        results = WmiSubscription.list_by_host(self.host_id)
        self.assertEqual(len(results), 0)

    # ── RegistryKey ────────────────────────────────────────────────────

    def test_10_registry_key_batch_create(self):
        """RegistryKey.batch_create 写 1 条."""
        from app.models.analysis import RegistryKey

        items = [
            {
                "key_path": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                "value_name": "MalwareEntry",
                "value_type": "REG_SZ",
                "value_data": "C:\\temp\\malware.exe",
                "last_write_time": "2026-07-01 09:30:00",
                "collected_at": "2026-07-01 10:00:00",
            },
        ]
        count = RegistryKey.batch_create(self.host_id, items)
        self.assertEqual(count, 1)

    def test_11_registry_key_list_by_host(self):
        """RegistryKey.list_by_host 返回 1 条."""
        from app.models.analysis import RegistryKey

        results = RegistryKey.list_by_host(self.host_id)
        self.assertEqual(len(results), 1)
        rk = results[0]
        self.assertEqual(rk["key_path"], "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run")
        self.assertEqual(rk["value_name"], "MalwareEntry")
        self.assertEqual(rk["value_type"], "REG_SZ")
        self.assertEqual(rk["value_data"], "C:\\temp\\malware.exe")

    def test_12_registry_key_delete_by_host(self):
        """RegistryKey.delete_by_host 清空."""
        from app.models.analysis import RegistryKey

        RegistryKey.delete_by_host(self.host_id)
        results = RegistryKey.list_by_host(self.host_id)
        self.assertEqual(len(results), 0)

    # ── clear_analysis_by_host 包含新表 ────────────────────────────────

    def test_13_clear_analysis_by_host_includes_new_tables(self):
        """clear_analysis_by_host 清理 4 张新表."""
        from app.models.analysis import (
            NetworkConnection, FileHash, WmiSubscription, RegistryKey,
            clear_analysis_by_host,
        )

        # 向 4 张新表写入数据
        NetworkConnection.batch_create(self.host_id, [
            {"protocol": "TCP", "local_addr": "10.0.0.5", "local_port": 12345,
             "remote_addr": "1.2.3.4", "remote_port": 80, "state": "ESTABLISHED",
             "pid": 999, "process_name": "test.exe", "collected_at": "2026-07-01 10:00:00"},
        ])
        FileHash.batch_create(self.host_id, [
            {"file_path": "C:\\test.exe", "file_name": "test.exe",
             "sha256": "aaa", "is_signed": False, "collected_at": "2026-07-01 10:00:00"},
        ])
        WmiSubscription.batch_create(self.host_id, [
            {"name": "TestSub", "event_filter": {"q": "SELECT"}, "event_consumer": {"t": "CLI"},
             "binding_type": "Permanent", "risk_level": "low", "collected_at": "2026-07-01 10:00:00"},
        ])
        RegistryKey.batch_create(self.host_id, [
            {"key_path": "HKLM\\Test", "value_name": "x", "value_type": "REG_SZ",
             "value_data": "y", "collected_at": "2026-07-01 10:00:00"},
        ])

        # 确认有数据
        self.assertEqual(len(NetworkConnection.list_by_host(self.host_id)), 1)
        self.assertEqual(len(FileHash.list_by_host(self.host_id)), 1)
        self.assertEqual(len(WmiSubscription.list_by_host(self.host_id)), 1)
        self.assertEqual(len(RegistryKey.list_by_host(self.host_id)), 1)

        # 执行清理
        clear_analysis_by_host(self.host_id)

        # 验证全部清空
        self.assertEqual(len(NetworkConnection.list_by_host(self.host_id)), 0,
                         "clear_analysis_by_host 未清理 network_connections")
        self.assertEqual(len(FileHash.list_by_host(self.host_id)), 0,
                         "clear_analysis_by_host 未清理 file_hashes")
        self.assertEqual(len(WmiSubscription.list_by_host(self.host_id)), 0,
                         "clear_analysis_by_host 未清理 wmi_subscriptions")
        self.assertEqual(len(RegistryKey.list_by_host(self.host_id)), 0,
                         "clear_analysis_by_host 未清理 registry_keys")


class TestDataCollectionEnhanceAPI(unittest.TestCase):
    """数据采集增强 API 端点回归测试."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

        # 登录获取 token
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建案件和主机
        response = cls.client.post(
            "/api/cases",
            json={"name": "API增强测试案件", "case_number": "API-ENHANCE-TEST-001"},
            headers=cls.auth_headers,
        )
        cls.case_id = response.json()["data"]["id"]

        response = cls.client.post(
            f"/api/cases/{cls.case_id}/hosts",
            json={
                "hostname": "API-ENHANCE-HOST",
                "ip_address": "10.0.0.10",
                "os_type": "windows",
            },
            headers=cls.auth_headers,
        )
        cls.host_id = response.json()["data"]["id"]

        # 导入 mock 数据并分析（让库里有数据）
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            mock_data = json.load(f)
        import io
        json_bytes = json.dumps(mock_data).encode("utf-8")
        cls.client.post(
            f"/api/hosts/{cls.host_id}/import",
            files={"file": ("agent_output.json", json_bytes, "application/json")},
            headers=cls.auth_headers,
        )
        cls.client.post(
            f"/api/hosts/{cls.host_id}/analyze",
            headers=cls.auth_headers,
        )

        # 写入增强数据
        from app.models.analysis import NetworkConnection, FileHash, WmiSubscription, RegistryKey
        NetworkConnection.batch_create(cls.host_id, [
            {"protocol": "TCP", "local_addr": "10.0.0.10", "local_port": 50001,
             "remote_addr": "1.2.3.4", "remote_port": 443, "state": "ESTABLISHED",
             "pid": 1000, "process_name": "edge.exe", "collected_at": "2026-07-01 10:00:00"},
        ])
        FileHash.batch_create(cls.host_id, [
            {"file_path": "C:\\test.dll", "file_name": "test.dll",
             "sha256": "fff", "is_signed": True, "signer": "Test Corp",
             "collected_at": "2026-07-01 10:00:00"},
        ])
        WmiSubscription.batch_create(cls.host_id, [
            {"name": "ApiTestSub", "event_filter": {"q": "X"}, "event_consumer": {"t": "Y"},
             "binding_type": "Permanent", "risk_level": "medium", "collected_at": "2026-07-01 10:00:00"},
        ])
        RegistryKey.batch_create(cls.host_id, [
            {"key_path": "HKLM\\ApiTest", "value_name": "zz", "value_type": "REG_DWORD",
             "value_data": "1", "collected_at": "2026-07-01 10:00:00"},
        ])

    def test_api_network_connections_200(self):
        """GET /hosts/{host_id}/network-connections 返回 200."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/network-connections",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)

    def test_api_file_hashes_200(self):
        """GET /hosts/{host_id}/file-hashes 返回 200."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/file-hashes",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)

    def test_api_wmi_subscriptions_200(self):
        """GET /hosts/{host_id}/wmi-subscriptions 返回 200."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/wmi-subscriptions",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)

    def test_api_registry_keys_200(self):
        """GET /hosts/{host_id}/registry-keys 返回 200."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/registry-keys",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)


def run_tests():
    """运行所有测试."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestDataCollectionEnhance))
    suite.addTests(loader.loadTestsFromTestCase(TestDataCollectionEnhanceAPI))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("  数据采集增强 — 独立回归测试")
    print("=" * 70)
    print()

    result = run_tests()

    print()
    print("=" * 70)
    print(f"  测试结果: {result.testsRun - len(result.failures) - len(result.errors)}/{result.testsRun} 通过")
    print(f"  失败: {len(result.failures)}  错误: {len(result.errors)}")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
