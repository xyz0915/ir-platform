"""AI 分析输入质量评估服务."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from app.services.explainability_service import ExplainabilityService

# 标准/知名端口（排除后为非标准端口）
_STANDARD_PORTS: set[int] = {80, 443, 53, 22, 3389}
# DNS 协议/端口关键词
_DNS_KEYWORDS: list[str] = ["dns", "domain", "53", "named", "dnscache"]


class InputQualityService:
    """对 AI 分析输入上下文做本地规则评估与补充建议生成。"""

    @staticmethod
    def evaluate(tiered_data: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []
        suggestions: list[dict[str, Any]] = []
        score = 100

        host_basic = tiered_data.get("host_basic", {}) or {}
        analysis_result = tiered_data.get("analysis_result", {}) or {}
        timeline_events = (
            (tiered_data.get("timeline_high", []) or [])
            + (tiered_data.get("timeline_medium", []) or [])
            + (tiered_data.get("timeline_low", []) or [])
        )
        # 网络数据：从多个来源收集
        suspicious_connections = InputQualityService._collect_network_data(tiered_data)
        abnormal_processes = (
            (tiered_data.get("abnormal_processes_high", []) or [])
            + (tiered_data.get("abnormal_processes_medium", []) or [])
            + (tiered_data.get("abnormal_processes_low", []) or [])
        )
        ioc_hits = (
            (tiered_data.get("ioc_hits_high", []) or [])
            + (tiered_data.get("ioc_hits_medium", []) or [])
            + (tiered_data.get("ioc_hits_low", []) or [])
        )
        persistence_items = tiered_data.get("persistence_suspicious", []) or []

        if not host_basic.get("hostname") and not host_basic.get("ip_address"):
            score -= 20
            issues.append("缺少主机标识信息，难以确认分析对象。")
            suggestions.append(InputQualityService._suggestion("host_identity", "补充主机标识", "建议补充主机名或 IP 地址，用于确认分析对象。", "high"))

        if not analysis_result.get("risk_level") and not analysis_result.get("summary"):
            score -= 15
            issues.append("缺少本地分析结果摘要，AI 需要从原始异常中自行归纳。")
            suggestions.append(InputQualityService._suggestion("local_summary", "补充本地分析摘要", "建议提供风险等级、风险摘要或本地分析结论。", "high"))

        if len(timeline_events) < 2:
            score -= 15
            issues.append("时间线事件过少，攻击链推断可能不完整。")
            suggestions.append(InputQualityService._suggestion("timeline", "补充时间线", "建议补充关键时间点、事件顺序或系统日志时间线。", "medium"))

        # ── 网络数据内容分析（修复问题①A） ──
        if not suspicious_connections:
            # 完全无网络数据 → 保持原有逻辑
            score -= 10
            issues.append("缺少可疑外连信息，难以判断 C2 或横向行为。")
            suggestions.append(InputQualityService._suggestion("network", "补充网络外连", "建议补充远端 IP/端口、协议和关联进程。", "medium"))
        else:
            public_ips = InputQualityService._count_public_ips(suspicious_connections)
            dns_count = InputQualityService._count_dns_records(suspicious_connections)
            non_std_ports = InputQualityService._count_non_standard_ports(suspicious_connections)

            if public_ips["count"] > 0:
                # 有公网连接 → 网络维度已采集，不再扣分，也不再提示"补网络外连"
                unique_ips = public_ips["unique_ips"]
                ip_list_str = ", ".join(sorted(unique_ips))
                suggestions.append(InputQualityService._suggestion(
                    "network_analysis",
                    "分析已有网络连接",
                    f"已有 {public_ips['count']} 条公网连接记录（{len(unique_ips)} 个唯一目的 IP: {ip_list_str}），建议排查可疑目的地并关联进程。",
                    "medium",
                ))
                if dns_count == 0 and non_std_ports == 0:
                    # 有公网连接但缺乏 DNS/端口协议详情
                    suggestions.append(InputQualityService._suggestion(
                        "network_detail",
                        "建议补充DNS解析记录和端口协议信息",
                        "当前网络连接数据缺少 DNS 解析记录与端口协议详情，建议补充以完善外连画像。",
                        "low",
                    ))
            elif public_ips.get("has_internal_only", False):
                # 只有内网/回环地址
                score -= 5
                issues.append("网络数据已采集但无外连记录，如需排查 C2 建议补公网出口流量。")
                suggestions.append(InputQualityService._suggestion("network", "补充公网出口流量", "当前仅有内网/回环连接，如需排查 C2 通信建议补充公网出口流量。", "medium"))
            else:
                # 有网络数据但无法解析 IP → 当作有数据但质量不够
                score -= 5
                issues.append("网络连接数据存在但无法解析外连信息，需进一步核查。")
                suggestions.append(InputQualityService._suggestion("network", "补充网络外连详情", "当前网络数据无法确认外连目标，建议补充远端 IP/端口详情。", "medium"))

        if not abnormal_processes:
            score -= 10
            issues.append("缺少异常进程信息，执行链分析可能偏弱。")
            suggestions.append(InputQualityService._suggestion("process", "补充异常进程", "建议补充可疑进程名、命令行、父子进程关系。", "medium"))

        if not ioc_hits:
            score -= 10
            issues.append("没有 IOC 命中记录，外部威胁画像佐证较少。")
            suggestions.append(InputQualityService._suggestion("ioc", "补充 IOC 信息", "可补充域名、IP、哈希等 IOC 命中上下文。", "low"))

        if not persistence_items:
            score -= 10
            issues.append("缺少持久化痕迹信息，驻留判断可能不充分。")
            suggestions.append(InputQualityService._suggestion("persistence", "补充持久化痕迹", "建议补充启动项、计划任务、注册表自启等信息。", "low"))

        if score >= 80:
            level = "high"
        elif score >= 55:
            level = "medium"
        else:
            level = "low"

        # 生成 summary：优先用 issues，无 issues 则给正面总结
        if issues:
            summary = "数据覆盖度存在以下不足：" + "；".join(issues[:3])
        elif score >= 80:
            summary = "输入数据覆盖度较高，各维度证据较完整，可供 AI 充分研判。"
        elif score >= 55:
            summary = "输入数据覆盖度中等，部分维度证据偏少，AI 结论可能需结合人工复核。"
        else:
            summary = "输入数据覆盖度偏低，关键维度证据缺失，AI 结论置信度有限，建议补充采集。"
        input_quality = {
            "score": max(0, min(100, score)),
            "level": level,
            "summary": summary,
            "issues": issues,
            "suggestions": suggestions,
        }
        coverage_gaps = ExplainabilityService.build_coverage_gaps(
            tiered_data=tiered_data,
            evidence_items=[],
            input_quality=input_quality,
        )
        miss_risk = {
            "level": "high" if level == "low" else "medium" if coverage_gaps.get("missing_data") or coverage_gaps.get("blind_spots") else "low",
            "summary": "；".join((coverage_gaps.get("missing_data") or []) + (coverage_gaps.get("weak_evidence") or []) + (coverage_gaps.get("blind_spots") or [])) or "当前输入质量较好，但仍建议结合人工复核。",
        }
        evidence_insufficiency = list(dict.fromkeys((coverage_gaps.get("weak_evidence") or []) + (coverage_gaps.get("recommended_collection") or [])))

        return {
            "input_quality": input_quality,
            "input_suggestions": suggestions,
            "coverage_gaps": coverage_gaps,
            "miss_risk": miss_risk,
            "evidence_insufficiency": evidence_insufficiency,
        }

    # ── 网络数据内容分析辅助方法 ──

    @staticmethod
    def _collect_network_data(tiered_data: dict[str, Any]) -> list[dict[str, Any]]:
        """从 tiered_data 中收集所有网络连接数据.

        覆盖：suspicious_connections_*、network_connections、processes 中的网络字段。

        Args:
            tiered_data: 分层数据字典。

        Returns:
            网络连接条目列表。
        """
        connections: list[dict[str, Any]] = []

        # 1. 从 suspicious_connections_* 收集
        for key in ("suspicious_connections_high", "suspicious_connections_medium",
                     "suspicious_connections_low"):
            items = tiered_data.get(key)
            if isinstance(items, list):
                connections.extend(items)

        # 2. 直接 network_connections 字段
        direct = tiered_data.get("network_connections")
        if isinstance(direct, list):
            connections.extend(direct)

        # 3. 从 processes 中提取网络字段（processes 可能含 remote/connection 信息）
        for proc_key in ("abnormal_processes_high", "abnormal_processes_medium",
                         "abnormal_processes_low", "process_list"):
            processes = tiered_data.get(proc_key)
            if not isinstance(processes, list):
                continue
            for p in processes:
                if not isinstance(p, dict):
                    continue
                # 检查进程条目中是否包含网络相关字段
                remote = p.get("remote") or p.get("remote_address") or p.get("connection")
                if remote:
                    connections.append({
                        "remote": str(remote),
                        "protocol": str(p.get("protocol", p.get("proto", ""))),
                        "process": str(p.get("process_name", p.get("name", ""))),
                        "source": "process",
                    })
                # 检查 nested 网络连接
                nested_conns = p.get("network_connections") or p.get("connections")
                if isinstance(nested_conns, list):
                    connections.extend(nested_conns)

        return connections

    @staticmethod
    def _parse_remote(entry: dict[str, Any]) -> tuple[str, str]:
        """从网络连接条目中提取 (ip_address, port).

        Args:
            entry: 网络连接条目（含 remote / remote_address / dst 字段）。

        Returns:
            (ip_str, port_str) 元组。
        """
        remote = (
            entry.get("remote") or entry.get("remote_address")
            or entry.get("dst") or entry.get("destination") or ""
        )
        if not remote:
            return ("", "")
        remote = str(remote).strip()
        # 尝试 "ip:port" 格式
        if ":" in remote:
            # 排除 IPv6 的 [: 模式
            parts = remote.rsplit(":", 1)
            if len(parts) == 2:
                return (parts[0].strip("[]"), parts[1].strip())
        return (remote, "")

    @staticmethod
    def _is_public_ip(ip_str: str) -> bool:
        """判断 IP 字符串是否为公网地址.

        排除：私有地址、回环、未指定、多播地址。

        Args:
            ip_str: IP 地址字符串。

        Returns:
            是公网地址返回 True。
        """
        if not ip_str or not ip_str.strip():
            return False
        ip_str = ip_str.strip().strip("[]")
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                return False
            return True
        except ValueError:
            # 不是合法 IP → 可能是域名
            return False

    @staticmethod
    def _count_public_ips(connections: list[dict[str, Any]]) -> dict[str, Any]:
        """统计网络连接中的公网 IP.

        Args:
            connections: 网络连接条目列表。

        Returns:
            {"count": int, "unique_ips": set[str], "has_internal_only": bool}
        """
        public_ips: set[str] = set()
        internal_ips: set[str] = set()
        total_public: int = 0

        for conn in connections:
            if not isinstance(conn, dict):
                continue
            ip_str, _port = InputQualityService._parse_remote(conn)
            if not ip_str:
                continue
            if InputQualityService._is_public_ip(ip_str):
                public_ips.add(ip_str)
                total_public += 1
            else:
                # 检查是不是合法 IP（内网/回环等）
                try:
                    ipaddress.ip_address(ip_str.strip().strip("[]"))
                    internal_ips.add(ip_str)
                except ValueError:
                    # 不是 IP → 可能是域名，算作潜在公网连接（域名通常指向公网）
                    public_ips.add(ip_str)
                    total_public += 1

        return {
            "count": total_public,
            "unique_ips": public_ips,
            "has_internal_only": len(public_ips) == 0 and len(internal_ips) > 0,
        }

    @staticmethod
    def _count_dns_records(connections: list[dict[str, Any]]) -> int:
        """统计网络连接中疑似 DNS 相关的记录数.

        Args:
            connections: 网络连接条目列表。

        Returns:
            DNS 相关记录数。
        """
        dns_count: int = 0
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            proto = str(conn.get("protocol", "")).lower()
            remote = str(conn.get("remote", conn.get("remote_address", ""))).lower()
            # 端口 53 或协议 dns
            if "53" in proto or "dns" in proto or "domain" in proto:
                dns_count += 1
                continue
            # remote 中包含 DNS 特征
            if any(kw in remote for kw in _DNS_KEYWORDS):
                dns_count += 1
                continue
            # 端口为 53
            _ip, port = InputQualityService._parse_remote(conn)
            if port == "53":
                dns_count += 1
        return dns_count

    @staticmethod
    def _count_non_standard_ports(connections: list[dict[str, Any]]) -> dict[str, Any]:
        """统计非标准端口连接数和端口列表.

        Args:
            connections: 网络连接条目列表。

        Returns:
            {"count": int, "ports": list[str]}
        """
        non_std_ports: set[str] = set()
        count: int = 0
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            _ip, port_str = InputQualityService._parse_remote(conn)
            if not port_str:
                continue
            try:
                port = int(port_str)
            except (ValueError, TypeError):
                continue
            if port not in _STANDARD_PORTS:
                non_std_ports.add(str(port))
                count += 1
        return {"count": count, "ports": sorted(non_std_ports, key=int)}

    @staticmethod
    def _suggestion(suggestion_type: str, title: str, detail: str, priority: str) -> dict[str, Any]:
        return {
            "type": suggestion_type,
            "title": title,
            "detail": detail,
            "priority": priority,
        }
