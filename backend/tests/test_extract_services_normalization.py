"""_extract_services() 归一化逻辑 — 回归测试."""

import pytest

from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer


class TestExtractServicesNormalization:
    """验证 _extract_services() 的字段归一化逻辑."""

    # (a) 整数 start_type 映射
    def test_start_type_int_mapping_manual(self):
        """输入 start_type=3 → 输出 "manual"."""
        raw = {"services": [{"name": "s1", "start_type": 3}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "manual"

    def test_start_type_int_mapping_boot(self):
        """输入 start_type=0 → 输出 "boot" (0 是 falsy 必须正确处理)."""
        raw = {"services": [{"name": "s1", "start_type": 0}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "boot"

    def test_start_type_int_mapping_system(self):
        """输入 start_type=1 → 输出 "system"."""
        raw = {"services": [{"name": "s1", "start_type": 1}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "system"

    def test_start_type_int_mapping_auto(self):
        """输入 start_type=2 → 输出 "auto"."""
        raw = {"services": [{"name": "s1", "start_type": 2}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "auto"

    def test_start_type_int_mapping_disabled(self):
        """输入 start_type=4 → 输出 "disabled"."""
        raw = {"services": [{"name": "s1", "start_type": 4}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "disabled"

    def test_start_type_int_mapping_out_of_range(self):
        """输入 start_type=99 → 回退 "auto"."""
        raw = {"services": [{"name": "s1", "start_type": 99}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "auto"

    def test_start_type_string_passthrough(self):
        """输入 start_type="manual" (字符串) → 输出 "manual"."""
        raw = {"services": [{"name": "s1", "start_type": "manual"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "manual"

    def test_start_type_missing_defaults_auto(self):
        """无 start_type 字段 → 输出 "auto"."""
        raw = {"services": [{"name": "s1"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["start_type"] == "auto"

    # (b) command 字段映射为 path
    def test_path_from_command_field(self):
        """command="C:\\test.exe" → path="C:\\test.exe"."""
        raw = {"services": [{"name": "s1", "command": "C:\\test.exe"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["path"] == "C:\\test.exe"

    def test_path_from_path_field_first(self):
        """同时有 path 和 command → path 优先."""
        raw = {
            "services": [
                {
                    "name": "s1",
                    "path": "C:\\Windows\\svc.exe",
                    "command": "C:\\test.exe",
                }
            ]
        }
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["path"] == "C:\\Windows\\svc.exe"

    def test_path_from_multiple_fallbacks(self):
        """验证多级回退：path → command → binary_path → ImagePath → binaryPath."""
        raw = {"services": [{"name": "s1", "binary_path": "C:\\bin\\app.exe"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["path"] == "C:\\bin\\app.exe"

    def test_path_empty_when_all_missing(self):
        """所有路径字段都缺失 → path=""."""
        raw = {"services": [{"name": "s1"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["path"] == ""

    # (c) status 默认值
    def test_status_default_unknown(self):
        """无 status 字段 → 输出 "unknown"."""
        raw = {"services": [{"name": "s1"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["status"] == "unknown"

    def test_status_from_status_field(self):
        """status="running" → 输出 "running"."""
        raw = {"services": [{"name": "s1", "status": "running"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["status"] == "running"

    def test_status_from_state_fallback(self):
        """state="stopped" → 输出 "stopped"."""
        raw = {"services": [{"name": "s1", "state": "stopped"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["status"] == "stopped"

    def test_status_empty_string_fallback(self):
        """status="" → 回退到 "unknown"."""
        raw = {"services": [{"name": "s1", "status": ""}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["status"] == "unknown"

    # (d) user 默认值
    def test_user_default_na(self):
        """无 user 字段 → 输出 "N/A"."""
        raw = {"services": [{"name": "s1"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["user"] == "N/A"

    def test_user_from_user_field(self):
        """user="LocalSystem" → 输出 "LocalSystem"."""
        raw = {"services": [{"name": "s1", "user": "LocalSystem"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["user"] == "LocalSystem"

    def test_user_from_username_fallback(self):
        """username="NT AUTHORITY\\SYSTEM" → 输出该值."""
        raw = {"services": [{"name": "s1", "username": "NT AUTHORITY\\SYSTEM"}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["user"] == "NT AUTHORITY\\SYSTEM"

    def test_user_empty_string_fallback(self):
        """user="" → 回退到 "N/A"."""
        raw = {"services": [{"name": "s1", "user": ""}]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result[0]["user"] == "N/A"

    # (e) 混合数据
    def test_mixed_int_start_type_and_command(self):
        """同时有 int start_type + command → 所有字段正确."""
        raw = {
            "services": [
                {
                    "name": "s1",
                    "display_name": "Test Service",
                    "status": "running",
                    "start_type": 3,
                    "command": "C:\\test.exe",
                    "user": "LocalSystem",
                }
            ]
        }
        result = ServiceRiskAnalyzer._extract_services(raw)
        svc = result[0]
        assert svc["name"] == "s1"
        assert svc["display_name"] == "Test Service"
        assert svc["status"] == "running"
        assert svc["start_type"] == "manual"
        assert svc["path"] == "C:\\test.exe"
        assert svc["user"] == "LocalSystem"

    def test_mixed_with_defaults(self):
        """部分字段缺失 → 缺失字段取默认值, 扩展字段正确."""
        raw = {
            "services": [
                {
                    "name": "z",
                    "start_type": 0,
                }
            ]
        }
        result = ServiceRiskAnalyzer._extract_services(raw)
        svc = result[0]
        assert svc["name"] == "z"
        assert svc["start_type"] == "boot"
        assert svc["status"] == "unknown"
        assert svc["path"] == ""
        assert svc["user"] == "N/A"

    # 额外: persistence 嵌套
    def test_services_from_persistence(self):
        """从 raw_data.persistence.services 中提取."""
        raw = {
            "persistence": {
                "services": [
                    {
                        "name": "s1",
                        "status": "running",
                        "start_type": 2,
                        "command": "C:\\svc.exe",
                        "user": "SYSTEM",
                    }
                ]
            }
        }
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert len(result) == 1
        assert result[0]["start_type"] == "auto"
        assert result[0]["path"] == "C:\\svc.exe"

    # 额外: 非 dict 条目应跳过
    def test_skip_non_dict_entries(self):
        """列表中包含非 dict 条目 → 跳过."""
        raw = {"services": [{"name": "s1", "start_type": 3}, "bad_entry"]}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert len(result) == 1
        assert result[0]["start_type"] == "manual"

    # 额外: 非 list services 返回空列表
    def test_non_list_services_returns_empty(self):
        """services 不是 list → 返回 []."""
        raw = {"services": "not_a_list"}
        result = ServiceRiskAnalyzer._extract_services(raw)
        assert result == []

    # 额外: 空输入
    def test_empty_raw_data(self):
        """空 raw_data → 返回 []."""
        result = ServiceRiskAnalyzer._extract_services({})
        assert result == []
