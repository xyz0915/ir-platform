"""分析编排服务 — 协调各分析模块完成完整分析流程."""

import ipaddress
import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.analysis.profile_builder import ProfileBuilder
from app.analysis.anomaly_detector import AnomalyDetector
from app.analysis.timeline_builder import TimelineBuilder
from app.analysis.ioc_checker import IocChecker
from app.analysis.persistence_finder import PersistenceFinder
from app.analysis.risk_assessor import RiskAssessor
from app.analysis.process_tree_builder import ProcessTreeBuilder
from app.models.analysis import (
    AnalysisResult, HostProfile, AbnormalProcess, SuspiciousConnection,
    SuspiciousStartupItem, PersistenceItem, TimelineEvent, IocHit,
    clear_analysis_by_host,
    NetworkConnection, FileHash, WmiSubscription, RegistryKey,
)
from app.models.host import Host
from app.rules.rule_engine import RuleEngine
from app.services.import_service import ImportService
from app.services.whitelist_service import WhitelistService
from app.services.enrichment_service import (
    get_enrichment_service,
    ThreatIntelQueryError,
    QuotaExceededError,
    UnsupportedIocTypeError,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """分析编排服务."""

    @staticmethod
    def analyze(host_id: int) -> dict:
        """执行完整分析流程.

        Args:
            host_id: 主机 ID.

        Returns:
            分析结果字典.

        Raises:
            ValueError: 主机不存在或数据未导入.
        """
        # 获取主机信息
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError("主机不存在")

        # 读取原始 JSON 数据
        raw_data = ImportService.read_raw_json(host_id)
        if not raw_data:
            raise ValueError("主机尚未导入采集数据")

        logger.info("Starting analysis for host %d", host_id)

        # 1. 清除旧分析结果
        clear_analysis_by_host(host_id)

        # 2. 加载规则
        rules = RuleEngine.load_rules()
        logger.info("Loaded %d rules", len(rules))

        # 3. 构建主机画像
        profile_data = ProfileBuilder.build(raw_data)
        HostProfile.create_or_replace(
            host_id=host_id,
            cpu_info=profile_data["cpu_info"],
            memory_info=profile_data["memory_info"],
            disk_info=profile_data["disk_info"],
            network_info=profile_data["network_info"],
            installed_software=profile_data["installed_software"],
            user_accounts=profile_data["user_accounts"],
            security_products=profile_data["security_products"],
            system_summary=profile_data["system_summary"],
        )
        logger.info("Host profile built")

        # 4. 异常检测（含白名单过滤）
        whitelist_service = WhitelistService()
        abnormal_processes = AnomalyDetector.detect_processes(raw_data, rules, whitelist_service=whitelist_service)
        AbnormalProcess.batch_create(host_id, abnormal_processes)
        logger.info("Detected %d abnormal processes", len(abnormal_processes))

        suspicious_connections = AnomalyDetector.detect_connections(raw_data, rules)
        SuspiciousConnection.batch_create(host_id, suspicious_connections)
        logger.info("Detected %d suspicious connections", len(suspicious_connections))

        suspicious_startup = AnomalyDetector.detect_startup_items(raw_data, rules)
        SuspiciousStartupItem.batch_create(host_id, suspicious_startup)
        logger.info("Detected %d suspicious startup items", len(suspicious_startup))

        # 5. 持久化痕迹分析
        all_persistence = PersistenceFinder.find_all(raw_data)
        assessed_persistence = PersistenceFinder.assess_suspicious(all_persistence, rules)
        PersistenceItem.batch_create(host_id, assessed_persistence)
        logger.info("Found %d persistence items (%d suspicious)",
                    len(assessed_persistence),
                    sum(1 for p in assessed_persistence if p.get("is_suspicious")))

        # 6. IOC 检测
        ioc_rules = [r for r in rules if r.get("category") == "ioc"]
        ioc_hits = IocChecker.check(raw_data, ioc_rules)
        IocHit.batch_create(host_id, ioc_hits)
        logger.info("Found %d IOC hits", len(ioc_hits))

        # 7. 时间线构建
        timeline_events = TimelineBuilder.build(raw_data)
        TimelineEvent.batch_create(host_id, timeline_events)
        logger.info("Built %d timeline events", len(timeline_events))

        # 8. 数据采集增强 — 从 raw_data 提取新表字段并落库
        # P0-1: 网络连接
        net_data = raw_data.get("network_connections", [])
        if isinstance(net_data, list) and net_data:
            NetworkConnection.batch_create(host_id, net_data)
            logger.info("Extracted %d network connections", len(net_data))
        # P0-2: 文件哈希
        fh_data = raw_data.get("file_hashes", [])
        if isinstance(fh_data, list) and fh_data:
            FileHash.batch_create(host_id, fh_data)
            logger.info("Extracted %d file hashes", len(fh_data))
        # P1-3: WMI 订阅
        wmi_data = raw_data.get("wmi_subscriptions", [])
        if isinstance(wmi_data, list) and wmi_data:
            WmiSubscription.batch_create(host_id, wmi_data)
            logger.info("Extracted %d WMI subscriptions", len(wmi_data))
        # P2-5: 注册表键值
        reg_data = raw_data.get("registry_keys", [])
        if isinstance(reg_data, list) and reg_data:
            RegistryKey.batch_create(host_id, reg_data)
            logger.info("Extracted %d registry keys", len(reg_data))

        # 9. 风险评估
        findings = {
            "abnormal_processes": abnormal_processes,
            "suspicious_connections": suspicious_connections,
            "suspicious_startup_items": suspicious_startup,
            "persistence_items": assessed_persistence,
            "ioc_hits": ioc_hits,
            "timeline_events": timeline_events,
        }
        risk_result = RiskAssessor.assess(findings)

        # 10. 保存分析结果
        result = AnalysisResult.create_or_replace(
            host_id=host_id,
            risk_level=risk_result["risk_level"],
            risk_score=risk_result["risk_score"],
            total_findings=risk_result["total_findings"],
            summary=risk_result["summary"],
            details=risk_result["details"],
        )

        # 10. 更新主机状态
        Host.update_status(host_id, status="analyzed")

        logger.info("Analysis completed for host %d: risk=%s, score=%d, findings=%d",
                     host_id, risk_result["risk_level"],
                     risk_result["risk_score"], risk_result["total_findings"])

        return result

    @staticmethod
    def get_analysis(host_id: int) -> Optional[dict]:
        """获取主机的分析结果汇总.

        Args:
            host_id: 主机 ID.

        Returns:
            分析结果字典，不存在时返回 None.
        """
        return AnalysisResult.get_by_host(host_id)

    @staticmethod
    def get_profile(host_id: int) -> Optional[dict]:
        """获取主机画像."""
        return HostProfile.get_by_host(host_id)

    @staticmethod
    def get_timeline(host_id: int, start: Optional[str] = None,
                     end: Optional[str] = None, event_type: Optional[str] = None) -> list:
        """获取时间线事件."""
        return TimelineEvent.list_by_host(host_id, start, end, event_type)

    @staticmethod
    def get_ioc_hits(host_id: int) -> list:
        """获取 IOC 命中列表."""
        return IocHit.list_by_host(host_id)

    @staticmethod
    def get_persistence(host_id: int) -> list:
        """获取持久化痕迹列表."""
        return PersistenceItem.list_by_host(host_id)

    @staticmethod
    def get_suspicious_connections(host_id: int) -> list:
        """获取可疑外连列表."""
        return SuspiciousConnection.list_by_host(host_id)
    @staticmethod
    def enrich_suspicious_connections(host_id: int) -> dict:
        """对主机所有可疑外连的公网 IP 做一键威胁情报检测.

        流程:
          1. 读取该主机全部 ``suspicious_connections`` 行；
          2. 提取 ``remote_address``，用 ``ipaddress`` 校验并过滤私网
             （private/loopback/link-local/multicast/reserved/unspecified），按 IP 去重；
          3. 逐个公网 IP 调 ``EnrichmentService.enrich_ioc(None, "ip", ip)``
             复用既有 provider 落库 ``threat_intel``（保留全历史）；
          4. 将 ``NormalizedIntel`` 的 ``threat_level/risk_score/tags`` 映射写回
             对应 ``suspicious_connections`` 行（按 ``remote_address`` 匹配）；
          5. 返回统计 dict。

        Args:
            host_id: 主机 ID.

        Returns:
            统计 dict::

                {
                    "total": int,            # 可疑外连总行数
                    "public": int,           # 去重后的公网 IP 数（实际检测数）
                    "enriched": int,         # 成功 enrichment 的 IP 数
                    "malicious": int,        # 命中 high（恶意）的 IP 数
                    "suspicious": int,       # 命中 medium（可疑）的 IP 数
                    "skipped_private": int,  # 私网/保留地址被跳过的 IP 数
                    "errors": List[dict],     # 失败 IP 列表 [{"ip", "error"}]
                }
        """
        connections = SuspiciousConnection.list_by_host(host_id)
        total = len(connections)

        # 1) 提取公网 IP、过滤私网、按 IP 去重
        public_ips: dict = {}            # ip(str) -> 出现次数（用于计数）
        skipped_private = 0
        for conn in connections:
            remote = (conn.get("remote_address") or "").strip()
            if not remote:
                continue
            try:
                ip_obj = ipaddress.ip_address(remote)
            except ValueError:
                # 非 IP（如域名、空串）跳过
                continue
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                skipped_private += 1
                continue
            public_ips[remote] = public_ips.get(remote, 0) + 1

        public = len(public_ips)
        enriched = 0
        malicious = 0
        suspicious = 0
        errors: list = []

        # 2) 逐个公网 IP 调用 EnrichmentService（复用 provider 与 threat_intel 落库）
        svc = get_enrichment_service()
        ip_results: dict = {}        # ip -> {threat_level, threat_score, threat_tags}
        for ip in public_ips:
            try:
                record = svc.enrich_ioc(None, "ip", ip)
            except (ThreatIntelQueryError, QuotaExceededError, UnsupportedIocTypeError) as exc:
                errors.append({"ip": ip, "error": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 — 单条失败不影响整体
                errors.append({"ip": ip, "error": f"查询异常: {exc}"})
                continue

            threat_level = record.get("threat_level")
            risk_score = int(record.get("risk_score") or 0)
            tags = record.get("tags") or []
            ip_results[ip] = {
                "threat_level": threat_level,
                "threat_score": risk_score,
                "threat_tags": json.dumps(tags, ensure_ascii=False),
            }
            enriched += 1
            if threat_level == "high":
                malicious += 1
            elif threat_level == "medium":
                suspicious += 1

        # 3) 写回 suspicious_connections（按 remote_address 匹配所有行）
        enriched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_rows: list = []
        for conn in connections:
            remote = (conn.get("remote_address") or "").strip()
            res = ip_results.get(remote)
            if res is None:
                continue
            update_rows.append({
                "id": conn["id"],
                "threat_level": res["threat_level"],
                "threat_score": res["threat_score"],
                "threat_tags": res["threat_tags"],
                "enriched_at": enriched_at,
            })
        if update_rows:
            SuspiciousConnection.update_threat_info(update_rows)

        return {
            "total": total,
            "public": public,
            "enriched": enriched,
            "malicious": malicious,
            "suspicious": suspicious,
            "skipped_private": skipped_private,
            "errors": errors,
        }

    @staticmethod
    def get_abnormal_processes(host_id: int) -> list:
        """获取异常进程列表."""
        return AbnormalProcess.list_by_host(host_id)

    @staticmethod
    def get_startup_items(host_id: int) -> list:
        """获取可疑启动项列表."""
        return SuspiciousStartupItem.list_by_host(host_id)

    @staticmethod
    def get_network_connections(host_id: int) -> list:
        """获取网络连接列表（数据采集增强 P1-2）."""
        return NetworkConnection.list_by_host(host_id)

    @staticmethod
    def get_file_hashes(host_id: int) -> list:
        """获取文件哈希列表（数据采集增强 P1-3）."""
        return FileHash.list_by_host(host_id)

    @staticmethod
    def get_wmi_subscriptions(host_id: int) -> list:
        """获取 WMI 订阅列表（数据采集增强 P1-5）."""
        return WmiSubscription.list_by_host(host_id)

    @staticmethod
    def get_registry_keys(host_id: int) -> list:
        """获取注册表键值列表（数据采集增强 P1-6）."""
        return RegistryKey.list_by_host(host_id)

    @staticmethod
    def get_process_tree(host_id: int) -> dict:
        """获取进程树结构用于可视化.

        Args:
            host_id: 主机 ID.

        Returns:
            进程树字典，用于 ECharts tree series 渲染.
        """
        raw_data = ImportService.read_raw_json(host_id)
        if not raw_data:
            return {"name": "(no data)", "children": []}

        processes = raw_data.get("processes", [])
        if not isinstance(processes, list) or not processes:
            return {"name": "(no process data)", "children": []}

        # 获取异常进程列表
        abnormal_process_list = AbnormalProcess.list_by_host(host_id)

        # 构建 abnormal_pids set 和 pid_to_info map
        abnormal_pids: set = set()
        pid_to_info: dict = {}
        for proc in abnormal_process_list:
            pid = proc.get("pid")
            if pid is not None:
                abnormal_pids.add(pid)
                pid_to_info[pid] = proc

        # 构建进程树
        tree = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        return tree
