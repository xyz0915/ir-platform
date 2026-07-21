"""test_timestamp_fix.py — 时间戳回退链单元测试.

覆盖 6 个核心 Mapper 的 timestamp or 链修复：
  ProcessMapper, NetworkMapper, RegistryMapper,
  FileMapper, PersistenceMapper, AuthMapper

每个 Mapper 至少 2 个用例：
  1. 正常场景（timestamp 存在）
  2. 空字符串 + fallback 场景（关键修复点）
  3. collected_at / last_write_time fallback
  4. 全部字段缺失 → 当前时间兜底

Phase 2 端到端验证：
  模拟 Agent 新采集器输出 → Mapper 正确优先匹配.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.services.event_normalizer import (
    ProcessMapper,
    NetworkMapper,
    RegistryMapper,
    FileMapper,
    PersistenceMapper,
    AuthMapper,
)

# ======================================================================
#  辅助函数
# ======================================================================

TS_EXPECTED = "2026-07-15T10:00:00"
TS_START_TIME = "2026-07-15T11:00:00"
TS_COLLECTED = "2026-07-15T12:00:00"
TS_LAST_WRITE = "2026-07-15T13:00:00"
TS_FALLBACK = "2026-07-11T23:10:07"


def _assert_looks_like_iso_ts(ts: str) -> None:
    """验证返回值是一个合法的 ISO 格式时间戳（不校验具体值）。"""
    assert ts, "timestamp 不应为空"
    assert "T" in ts, f"timestamp 应包含 'T': {ts}"
    # 检查是否能被解析
    try:
        datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        pytest.fail(f"timestamp 不是合法的 ISO 格式: {ts}")


# ======================================================================
#  ProcessMapper
# ======================================================================

class TestProcessMapper:

    mapper = ProcessMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_empty_start_time_fallback(self):
        """start_time 是空字符串 → or 链 fallback 到 _fallback_ts."""
        raw = {"start_time": "", "_fallback_ts": TS_FALLBACK, "name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_start_time_fallback(self):
        """无 timestamp，有 start_time → 使用 start_time."""
        raw = {"start_time": TS_START_TIME, "_fallback_ts": TS_FALLBACK, "name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_START_TIME

    def test_start_time_empty_collected_not_in_chain(self):
        """ProcessMapper 无 collected_at 回退 → start_time 空时直接到 _fallback_ts."""
        raw = {"start_time": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        # ProcessMapper 链: timestamp → start_time → _fallback_ts → now
        # collected_at 不在链中
        assert result["timestamp"] == TS_FALLBACK

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"name": "orphan.exe", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])

    def test_timestamp_empty_string(self):
        """timestamp 是空字符串 → 继续 fallback."""
        raw = {"timestamp": "", "start_time": TS_START_TIME, "_fallback_ts": TS_FALLBACK, "name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        # timestamp="" is falsy → or 链继续
        assert result["timestamp"] == TS_START_TIME


# ======================================================================
#  NetworkMapper
# ======================================================================

class TestNetworkMapper:

    mapper = NetworkMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "remote_address": "8.8.8.8", "remote_port": 443, "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_empty_start_time_fallback(self):
        """start_time 空字符串 → fallback 到 collected_at."""
        raw = {"start_time": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "remote_address": "8.8.8.8", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_collected_at_fallback(self):
        """无 timestamp/start_time → collected_at 优先于 _fallback_ts."""
        raw = {"collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "remote_address": "8.8.8.8", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_empty_collected_at_fallback(self):
        """collected_at 空字符串 → fallback 到 _fallback_ts."""
        raw = {"collected_at": "", "_fallback_ts": TS_FALLBACK, "remote_address": "8.8.8.8", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_start_time_value(self):
        """无 timestamp，有 start_time → 使用 start_time（优先于 collected_at）。"""
        raw = {"start_time": TS_START_TIME, "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "remote_address": "8.8.8.8", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_START_TIME

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"remote_address": "10.0.0.1", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])

    def test_timestamp_empty_string(self):
        """timestamp 空字符串 → 继续 fallback."""
        raw = {"timestamp": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "remote_address": "1.1.1.1", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED


# ======================================================================
#  RegistryMapper
# ======================================================================

class TestRegistryMapper:

    mapper = RegistryMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "key_path": "HKLM\\Software\\Test", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_last_write_time(self):
        """无 timestamp，有 last_write_time → 使用 last_write_time."""
        raw = {"last_write_time": TS_LAST_WRITE, "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "key_path": "HKLM\\Software\\Test", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_LAST_WRITE

    def test_empty_last_write_time_fallback(self):
        """last_write_time 空字符串 → fallback 到 collected_at."""
        raw = {"last_write_time": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "key_path": "HKLM\\Software\\Test", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_collected_at_fallback(self):
        """无 timestamp/last_write_time → collected_at 优先于 _fallback_ts."""
        raw = {"collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "key_path": "HKLM\\Software\\Test", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_empty_collected_at_fallback(self):
        """collected_at 空字符串 → fallback 到 _fallback_ts."""
        raw = {"collected_at": "", "_fallback_ts": TS_FALLBACK, "key_path": "HKLM\\Software\\Test", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"key_path": "HKLM\\Software\\Orphan", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])


# ======================================================================
#  FileMapper
# ======================================================================

class TestFileMapper:

    mapper = FileMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "file_name": "malware.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_collected_at_fallback(self):
        """无 timestamp → collected_at 优先于 _fallback_ts."""
        raw = {"collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "file_name": "malware.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_empty_collected_at_fallback(self):
        """collected_at 空字符串 → fallback 到 _fallback_ts."""
        raw = {"collected_at": "", "_fallback_ts": TS_FALLBACK, "file_name": "test.exe", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"file_name": "orphan.dll", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])

    def test_timestamp_empty_string(self):
        """timestamp 空字符串 → fallback 到 collected_at."""
        raw = {"timestamp": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "file_name": "test.dll", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED


# ======================================================================
#  PersistenceMapper
# ======================================================================

class TestPersistenceMapper:

    mapper = PersistenceMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "name": "TestSvc", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_start_time_fallback(self):
        """无 timestamp，有 start_time → 使用 start_time."""
        raw = {"start_time": TS_START_TIME, "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "name": "TestSvc", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_START_TIME

    def test_empty_start_time_fallback(self):
        """start_time 空字符串 → fallback 到 collected_at."""
        raw = {"start_time": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "name": "TestSvc", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_collected_at_fallback(self):
        """无 timestamp/start_time → collected_at 优先于 _fallback_ts."""
        raw = {"collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "name": "TestSvc", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_empty_collected_at_fallback(self):
        """collected_at 空字符串 → fallback 到 _fallback_ts."""
        raw = {"collected_at": "", "_fallback_ts": TS_FALLBACK, "name": "TestSvc", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"name": "OrphanSvc", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])


# ======================================================================
#  AuthMapper
# ======================================================================

class TestAuthMapper:

    mapper = AuthMapper()

    def test_normal_timestamp(self):
        """timestamp 存在 → 使用 timestamp."""
        raw = {"timestamp": TS_EXPECTED, "user_name": "admin", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_EXPECTED

    def test_start_time_fallback(self):
        """无 timestamp，有 start_time → 使用 start_time."""
        raw = {"start_time": TS_START_TIME, "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "user_name": "admin", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_START_TIME

    def test_empty_start_time_fallback(self):
        """start_time 空字符串 → fallback 到 collected_at."""
        raw = {"start_time": "", "collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "user_name": "admin", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_collected_at_fallback(self):
        """无 timestamp/start_time → collected_at 优先于 _fallback_ts."""
        raw = {"collected_at": TS_COLLECTED, "_fallback_ts": TS_FALLBACK, "user_name": "admin", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_empty_collected_at_fallback(self):
        """collected_at 空字符串 → fallback 到 _fallback_ts."""
        raw = {"collected_at": "", "_fallback_ts": TS_FALLBACK, "user_name": "admin", "host_id": 1}
        result = self.mapper.map(raw)
        assert result["timestamp"] == TS_FALLBACK

    def test_all_missing_returns_now(self):
        """所有字段缺失 → 返回当前时间."""
        raw = {"user_name": "orphan", "host_id": 1}
        result = self.mapper.map(raw)
        _assert_looks_like_iso_ts(result["timestamp"])


# ======================================================================
#  Phase 2 端到端链路验证
# ======================================================================

class TestPhase2EndToEnd:

    """模拟 Phase 2 Agent 新采集器输出 → Mapper 正确处理."""

    def test_registry_agent_output(self):
        """模拟 registry.py 采集的输出 → RegistryMapper 优先匹配 last_write_time."""
        raw = {
            "last_write_time": TS_LAST_WRITE,
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "key_path": r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run\TestMalware",
            "value_name": "MalwareKey",
            "value_type": "REG_SZ",
            "value_data": "evil.exe",
            "host_id": 1,
        }
        result = RegistryMapper().map(raw)
        assert result["timestamp"] == TS_LAST_WRITE  # last_write_time 最优先
        assert result["evidence"]["key_path"] == raw["key_path"]
        assert result["evidence"]["value_data"] == "evil.exe"

    def test_process_agent_output_with_collected_at(self):
        """模拟 processes.py 采集的输出 → ProcessMapper 使用 start_time."""
        raw = {
            "pid": 1234,
            "ppid": 567,
            "name": "malware.exe",
            "path": r"C:\Windows\malware.exe",
            "command_line": "malware.exe -payload",
            "user": "SYSTEM",
            "start_time": TS_START_TIME,
            "threads": 2,
            "connections": [],
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = ProcessMapper().map(raw)
        assert result["timestamp"] == TS_START_TIME

    def test_process_agent_empty_start_time_with_collected_at(self):
        """模拟 processes.py start_time 为空 → ProcessMapper 不使用 collected_at（不在链中）。"""
        raw = {
            "pid": 1234,
            "name": "test.exe",
            "start_time": "",
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = ProcessMapper().map(raw)
        # ProcessMapper 链: timestamp → start_time → _fallback_ts → now
        assert result["timestamp"] == TS_FALLBACK

    def test_network_agent_output_with_collected_at(self):
        """模拟 network.py 采集输出 → NetworkMapper collected_at fallback."""
        raw = {
            "protocol": "TCP",
            "local_address": "192.168.1.2",
            "local_port": 4444,
            "remote_address": "10.0.0.1",
            "remote_port": 8080,
            "state": "ESTABLISHED",
            "pid": 1234,
            "process_name": "malware.exe",
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = NetworkMapper().map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_persistence_agent_output_with_collected_at(self):
        """模拟 persistence.py 采集输出 → PersistenceMapper collected_at fallback."""
        raw = {
            "name": "EvilService",
            "command": r"C:\Windows\evil.exe",
            "location": r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = PersistenceMapper().map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_auth_agent_output_with_collected_at(self):
        """模拟认证事件 → AuthMapper collected_at fallback."""
        raw = {
            "user_name": "attacker",
            "logon_type": "network",
            "source_ip": "10.0.0.5",
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = AuthMapper().map(raw)
        assert result["timestamp"] == TS_COLLECTED

    def test_file_agent_output_with_collected_at(self):
        """模拟文件事件 → FileMapper collected_at fallback."""
        raw = {
            "file_name": "dropper.exe",
            "file_path": r"C:\Users\Public\dropper.exe",
            "file_size": 123456,
            "collected_at": TS_COLLECTED,
            "_fallback_ts": TS_FALLBACK,
            "host_id": 1,
        }
        result = FileMapper().map(raw)
        assert result["timestamp"] == TS_COLLECTED
