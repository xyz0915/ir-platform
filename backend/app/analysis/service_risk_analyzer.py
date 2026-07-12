"""系统服务风险分析器 — 多维度检测安全服务篡改/伪装/提权风险."""

import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any

from app.analysis.service_constants import (
    KNOWN_LEGIT_SERVICES,
    SCORING_WEIGHTS,
    SECURITY_SERVICES,
    SERVICE_NAME_SIMILARITY_THRESHOLD,
    START_TYPE_RISK,
    SUSPICIOUS_PATH_KEYWORDS,
    TRUSTED_PATHS,
)

logger = logging.getLogger(__name__)


class ServiceRiskAnalyzer:
    """系统服务风险分析器 — 所有方法为静态方法."""

    @staticmethod
    def analyze(raw_data: dict, host_id: int) -> dict:
        """对原始采集数据中的系统服务执行多维度风险检测.

        Args:
            raw_data: Agent 采集的原始 JSON 数据.
            host_id: 主机 ID（用于日志上下文）.

        Returns:
            结构化风险分析结果::

                {
                    "services": [ {服务风险详情} ],
                    "aggregate_score": int,
                    "summary": {"total": int, "high_risk_count": int},
                }
        """
        services = ServiceRiskAnalyzer._extract_services(raw_data)
        if not services:
            logger.info("Host %d: no services data available", host_id)
            return {
                "services": [],
                "aggregate_score": 0,
                "summary": {"total": 0, "high_risk_count": 0},
            }

        # 并行执行 4 个检测器
        tamper_results = ServiceRiskAnalyzer._detect_tamper(services)
        shadow_results = ServiceRiskAnalyzer._detect_shadow(services)
        priv_esc_results = ServiceRiskAnalyzer._detect_priv_esc(services)
        registry_results = ServiceRiskAnalyzer._detect_registry(services)

        # 按服务名分组检测结果
        detections_by_name: dict[str, list[dict]] = {}
        for svc in services:
            name = svc.get("name", "")
            detections_by_name[name] = []

        for det in tamper_results:
            name = det.get("service_name", "")
            if name in detections_by_name:
                detections_by_name[name].append(det)

        for det in shadow_results:
            name = det.get("service_name", "")
            if name in detections_by_name:
                detections_by_name[name].append(det)

        for det in priv_esc_results:
            name = det.get("service_name", "")
            if name in detections_by_name:
                detections_by_name[name].append(det)

        for det in registry_results:
            name = det.get("service_name", "")
            if name in detections_by_name:
                detections_by_name[name].append(det)

        # 构建服务风险列表
        enriched_services: list[dict] = []
        for svc in services:
            name = svc.get("name", "")
            svc_detections = detections_by_name.get(name, [])

            risk_score = ServiceRiskAnalyzer._calculate_aggregate_score(
                svc_detections
            )
            severity_label = ServiceRiskAnalyzer._score_to_label(risk_score)

            enriched_services.append({
                "name": svc.get("name", ""),
                "display_name": svc.get("display_name", ""),
                "status": svc.get("status", ""),
                "start_type": svc.get("start_type", ""),
                "path": svc.get("path", ""),
                "user": svc.get("user", ""),
                "risk_score": risk_score,
                "severity_label": severity_label,
                "detections": svc_detections,
            })

        # 计算总体聚合分数
        total_score = 0
        for svc in enriched_services:
            total_score += svc["risk_score"]
        aggregate_score = min(total_score, 100)

        # 统计高风险服务数 (score >= 50)
        high_risk_count = sum(
            1 for s in enriched_services if s["risk_score"] >= 50
        )

        return {
            "services": enriched_services,
            "aggregate_score": aggregate_score,
            "summary": {
                "total": len(enriched_services),
                "high_risk_count": high_risk_count,
            },
        }

    @staticmethod
    def _extract_services(raw_data: dict) -> list[dict]:
        """从 raw_data 中提取并标准化服务列表.

        优先从 ``raw_data.persistence.services`` 取，回退到
        ``raw_data.services``。字段名标准化为 name/display_name/status/
        start_type/path/user。

        Args:
            raw_data: Agent 原始 JSON 数据.

        Returns:
            标准化后的服务列表.
        """
        persistence = raw_data.get("persistence") or {}
        if isinstance(persistence, dict):
            svc_list = persistence.get("services")
            if isinstance(svc_list, list) and svc_list:
                raw_services = svc_list
            else:
                raw_services = raw_data.get("services", [])
        else:
            raw_services = raw_data.get("services", [])

        if not isinstance(raw_services, list):
            return []

        # start_type 整数→文本映射（兼容新版 Agent JSON 整数格式）
        START_TYPE_INT_MAP: dict[int, str] = {
            0: "boot",
            1: "system",
            2: "auto",
            3: "manual",
            4: "disabled",
        }

        normalized: list[dict] = []
        for svc in raw_services:
            if not isinstance(svc, dict):
                continue

            # --- start_type 归一化：整数映射为文本标签 ---
            # 注意：不能用 or 链，因为 0 是合法值（boot）但在 Python 中是 falsy
            raw_start = None
            for key in ("start_type", "startType", "StartType"):
                val = svc.get(key)
                if val is not None:
                    raw_start = val
                    break

            if isinstance(raw_start, int):
                start_type_str = START_TYPE_INT_MAP.get(raw_start, "auto")
            elif raw_start:
                start_type_str = str(raw_start)
            else:
                start_type_str = "auto"

            # --- path 字段：command 作为优先回退（新版 Agent JSON 格式）---
            path_str = str(
                svc.get("path")
                or svc.get("command")
                or svc.get("binary_path")
                or svc.get("ImagePath")
                or svc.get("binaryPath")
                or "",
            )

            # --- status 字段：默认 "unknown" ---
            status_str = str(
                svc.get("status") or svc.get("state") or svc.get("Status") or "unknown",
            )

            # --- user 字段：默认 "N/A" ---
            user_str = str(
                svc.get("user") or svc.get("username") or svc.get("UserName") or svc.get("run_as") or "N/A",
            )

            normalized.append({
                "name": str(svc.get("name") or svc.get("service_name") or svc.get("Name") or ""),
                "display_name": str(svc.get("display_name") or svc.get("displayname") or svc.get("DisplayName") or ""),
                "status": status_str,
                "start_type": start_type_str,
                "path": path_str,
                "user": user_str,
            })
        return normalized

    @staticmethod
    def _detect_tamper(services: list[dict]) -> list[dict]:
        """检测安全服务被篡改（P0-1-TAMPER）.

        检查安全软件服务（SECURITY_SERVICES 白名单内）的状态是否异常：
        - status != "running" → 触发
        - start_type 在 START_TYPE_RISK 中返回高风险的 → 叠加触发

        Args:
            services: 标准化后的服务列表.

        Returns:
            检测结果列表，每项包含 rule_id/rule_name/triggered/severity/weight/detail.
        """
        results: list[dict] = []
        for svc in services:
            name = svc.get("name", "")
            name_lower = name.lower()
            if name_lower not in SECURITY_SERVICES:
                continue

            status = (svc.get("status") or "").lower()
            start_type = (svc.get("start_type") or "").lower()

            triggered = False
            reasons: list[str] = []

            # 检查运行状态
            if status != "running":
                triggered = True
                reasons.append(
                    f"安全服务 {name} 状态为 {status}，预期应为 running"
                )

            # 检查启动类型
            st_risk = START_TYPE_RISK.get(start_type, 0)
            if st_risk > 0:
                triggered = True
                reasons.append(
                    f"安全服务 {name} 启动类型为 {start_type}（风险分值: {st_risk}）"
                )

            results.append({
                "rule_id": "P0-1-TAMPER",
                "rule_name": "安全服务被篡改",
                "triggered": triggered,
                "severity": "critical",
                "weight": SCORING_WEIGHTS["P0-1-TAMPER"],
                "detail": "; ".join(reasons) if reasons else "",
                "service_name": name,
            })
        return results

    @staticmethod
    def _detect_shadow(services: list[dict]) -> list[dict]:
        """检测影子服务 / 名称伪装（P0-2-SHADOW）.

        三个维度：
        - 名称伪装：与 KNOWN_LEGIT_SERVICES 相似度 >= 0.85 且不在已知集合中
        - 路径异常：binary_path 不在 TRUSTED_PATHS 中
        - 可疑路径关键词：路径含 SUSPICIOUS_PATH_KEYWORDS

        Args:
            services: 标准化后的服务列表.

        Returns:
            检测结果列表.
        """
        results: list[dict] = []
        for svc in services:
            name = svc.get("name", "")
            name_lower = name.lower()
            path = svc.get("path", "")

            triggered = False
            reasons: list[str] = []

            # 1. 名称伪装检测
            if name_lower and name_lower not in KNOWN_LEGIT_SERVICES:
                for legit_name in KNOWN_LEGIT_SERVICES:
                    ratio = SequenceMatcher(
                        None, name_lower, legit_name
                    ).ratio()
                    if ratio >= SERVICE_NAME_SIMILARITY_THRESHOLD:
                        triggered = True
                        reasons.append(
                            f"服务名 {name} 与合法服务 {legit_name} 高度相似（{ratio:.2f}），"
                            f"疑为名称伪装"
                        )
                        break

            # 2. 路径异常检测
            if path:
                normalized_path = ServiceRiskAnalyzer._normalize_path(path)
                in_trusted = any(
                    normalized_path.startswith(tp)
                    for tp in TRUSTED_PATHS
                )
                if not in_trusted:
                    triggered = True
                    reasons.append(
                        f"服务 {name} 路径 {path} 不在可信路径中"
                    )

                # 3. 可疑路径关键词
                for keyword in SUSPICIOUS_PATH_KEYWORDS:
                    if keyword in normalized_path:
                        triggered = True
                        reasons.append(
                            f"服务 {name} 路径包含可疑关键词: {keyword}"
                        )
                        break

            if triggered:
                results.append({
                    "rule_id": "P0-2-SHADOW",
                    "rule_name": "影子服务/名称伪装",
                    "triggered": True,
                    "severity": "critical",
                    "weight": SCORING_WEIGHTS["P0-2-SHADOW"],
                    "detail": "; ".join(reasons),
                    "service_name": name,
                })
        return results

    @staticmethod
    def _detect_priv_esc(services: list[dict]) -> list[dict]:
        """检测服务提权风险（P1-PRIVESC）.

        当服务以 LocalSystem 或 NT AUTHORITY\\SYSTEM 权限运行，
        且 binary_path 不位于可信系统目录中时触发。

        Args:
            services: 标准化后的服务列表.

        Returns:
            检测结果列表.
        """
        results: list[dict] = []
        high_priv_users = {"localsystem", "nt authority\\system", "system"}

        for svc in services:
            user = (svc.get("user") or "").lower()
            path = svc.get("path", "")
            name = svc.get("name", "")

            if user not in high_priv_users:
                continue

            if not path:
                continue

            normalized_path = ServiceRiskAnalyzer._normalize_path(path)
            in_trusted = any(
                normalized_path.startswith(tp)
                for tp in TRUSTED_PATHS
            )

            if not in_trusted:
                results.append({
                    "rule_id": "P1-PRIVESC",
                    "rule_name": "服务提权风险",
                    "triggered": True,
                    "severity": "high",
                    "weight": SCORING_WEIGHTS["P1-PRIVESC"],
                    "detail": (
                        f"服务 {name} 以高权限账户 {svc.get('user', '')} 运行，"
                        f"但路径 {path} 不在可信系统目录中"
                    ),
                    "service_name": name,
                })

            # 额外检查：高权限账户 + 可疑路径关键词
            for keyword in SUSPICIOUS_PATH_KEYWORDS:
                if keyword in normalized_path:
                    results.append({
                        "rule_id": "P1-PRIVESC",
                        "rule_name": "服务提权风险",
                        "triggered": True,
                        "severity": "high",
                        "weight": SCORING_WEIGHTS["P1-PRIVESC"],
                        "detail": (
                            f"服务 {name} 以高权限账户 {svc.get('user', '')} 运行，"
                            f"且路径包含可疑关键词: {keyword}"
                        ),
                        "service_name": name,
                    })
                    break

        return results

    @staticmethod
    def _detect_registry(services: list[dict]) -> list[dict]:
        """检测注册表相关服务风险（P1-REGISTRY）.

        检查服务是否具有注册表持久化特征：
        - 服务名与注册表相关的已知伪装模式
        - 路径异常且不在已知合法服务中的服务

        Args:
            services: 标准化后的服务列表.

        Returns:
            检测结果列表.
        """
        results: list[dict] = []
        for svc in services:
            name = svc.get("name", "")
            name_lower = name.lower()
            path = svc.get("path", "")

            if not path:
                continue

            normalized_path = ServiceRiskAnalyzer._normalize_path(path)
            in_trusted = any(
                normalized_path.startswith(tp)
                for tp in TRUSTED_PATHS
            )

            # 不在可信路径中且不在已知合法服务列表中
            if not in_trusted and name_lower not in KNOWN_LEGIT_SERVICES:
                # 检查是否有注册表相关的可疑特征
                has_suspicious_keyword = any(
                    kw in normalized_path for kw in SUSPICIOUS_PATH_KEYWORDS
                )
                if has_suspicious_keyword:
                    results.append({
                        "rule_id": "P1-REGISTRY",
                        "rule_name": "注册表关联风险",
                        "triggered": True,
                        "severity": "medium",
                        "weight": SCORING_WEIGHTS["P1-REGISTRY"],
                        "detail": (
                            f"服务 {name} 路径 {path} 不在可信目录且路径包含可疑关键词，"
                            f"可能涉及注册表持久化"
                        ),
                        "service_name": name,
                    })

        return results

    @staticmethod
    def _calc_edit_distance(a: str, b: str) -> float:
        """计算两个字符串的编辑距离相似度.

        Args:
            a: 第一个字符串.
            b: 第二个字符串.

        Returns:
            0.0-1.0 之间的相似度.
        """
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    #: Windows 系统根目录的标准展开目标
    _WINDOWS_ROOT: str = "C:\\Windows"

    #: 环境变量 → 实际路径映射（小写键，值保持标准大小写以便 startswith 匹配）
    _ENV_VAR_MAP: dict[str, str] = {
        'systemroot': 'C:\\Windows',
        'windir': 'C:\\Windows',
        'programdata': 'C:\\ProgramData',
        'programfiles': 'C:\\Program Files',
        'programfiles(x86)': 'C:\\Program Files (x86)',
    }

    @staticmethod
    def _normalize_path(path: str) -> str:
        """规范化路径字符串，展开 Windows 系统路径别名.

        处理以下 Windows 路径别名（大小写不敏感）：

        - ``\\SystemRoot\\`` → ``C:\\Windows\\``
        - ``%SystemRoot%`` → ``C:\\Windows\\``
        - ``%windir%`` → ``C:\\Windows\\``
        - ``%ProgramData%`` → ``C:\\ProgramData\\``
        - ``%ProgramFiles%`` → ``C:\\Program Files\\``
        - ``%ProgramFiles(x86)%`` → ``C:\\Program Files (x86)\\``
        - 相对 ``System32\\...`` / ``SysWOW64\\...`` → 补全 ``C:\\Windows\\``
        - NT 设备路径 ``\\??\\`` 前缀剥离

        Args:
            path: 原始路径字符串，可含命令行参数.

        Returns:
            展开别名后小写的规范化路径.
        """
        # 0. 去除首尾空白和引号
        path = path.strip().strip('"').strip("'")
        if not path:
            return path

        # 1. NT 设备路径 \??\ 前缀剥离（必须在别名展开之前，否则正则无法匹配）
        if path.startswith('\\??\\'):
            path = path[4:]
            # NT 前缀后可能残留引号（如 \??\"%SystemRoot%...）
            path = path.strip('"').strip("'")

        # 2. 展开 %ENV_VAR% 环境变量（systemroot / windir / programdata / programfiles 等）
        m = re.match(r'^%([^%]+)%[\\/]?(.*)$', path, re.IGNORECASE)
        if m:
            var_name = m.group(1).lower()
            rest = m.group(2)
            resolved = ServiceRiskAnalyzer._ENV_VAR_MAP.get(var_name)
            if resolved:
                path = resolved + '\\' + rest

        # 2. 展开 \SystemRoot\... 前缀
        m = re.match(r'^\\SystemRoot[\\/](.*)$', path, re.IGNORECASE)
        if m:
            path = ServiceRiskAnalyzer._WINDOWS_ROOT + '\\' + m.group(1)

        # 3. 展开 SystemRoot\... 前缀（无前导反斜杠，在步骤2之后执行）
        m = re.match(r'^SystemRoot[\\/](.*)$', path, re.IGNORECASE)
        if m:
            path = ServiceRiskAnalyzer._WINDOWS_ROOT + '\\' + m.group(1)

        # 4. 相对 System32\... / SysWOW64\... 补全 C:\Windows\ 前缀
        if re.match(r'^system32[\\/]', path, re.IGNORECASE):
            path = ServiceRiskAnalyzer._WINDOWS_ROOT + '\\' + path
        elif re.match(r'^syswow64[\\/]', path, re.IGNORECASE):
            path = ServiceRiskAnalyzer._WINDOWS_ROOT + '\\' + path

        return os.path.normpath(path).lower()

    @staticmethod
    def _calculate_aggregate_score(detections: list[dict]) -> int:
        """根据触发检测规则计算单个服务的聚合风险分数.

        累加触发的检测规则权重，上限 100。

        Args:
            detections: 检测结果列表.

        Returns:
            0-100 的分数.
        """
        total = sum(
            d["weight"] for d in detections if d.get("triggered")
        )
        return min(total, 100)

    @staticmethod
    def _score_to_label(score: int) -> str:
        """将分数映射为严重等级标签.

        Args:
            score: 0-100 的分数.

        Returns:
            critical / high / medium / low.
        """
        if score >= 70:
            return "critical"
        elif score >= 50:
            return "high"
        elif score >= 25:
            return "medium"
        return "low"
