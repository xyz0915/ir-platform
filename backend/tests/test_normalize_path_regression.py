"""_normalize_path() 路径规范化 — 回归测试（影子服务误报修复验证）."""

import pytest

from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer


# ============================================================================
# _normalize_path() — 单元测试
# ============================================================================

class TestNormalizePathEnvVarExpansion:
    """%ENV_VAR% 环境变量展开."""

    def test_systemroot_with_percent(self):
        """%SystemRoot%\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%SystemRoot%\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_systemroot_lowercase(self):
        """%systemroot%\\System32\\drivers\\etc → c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%systemroot%\\System32\\drivers\\etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"

    def test_systemroot_mixed_case(self):
        """%SystemRoot% 大小写混合应正确展开."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%SyStEmRoOt%\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_windir_expansion(self):
        """%windir%\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%windir%\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_programdata_expansion(self):
        """%ProgramData%\\Microsoft\\app.exe → c:\\programdata\\microsoft\\app.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%ProgramData%\\Microsoft\\app.exe"
        )
        assert result == "c:\\programdata\\microsoft\\app.exe"

    def test_programfiles_expansion(self):
        """%ProgramFiles%\\App\\app.exe → c:\\program files\\app\\app.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%ProgramFiles%\\App\\app.exe"
        )
        assert result == "c:\\program files\\app\\app.exe"

    def test_programfiles_x86_expansion(self):
        """%ProgramFiles(x86)%\\App\\app.exe → c:\\program files (x86)\\app\\app.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%ProgramFiles(x86)%\\App\\app.exe"
        )
        assert result == "c:\\program files (x86)\\app\\app.exe"

    def test_env_var_without_trailing_backslash(self):
        """%SystemRoot% (无尾随反斜杠) → c:\\windows."""
        result = ServiceRiskAnalyzer._normalize_path("%SystemRoot%")
        assert result == "c:\\windows"

    def test_env_var_with_trailing_backslash(self):
        """%SystemRoot%\\ (有尾随反斜杠) → c:\\windows."""
        result = ServiceRiskAnalyzer._normalize_path("%SystemRoot%\\")
        assert result == "c:\\windows"


class TestNormalizePathSystemRootPrefix:
    """\\SystemRoot\\ 和 SystemRoot\\ 前缀展开."""

    def test_backslash_systemroot_prefix(self):
        """\\SystemRoot\\System32\\drivers\\etc → c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\SystemRoot\\System32\\drivers\\etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"

    def test_backslash_systemroot_lowercase(self):
        """\\systemroot\\system32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\systemroot\\system32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_systemroot_no_leading_backslash(self):
        """SystemRoot\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "SystemRoot\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_systemroot_forward_slash(self):
        """\\SystemRoot/System32/drivers/etc → c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\SystemRoot/System32/drivers/etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"

    def test_systemroot_prefix_with_kernel_flags(self):
        """\\SystemRoot\\System32\\svchost.exe -k netsvcs (带命令行参数)."""
        # _normalize_path 接收的是 path 字段, 可能含命令行参数
        result = ServiceRiskAnalyzer._normalize_path(
            "\\SystemRoot\\System32\\svchost.exe -k netsvcs"
        )
        # 注意：-k netsvcs 保持原样
        assert result.startswith("c:\\windows\\system32\\svchost.exe")


class TestNormalizePathRelativeSystemPaths:
    """相对 System32\\ / SysWOW64\\ 补全."""

    def test_relative_system32(self):
        """System32\\drivers\\etc → c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "System32\\drivers\\etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"

    def test_relative_system32_lowercase(self):
        """system32\\drivers\\etc → c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "system32\\drivers\\etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"

    def test_relative_syswow64(self):
        """SysWOW64\\drivers\\etc → c:\\windows\\syswow64\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "SysWOW64\\drivers\\etc"
        )
        assert result == "c:\\windows\\syswow64\\drivers\\etc"

    def test_relative_syswow64_lowercase(self):
        """syswow64\\app.exe → c:\\windows\\syswow64\\app.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "syswow64\\app.exe"
        )
        assert result == "c:\\windows\\syswow64\\app.exe"


class TestNormalizePathNTDevicePath:
    """NT 设备路径 \\??\\ 前缀剥离."""

    def test_nt_prefix_with_drive_path(self):
        """\\??\\C:\\Windows\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\??\\C:\\Windows\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_nt_prefix_with_unc_path(self):
        """\\??\\UNC\\server\\share → unc\\server\\share."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\??\\UNC\\server\\share"
        )
        assert result == "unc\\server\\share"

    def test_nt_prefix_lowercase(self):
        """\\??\\c:\\windows\\system32\\drivers\\etc."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\??\\c:\\windows\\system32\\drivers\\etc"
        )
        assert result == "c:\\windows\\system32\\drivers\\etc"


