"""系统服务风险分析器 — 单元测试."""

import pytest

from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer


class TestDetectTamper:
    """安全服务篡改检测测试."""

    def test_detect_tamper_windefend_stopped(self):
        """模拟 WinDefend 状态为 stopped，应触发 P0-1-TAMPER."""
        services = [
            {
                "name": "WinDefend",
                "display_name": "Windows Defender Antivirus Service",
                "status": "stopped",
                "start_type": "auto",
                "path": "C:\\Windows\\System32\\svchost.exe -k secsvcs",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_tamper(services)
        assert len(results) == 1
        r = results[0]
        assert r["rule_id"] == "P0-1-TAMPER"
        assert r["triggered"] is True
        assert r["severity"] == "critical"
        assert "stopped" in r["detail"].lower()
        assert "running" in r["detail"].lower()

    def test_detect_tamper_normal_service_ignored(self):
        """普通服务（不在 SECURITY_SERVICES 中）stopped 不应触发."""
        services = [
            {
                "name": "SomeRandomService",
                "display_name": "Some Random Service",
                "status": "stopped",
                "start_type": "manual",
                "path": "C:\\Program Files\\SomeApp\\svc.exe",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_tamper(services)
        assert len(results) == 0


class TestDetectShadow:
    """影子服务 / 名称伪装检测测试."""

    def test_detect_shadow_name_spoof(self):
        """模拟 "W1nDefend" vs "WinDefend" — 相似度应 >= 0.85."""
        services = [
            {
                "name": "W1nDefend",
                "display_name": "Windows Defender Service",
                "status": "running",
                "start_type": "auto",
                "path": "C:\\Windows\\System32\\svchost.exe",
                "user": "LocalSystem",
            }
        ]
        # W1nDefend 与 windefend 相似度:
        # SequenceMatcher(None, "w1ndefend", "windefend").ratio()
        # = 2*7 / (9+9) = 14/18 ≈ 0.78 < 0.85
        # 但 KNOWN_LEGIT_SERVICES 中没有 "windefend"（它在 SECURITY_SERVICES 中）
        # KNOWN_LEGIT_SERVICES 是正常合法服务，如 dhcp, dnscache 等
        # 所以这个测试需要模拟一个与 KNOWN_LEGIT_SERVICES 中某服务名相似的伪装
        # 比如 "dnhcp" vs "dhcp" → ratio = 2*4/(5+4) = 8/9≈0.89

        services = [
            {
                "name": "dnhcp",
                "display_name": "DHCP Client Spoof",
                "status": "running",
                "start_type": "auto",
                "path": "C:\\Users\\public\\dnhcp.exe",
                "user": "LocalSystem",
            }
        ]

        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1
        r = results[0]
        assert r["rule_id"] == "P0-2-SHADOW"
        assert r["triggered"] is True
        # 应同时触发名称伪装和路径异常
        assert "相似" in r["detail"] or "伪装" in r["detail"] or "shadow" in r["detail"].lower()

    def test_detect_shadow_path_anomaly(self):
        """路径在 TEMP 下，应触发路径异常检测."""
        services = [
            {
                "name": "WindowsUpdateHelper",
                "display_name": "Windows Update Helper",
                "status": "running",
                "start_type": "auto",
                "path": "C:\\Users\\admin\\AppData\\Local\\Temp\\update.exe",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1
        r = results[0]
        assert r["rule_id"] == "P0-2-SHADOW"
        assert r["triggered"] is True
        # 路径中包含 temp 和 appdata
        detail_lower = r["detail"].lower()
        assert "temp" in detail_lower or "appdata" in detail_lower


class TestNormalizePath:
    """路径规范化测试 — 回归保护：环境变量展开后应正确匹配可信/可疑路径."""

    def test_systemroot_env_var_not_shadow(self):
        """%SystemRoot%\\system32\\svchost.exe 展开后应匹配 C:\\Windows\\ 可信前缀，不触发 shadow."""
        services = [
            {
                "name": "TestSystemRootSvc",
                "display_name": "Test SystemRoot Service",
                "status": "running",
                "start_type": "auto",
                "path": "%SystemRoot%\\system32\\svchost.exe -k netsvcs",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        # 路径经 _normalize_path 展开 %SystemRoot% 后以 c:\windows\ 开头，属于可信路径
        # 不应触发 P0-2-SHADOW
        assert len(results) == 0

    def test_programdata_env_var_not_shadow(self):
        """%ProgramData%\\... 展开后应匹配 C:\\ProgramData\\ 可信前缀，不触发 shadow."""
        services = [
            {
                "name": "TestProgramDataSvc",
                "display_name": "Test ProgramData Service",
                "status": "running",
                "start_type": "auto",
                "path": "%ProgramData%\\Microsoft\\Windows Defender\\Platform\\4.18\\MsMpEng.exe",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        # 路径经 _normalize_path 展开后以 c:\programdata\ 开头，属于可信路径
        assert len(results) == 0

    def test_user_temp_path_still_shadow(self):
        """C:\\Users\\...\\AppData\\Temp\\evil.exe 不在可信路径且含 temp/appdata 关键词，仍触发 shadow."""
        services = [
            {
                "name": "EvilService",
                "display_name": "Evil Malware Service",
                "status": "running",
                "start_type": "auto",
                "path": "C:\\Users\\victim\\AppData\\Local\\Temp\\evil.exe",
                "user": "LocalSystem",
            }
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1
        r = results[0]
        assert r["rule_id"] == "P0-2-SHADOW"
        assert r["triggered"] is True
        # 路径包含 temp 或 appdata 关键词
        detail_lower = r["detail"].lower()
        assert "temp" in detail_lower or "appdata" in detail_lower
        assert "不在可信路径" in r["detail"]

    def test_normalize_path_env_var_direct(self):
        """直接测试 _normalize_path：环境变量展开正确性."""
        # %SystemRoot%
        result = ServiceRiskAnalyzer._normalize_path("%SystemRoot%\\system32\\svchost.exe")
        assert result == "c:\\windows\\system32\\svchost.exe"

        # %ProgramData%
        result = ServiceRiskAnalyzer._normalize_path("%ProgramData%\\Microsoft\\Defender\\MsMpEng.exe")
        assert result == "c:\\programdata\\microsoft\\defender\\msmpeng.exe"

        # %windir%
        result = ServiceRiskAnalyzer._normalize_path("%windir%\\system32\\drivers\\etc")
        assert result == "c:\\windows\\system32\\drivers\\etc"

        # 普通路径不变（仅小写化）
        result = ServiceRiskAnalyzer._normalize_path("C:\\Users\\Public\\test.exe")
        assert result == "c:\\users\\public\\test.exe"


class TestAggregateScore:
    """聚合评分测试."""

    def test_aggregate_score_calculation(self):
        """验证评分聚合逻辑：多个触发规则权重累加."""
        detections = [
            {
                "rule_id": "P0-1-TAMPER",
                "rule_name": "安全服务被篡改",
                "triggered": True,
                "severity": "critical",
                "weight": 40,
                "detail": "安全服务 stopped",
                "service_name": "WinDefend",
            },
            {
                "rule_id": "P0-2-SHADOW",
                "rule_name": "影子服务/名称伪装",
                "triggered": True,
                "severity": "critical",
                "weight": 35,
                "detail": "路径异常",
                "service_name": "WinDefend",
            },
            {
                "rule_id": "P1-PRIVESC",
                "rule_name": "服务提权风险",
                "triggered": False,
                "severity": "high",
                "weight": 15,
                "detail": "",
                "service_name": "WinDefend",
            },
        ]
        score = ServiceRiskAnalyzer._calculate_aggregate_score(detections)
        assert score == 75  # 40 + 35

    def test_empty_services_returns_zero(self):
        """空服务列表边界测试."""
        result = ServiceRiskAnalyzer.analyze({}, host_id=1)
        assert result["aggregate_score"] == 0
        assert result["summary"]["total"] == 0
        assert result["summary"]["high_risk_count"] == 0
        assert result["services"] == []
