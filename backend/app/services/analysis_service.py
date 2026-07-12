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
    def _inject_exe_signatures(raw_data: dict) -> None:
        """将 file_hashes 的哈希/签名信息按 path JOIN 注入进程 dict（T02）.

        纯内存操作：遍历 raw_data["file_hashes"] 构建 ``file_path(小写) -> {sha256,
        is_signed, signer}`` 映射，再为 raw_data["processes"] 中 path 命中的进程注入
        ``exe_sha256`` / ``exe_is_signed`` / ``exe_signer`` 三个字段。
        无对应 file_hash 的进程字段保持缺失（None），下游规则据此优雅降级。

        Args:
            raw_data: Agent 原始 JSON（原地修改 processes 列表中的 dict）。
        """
        if not isinstance(raw_data, dict):
            return
        file_hashes = raw_data.get("file_hashes")
        if not isinstance(file_hashes, list):
            return

        # 构建 path -> 哈希信息 映射（小写归一，兼容 / 与 \\ 分隔符）
        hash_by_path: dict = {}
        for fh in file_hashes:
            if not isinstance(fh, dict):
                continue
            fp = fh.get("file_path") or fh.get("path")
            if not fp:
                continue
            key = str(fp).strip().lower().replace("/", "\\")
            hash_by_path[key] = {
                "sha256": fh.get("sha256") or fh.get("hash"),
                "is_signed": fh.get("is_signed"),
                "signer": fh.get("signer"),
            }

        if not hash_by_path:
            return

        processes = raw_data.get("processes")
        if not isinstance(processes, list):
            return
        for proc in processes:
            if not isinstance(proc, dict):
                continue
            ppath = proc.get("path")
            if not ppath:
                continue
            key = str(ppath).strip().lower().replace("/", "\\")
            info = hash_by_path.get(key)
            if not info:
                continue
            proc["exe_sha256"] = info["sha256"]
            proc["exe_is_signed"] = info["is_signed"]
            proc["exe_signer"] = info["signer"]

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
        # T02：进程 exe 哈希/签名 JOIN 注入 —— 按 process.path 关联已采集的
        # file_hashes，注入 exe_sha256 / exe_is_signed / exe_signer（纯内存 JOIN，
        # 不依赖 DB 时序；无对应 file_hash 时字段为 None 不报错）。供
        # malicious_hash_process（T03 动态 IOC 合并）与 unsigned_executable（T05）使用。
        AnalysisService._inject_exe_signatures(raw_data)
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
        timeline_events = TimelineBuilder.build(raw_data, ioc_hits=ioc_hits)
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

        # 8.6 文件哈希情报匹配（TI_malware_hash：list 规则 field=file_hash，动态并入 iocs.hash）
        # 把已落库的 FileHash 维度作为 data_items 送入 RuleEngine.evaluate，
        # 使 TI_malware_hash 规则能够命中（此前 FileHash 未进入评估输入，该规则永不执行）。
        # 注意：此处仅「追加」hash 类命中到 ioc_hits，绝不使用 IocHit.batch_create
        # （其会 DELETE 整主机 ioc_hits，破坏 step 6 已写入的常规 IOC 命中）。
        hash_rules = [
            r for r in rules
            if r.get("rule_type") == "list"
            and (r.get("condition") or {}).get("field") == "file_hash"
        ]
        if hash_rules:
            fh_rows = FileHash.list_by_host(host_id) or []
            fh_items = [
                {
                    "file_hash": (r.get("sha256") or r.get("hash") or ""),
                    "file_name": r.get("file_name"),
                    "file_path": r.get("file_path"),
                }
                for r in fh_rows
                if (r.get("sha256") or r.get("hash"))
            ]
            if fh_items:
                hash_matches = RuleEngine.evaluate(
                    fh_items, hash_rules, global_context={"host_id": host_id}
                )
                if hash_matches:
                    IocHit.append(
                        host_id,
                        [
                            {
                                "ioc_type": "hash",
                                "ioc_value": m["item"].get("file_hash"),
                                "matched_in": m["rule_name"],
                                "context": m["reason"],
                                "severity": m["severity"],
                            }
                            for m in hash_matches
                        ],
                    )
                    logger.info("Detected %d file-hash (TI_malware_hash) matches", len(hash_matches))

        # 8.5 攻击链关联检测（任务①）：主机级跨维度顺序匹配
        # 此时各维度取证数据已落库，_build_host_events 可按 host_id 下钻聚合。
        # 命中强制 severity=critical，reason 含攻击链步骤明细（见 rule_engine._match_attack_chain）。
        attack_chain_rules = [r for r in rules if r.get("rule_type") == "attack_chain"]
        attack_chain_matches = []
        if attack_chain_rules:
            attack_chain_matches = RuleEngine.evaluate(
                [], attack_chain_rules, global_context={"host_id": host_id}
            )
            logger.info("Detected %d attack chain matches", len(attack_chain_matches))

        # 9. 风险评估
        findings = {
            "abnormal_processes": abnormal_processes,
            "suspicious_connections": suspicious_connections,
            "suspicious_startup_items": suspicious_startup,
            "persistence_items": assessed_persistence,
            "ioc_hits": ioc_hits,
            "timeline_events": timeline_events,
            "attack_chains": attack_chain_matches,
        }
        risk_result = RiskAssessor.assess(findings)
        # 攻击链关联单独记录到详情（不影响既有风险分数/等级，避免影响历史评估口径）
        if attack_chain_matches:
            risk_result.setdefault("details", {})["attack_chains"] = [
                {
                    "rule_name": m.get("rule_name", ""),
                    "severity": m.get("severity"),
                    "reason": m.get("reason", ""),
                    "steps": m.get("item", {}).get("attack_chain_steps", []),
                }
                for m in attack_chain_matches
            ]

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
                     end: Optional[str] = None, event_type: Optional[str] = None,
                     severities: Optional[str] = None, event_types: Optional[str] = None,
                     ioc_hit: Optional[bool] = None) -> list:
        """获取时间线事件（支持多维度过滤）."""
        return TimelineEvent.list_by_host(
            host_id, start, end, event_type,
            severities=severities, event_types=event_types, ioc_hit=ioc_hit,
        )

    @staticmethod
    def get_timeline_stats(host_id: int) -> dict:
        """获取时间线事件统计摘要."""
        return TimelineEvent.get_stats(host_id)

    @staticmethod
    def update_timeline_event(event_id: int, data: dict) -> dict:
        """更新时间线事件处置状态（V3-2）."""
        return TimelineEvent.update_status(event_id, data)

    @staticmethod
    def compare_timelines(host_ids: list) -> dict:
        """多主机时间线叠加对比（V3-4）.

        Args:
            host_ids: 主机 ID 列表.

        Returns:
            含 hosts 列表和 timeRange 的对比数据字典.
        """
        palette = ["#409EFF", "#E6A23C", "#67C23A", "#F56C6C", "#9B59B6"]
        hosts_data: list = []
        all_timestamps: list = []

        for idx, hid in enumerate(host_ids):
            host = Host.get_by_id(hid)
            hostname = host.get("hostname", f"Host-{hid}") if host else f"Host-{hid}"
            events = TimelineEvent.list_by_host(hid)
            for e in events:
                ts = e.get("timestamp", "")
                if ts:
                    all_timestamps.append(ts)
            hosts_data.append({
                "host_id": hid,
                "hostname": hostname,
                "color": palette[idx % len(palette)],
                "events": events,
            })

        # 计算时间范围
        time_range: dict = {"start": None, "end": None}
        if all_timestamps:
            all_timestamps.sort()
            time_range["start"] = all_timestamps[0]
            time_range["end"] = all_timestamps[-1]

        return {"hosts": hosts_data, "timeRange": time_range}

    @staticmethod
    def export_timeline_csv(host_id: int, start: Optional[str] = None,
                            end: Optional[str] = None, event_types: Optional[str] = None,
                            severity: Optional[str] = None) -> tuple:
        """导出时间线为 CSV 格式（V3-5）.

        Returns:
            (csv_content: str, filename: str) 用于 StreamingResponse.
        """
        import csv as csv_mod
        import io

        events = TimelineEvent.list_by_host(
            host_id, start=start, end=end,
            event_types=event_types, severities=severity,
        )

        output = io.StringIO()
        writer = csv_mod.writer(output)
        writer.writerow([
            "ID", "Timestamp", "Event Type", "Source", "Description",
            "Severity", "Kill Chain Stage", "MITRE Technique ID",
            "Status", "IOC Hit ID",
        ])

        for e in events:
            writer.writerow([
                e.get("id", ""),
                e.get("timestamp", ""),
                e.get("event_type", ""),
                e.get("source", ""),
                e.get("description", ""),
                e.get("severity", ""),
                e.get("kill_chain_stage", ""),
                e.get("mitre_technique_id", ""),
                e.get("status", ""),
                e.get("ioc_hit_id", ""),
            ])

        csv_content = output.getvalue()
        output.close()
        host = Host.get_by_id(host_id)
        hostname = host.get("hostname", f"host-{host_id}") if host else f"host-{host_id}"
        filename = f"timeline_{hostname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return csv_content, filename

    @staticmethod
    def export_timeline_pdf(host_id: int, start: Optional[str] = None,
                            end: Optional[str] = None) -> bytes:
        """导出时间线为 PDF 报告（V3-5）.

        复用 PdfExportService 生成文字+表格形式的 PDF 时间线报告.
        """
        try:
            from app.services.pdf_export_service import PdfExportService
            events = TimelineEvent.list_by_host(host_id, start=start, end=end)
            host = Host.get_by_id(host_id)
            hostname = host.get("hostname", f"Host-{host_id}") if host else f"Host-{host_id}"
            return PdfExportService.export_timeline_report(hostname, events)
        except ImportError:
            # 降级：生成简单文本形式的 PDF
            import io
            events = TimelineEvent.list_by_host(host_id, start=start, end=end)
            text_buf = io.StringIO()
            text_buf.write("Timeline Events Report\n")
            text_buf.write("=" * 60 + "\n\n")
            for e in events:
                text_buf.write(f"[{e.get('timestamp', '')}] {e.get('event_type', '')} - {e.get('description', '')}\n")
            return text_buf.getvalue().encode("utf-8")

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
    def enrich_network_connections(host_id: int) -> dict:
        """对主机所有网络连接的公网 IP 做一键威胁情报检测."""
        connections = NetworkConnection.list_by_host(host_id)
        total = len(connections)
        public_ips: dict = {}
        skipped_private = 0
        for conn in connections:
            remote = (conn.get("remote_addr") or "").strip()
            if not remote:
                continue
            try:
                ip_obj = ipaddress.ip_address(remote)
            except ValueError:
                continue
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
                skipped_private += 1
                continue
            public_ips[remote] = public_ips.get(remote, 0) + 1

        public = len(public_ips)
        enriched = 0
        malicious = 0
        suspicious = 0
        errors: list = []
        svc = get_enrichment_service()
        ip_results: dict = {}
        for ip in public_ips:
            try:
                record = svc.enrich_ioc(None, "ip", ip)
            except (ThreatIntelQueryError, QuotaExceededError, UnsupportedIocTypeError) as exc:
                errors.append({"ip": ip, "error": str(exc)})
                continue
            except Exception as exc:
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

        enriched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_rows: list = []
        for conn in connections:
            remote = (conn.get("remote_addr") or "").strip()
            res = ip_results.get(remote)
            if res is None:
                continue
            update_rows.append({"id": conn["id"], "threat_level": res["threat_level"], "threat_score": res["threat_score"], "threat_tags": res["threat_tags"], "enriched_at": enriched_at})
        if update_rows:
            NetworkConnection.update_threat_info(update_rows)
        return {"total": total, "public": public, "enriched": enriched, "malicious": malicious, "suspicious": suspicious, "skipped_private": skipped_private, "errors": errors}

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
    def get_process_tree(host_id: int, enrich: bool = False) -> dict:
        """获取进程树结构用于可视化.

        Args:
            host_id: 主机 ID.
            enrich: 是否返回增强字段（severity/parent_name/connections/...）。
                默认 False → 响应与历史版本逐字段一致，旧前端（ProcessTreeChart）可继续工作。

        Returns:
            进程树字典，用于 ECharts tree series 渲染（enrich=True 时增量追加增强字段）.
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

        # 构建进程树（enrich 缺省时行为与历史一致）
        tree = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info, enrich=enrich)
        return tree