class TestNormalizePathCombined:
    """多步骤组合场景."""

    def test_nt_prefix_with_systemroot_env(self):
        """\\??\\%SystemRoot%\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\??\\%SystemRoot%\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_nt_prefix_with_backslash_systemroot(self):
        """\\??\\SystemRoot\\System32\\svchost.exe → c:\\windows\\system32\\svchost.exe."""
        result = ServiceRiskAnalyzer._normalize_path(
            "\\??\\\\SystemRoot\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_quoted_path_stripping(self):
        """"C:\\Windows\\System32\\svc.exe" → 引号被剥离."""
        result = ServiceRiskAnalyzer._normalize_path(
            '"C:\\Windows\\System32\\svc.exe"'
        )
        assert result == "c:\\windows\\system32\\svc.exe"

    def test_single_quoted_path_stripping(self):
        """'C:\\Windows\\System32\\svc.exe' → 单引号被剥离."""
        result = ServiceRiskAnalyzer._normalize_path(
            "'C:\\Windows\\System32\\svc.exe'"
        )
        assert result == "c:\\windows\\system32\\svc.exe"

    def test_nt_quoted_env_path(self):
        """\\??\\"%SystemRoot%\\System32\\svchost.exe" 完整组合."""
        result = ServiceRiskAnalyzer._normalize_path(
            '\\??\\"%SystemRoot%\\System32\\svchost.exe"'
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_already_normalized_path(self):
        """已规范化的路径保持不变（仅小写化）."""
        result = ServiceRiskAnalyzer._normalize_path(
            "C:\\Windows\\System32\\svchost.exe"
        )
        assert result == "c:\\windows\\system32\\svchost.exe"

    def test_trusted_path_with_spaces(self):
        """Program Files (x86) 路径保持正确."""
        result = ServiceRiskAnalyzer._normalize_path(
            "C:\\Program Files (x86)\\Common Files\\Adobe\\ARM\\1.0\\armsvc.exe"
        )
        assert result == (
            "c:\\program files (x86)\\common files\\adobe\\arm\\1.0\\armsvc.exe"
        )


class TestNormalizePathEdgeCases:
    """边界情况测试."""

    def test_empty_string(self):
        """空字符串 → 空字符串."""
        result = ServiceRiskAnalyzer._normalize_path("")
        assert result == ""

    def test_whitespace_only(self):
        """纯空白字符串 → 空字符串."""
        result = ServiceRiskAnalyzer._normalize_path("   ")
        assert result == ""

    def test_path_with_trailing_spaces(self):
        """前后空白被剥离."""
        result = ServiceRiskAnalyzer._normalize_path(
            "  C:\\Windows\\System32\\svc.exe  "
        )
        assert result == "c:\\windows\\system32\\svc.exe"

    def test_unknown_env_var_passthrough(self):
        """未知 %ENV_VAR% 保持原样."""
        result = ServiceRiskAnalyzer._normalize_path(
            "%MY_CUSTOM_VAR%\\app.exe"
        )
        # 未知变量不展开，保持原字符串小写
        assert result == "%my_custom_var%\\app.exe"

    def test_non_windows_path_preserved(self):
        """非 Windows 路径（Linux 风格）保持不变."""
        result = ServiceRiskAnalyzer._normalize_path("/usr/bin/service")
        assert result == "\\usr\\bin\\service"  # os.path.normpath 在 Windows 上转换


# ============================================================================
# _detect_shadow() — 误报修复回归测试
# ============================================================================

class TestDetectShadowRegressionNoFalsePositive:
    """验证合法系统服务路径不再触发 P0-2-SHADOW 误报."""

    def _make_service(self, name, path, user="LocalSystem"):
        """构造标准化服务字典."""
        return {
            "name": name,
            "display_name": name,
            "status": "running",
            "start_type": "auto",
            "path": path,
            "user": user,
        }

    # --- 系统路径变体：均不应触发 ---

    def test_systemroot_percent_path_no_trigger(self):
        """%SystemRoot%\\System32\\svchost.exe — 不应触发影子检测."""
        services = [
            self._make_service(
                "TestSvc",
                "%SystemRoot%\\System32\\svchost.exe -k netsvcs",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"合法系统路径不应触发误报，但触发了: "
            f"{[r['detail'] for r in results]}"
        )

    def test_backslash_systemroot_path_no_trigger(self):
        """\\SystemRoot\\System32\\svchost.exe — 不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "\\SystemRoot\\System32\\svchost.exe -k netsvcs",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"\\SystemRoot\\ 前缀路径不应触发误报: "
            f"{[r['detail'] for r in results]}"
        )

    def test_relative_system32_path_no_trigger(self):
        """System32\\drivers\\disk.sys — 不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "System32\\drivers\\disk.sys",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"相对 System32\\ 路径不应触发误报: "
            f"{[r['detail'] for r in results]}"
        )

    def test_nt_prefix_path_no_trigger(self):
        """\\??\\C:\\Windows\\System32\\svchost.exe — 不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "\\??\\C:\\Windows\\System32\\svchost.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"NT 设备路径不应触发误报: "
            f"{[r['detail'] for r in results]}"
        )

    def test_windir_expansion_no_trigger(self):
        """%windir%\\System32\\svchost.exe — 不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "%windir%\\System32\\svchost.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"%windir% 展开后应为可信路径: "
            f"{[r['detail'] for r in results]}"
        )

    def test_programfiles_path_no_trigger(self):
        """%ProgramFiles%\\App\\app.exe — 不应触发路径异常."""
        services = [
            self._make_service(
                "TestSvc",
                "%ProgramFiles%\\SomeApp\\app.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        # 注意：名称可能与 KNOWN_LEGIT_SERVICES 相似触发名称伪装，
        # 但不应触发路径异常
        path_triggered = any(
            "路径" in r["detail"] and "不在可信路径" in r["detail"]
            for r in results
        )
        assert not path_triggered, (
            f"%ProgramFiles% 展开后应为可信路径，不应触发路径异常: "
            f"{[r['detail'] for r in results]}"
        )

    def test_programdata_path_no_trigger(self):
        """%ProgramData%\\Microsoft\\app.exe — 不应触发路径异常."""
        services = [
            self._make_service(
                "TestSvc",
                "%ProgramData%\\Microsoft\\SomeApp\\app.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        path_triggered = any(
            "路径" in r["detail"] and "不在可信路径" in r["detail"]
            for r in results
        )
        assert not path_triggered, (
            f"%ProgramData% 展开后应为可信路径，不应触发路径异常: "
            f"{[r['detail'] for r in results]}"
        )

    def test_normal_windows_system32_path_no_trigger(self):
        """C:\\Windows\\System32\\svchost.exe — 最常规路径不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "C:\\Windows\\System32\\svchost.exe -k netsvcs",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"标准 Windows 系统路径不应触发误报: "
            f"{[r['detail'] for r in results]}"
        )

    def test_syswow64_path_no_trigger(self):
        """SysWOW64\\app.exe — 不应触发."""
        services = [
            self._make_service(
                "TestSvc",
                "SysWOW64\\someapp.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) == 0, (
            f"SysWOW64 相对路径不应触发误报: "
            f"{[r['detail'] for r in results]}"
        )

    # --- 以下路径仍应触发 ---

    def test_temp_path_still_triggers(self):
        """C:\\Users\\admin\\AppData\\Local\\Temp\\malware.exe — 仍应触发."""
        services = [
            self._make_service(
                "MalwareSvc",
                "C:\\Users\\admin\\AppData\\Local\\Temp\\malware.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1, (
            "恶意临时目录路径应仍触发影子检测"
        )
        assert results[0]["rule_id"] == "P0-2-SHADOW"

    def test_downloads_path_still_triggers(self):
        """C:\\Users\\admin\\Downloads\\bad.exe — 仍应触发."""
        services = [
            self._make_service(
                "EvilSvc",
                "C:\\Users\\admin\\Downloads\\bad.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1, (
            "Downloads 目录路径应仍触发影子检测"
        )

    def test_public_folder_still_triggers(self):
        """C:\\Users\\public\\payload.exe — 仍应触发."""
        services = [
            self._make_service(
                "PayloadSvc",
                "C:\\Users\\public\\payload.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1, (
            "Public 目录路径应仍触发影子检测"
        )

    def test_appdata_roaming_still_triggers(self):
        """C:\\Users\\user\\AppData\\Roaming\\bad.exe — 仍应触发."""
        services = [
            self._make_service(
                "RoamingSvc",
                "C:\\Users\\user\\AppData\\Roaming\\bad.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_shadow(services)
        assert len(results) >= 1, (
            "AppData 路径应仍触发影子检测"
        )


# ============================================================================
# _detect_priv_esc() — 误报修复回归测试
# ============================================================================

class TestDetectPrivEscRegressionNoFalsePositive:
    """验证合法系统服务路径不再触发 P1-PRIVESC 误报."""

    def _make_service(self, name, path, user="LocalSystem"):
        """构造标准化服务字典."""
        return {
            "name": name,
            "display_name": name,
            "status": "running",
            "start_type": "auto",
            "path": path,
            "user": user,
        }

    def test_systemroot_path_no_priv_esc_false_positive(self):
        """高权限 + %SystemRoot% 路径 → 不应触发提权（路径可信）."""
        services = [
            self._make_service(
                "TestSvc",
                "%SystemRoot%\\System32\\svchost.exe -k netsvcs",
                "LocalSystem",
            )
        ]
        results = ServiceRiskAnalyzer._detect_priv_esc(services)
        assert len(results) == 0, (
            f"高权限 + 可信系统路径不应触发提权误报: "
            f"{[r['detail'] for r in results]}"
        )

    def test_nt_prefix_path_no_priv_esc_false_positive(self):
        """高权限 + \\??\\C:\\Windows\\System32 路径 → 不应触发提权."""
        services = [
            self._make_service(
                "TestSvc",
                "\\??\\C:\\Windows\\System32\\drivers\\disk.sys",
                "LocalSystem",
            )
        ]
        results = ServiceRiskAnalyzer._detect_priv_esc(services)
        assert len(results) == 0, (
            f"高权限 + NT 设备路径不应触发提权误报"
        )

    def test_temp_path_still_triggers_priv_esc(self):
        """高权限 + Temp 路径 → 仍应触发提权."""
        services = [
            self._make_service(
                "BadSvc",
                "C:\\Users\\admin\\AppData\\Local\\Temp\\backdoor.exe",
                "LocalSystem",
            )
        ]
        results = ServiceRiskAnalyzer._detect_priv_esc(services)
        assert len(results) >= 1, (
            "高权限 + 可疑路径应仍触发提权检测"
        )


# ============================================================================
# _detect_registry() — 误报修复回归测试
# ============================================================================

class TestDetectRegistryRegressionNoFalsePositive:
    """验证合法系统服务路径不再触发 P1-REGISTRY 误报."""

    def _make_service(self, name, path):
        """构造标准化服务字典."""
        return {
            "name": name,
            "display_name": name,
            "status": "running",
            "start_type": "auto",
            "path": path,
            "user": "LocalSystem",
        }

    def test_systemroot_path_no_registry_false_positive(self):
        """不在已知合法服务中 + %SystemRoot% 路径 → 不应触发注册表风险（路径可信）."""
        services = [
            self._make_service(
                "SomeUnknownSvc",
                "%SystemRoot%\\System32\\some_unknown.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_registry(services)
        assert len(results) == 0, (
            f"不在已知列表但路径可信不应触发注册表风险: "
            f"{[r['detail'] for r in results]}"
        )

    def test_nt_prefix_no_registry_false_positive(self):
        """不在已知合法服务中 + \\??\\ 系统路径 → 不应触发."""
        services = [
            self._make_service(
                "UnknownDriverSvc",
                "\\??\\C:\\Windows\\System32\\drivers\\unknown.sys",
            )
        ]
        results = ServiceRiskAnalyzer._detect_registry(services)
        assert len(results) == 0, (
            f"NT 设备路径 + 可信目录不应触发注册表风险"
        )

    def test_suspicious_path_still_triggers_registry(self):
        """不在已知合法服务中 + Temp 路径 → 仍应触发."""
        services = [
            self._make_service(
                "UnknownBadSvc",
                "C:\\Users\\admin\\AppData\\Local\\Temp\\persist.exe",
            )
        ]
        results = ServiceRiskAnalyzer._detect_registry(services)
        assert len(results) >= 1, (
            "不在已知列表 + 可疑路径应仍触发注册表风险"
        )
