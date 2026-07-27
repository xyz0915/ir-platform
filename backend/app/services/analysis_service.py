"""分析编排服务 — 协调各分析模块完成完整分析流程."""

import concurrent.futures
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
    WebShell, MemoryShell,
)
from app.models.host import Host
from app.rules.rule_engine import RuleEngine
from app.services.import_service import ImportService
from app.services.whitelist_service import WhitelistService
from app.analysis.process_event_consumer import ProcessEventConsumer
from app.services.enrichment_service import (
    get_enrichment_service,
    ThreatIntelQueryError,
    QuotaExceededError,
    UnsupportedIocTypeError,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """分析编排服务."""

    # 双路检测降级开关：关闭后跳过语义检索分支（P2）
    _ENABLE_SEMANTIC_DETECTION: bool = True

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

    # SQLite INTEGER 上限 (2^63 - 1)
    _SQLITE_MAX_INT: int = 9223372036854775807

    @staticmethod
    def _sanitize_ints(data: Any, max_val: int = None) -> int:
        """递归裁剪超出 SQLite INTEGER 上限的整数字段，防止 DB batch_create 失败。

        @deprecated 建议移到 import_service 层处理

        Args:
            data: 待处理的字典/列表/值（原地修改）。
            max_val: 上限值，默认使用 _SQLITE_MAX_INT。

        Returns:
            被裁剪的字段数。
        """
        if max_val is None:
            max_val = AnalysisService._SQLITE_MAX_INT
        fixed = 0

        if isinstance(data, dict):
            for key, val in list(data.items()):
                if isinstance(val, int) and val > max_val:
                    data[key] = max_val
                    fixed += 1
                    logger.warning(
                        "Clipped oversized int in field=%s: old=%d → new=%d",
                        key, val, max_val,
                    )
                elif isinstance(val, (dict, list)):
                    fixed += AnalysisService._sanitize_ints(val, max_val)
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    fixed += AnalysisService._sanitize_ints(item, max_val)
        return fixed

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

        # 2. 加载规则（优先使用激活策略）
        from app.models.policy import DetectionPolicy
        active_policy = DetectionPolicy.get_active()
        if active_policy and active_policy.get("rule_ids"):
            rules = RuleEngine.load_rules_by_ids(active_policy["rule_ids"])
            # 过滤掉行为引擎规则（仅 ServiceRiskAnalyzer 使用）
            rules = [r for r in rules if r.get("engine_type") != "behavior_engine"]
            policy_name = active_policy.get("name", "未命名")
            logger.info("Using active policy '%s': %d rules", policy_name, len(rules))
        else:
            rules = RuleEngine.load_rules()
            # 过滤掉行为引擎规则（仅 ServiceRiskAnalyzer 使用）
            rules = [r for r in rules if r.get("engine_type") != "behavior_engine"]
            logger.warning("No active policy — fallback to all enabled rules (%d rules)", len(rules))

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
        # 裁剪超出 SQLite INTEGER 上限的字段（如异常 PID 值）—— 兜底防线
        AnalysisService._sanitize_ints(raw_data)

        # ── Phase 1: 并行检测（仅计算，不写库） ──
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_processes = executor.submit(
                AnomalyDetector.detect_processes, raw_data, rules,
                whitelist_service=whitelist_service,
            )
            future_connections = executor.submit(
                AnomalyDetector.detect_connections, raw_data, rules,
            )
            future_startup = executor.submit(
                AnomalyDetector.detect_startup_items, raw_data, rules,
            )
            future_registry = executor.submit(
                lambda: raw_data.get("registry_keys", []),
            )

            # as_completed 收集结果
            results: dict[str, Any] = {}
            for future in concurrent.futures.as_completed([
                future_processes, future_connections,
                future_startup, future_registry,
            ]):
                if future == future_processes:
                    results["processes"] = future.result()
                elif future == future_connections:
                    results["connections"] = future.result()
                elif future == future_startup:
                    results["startup"] = future.result()
                elif future == future_registry:
                    results["registry"] = future.result()

            abnormal_processes = results.get("processes", [])
            suspicious_connections = results.get("connections", [])
            suspicious_startup = results.get("startup", [])
            registry_keys = results.get("registry", [])

        # ── Phase 2: 串行写库（保持原顺序） ──
        AbnormalProcess.batch_create(host_id, abnormal_processes)
        logger.info("Detected %d abnormal processes", len(abnormal_processes))

        SuspiciousConnection.batch_create(host_id, suspicious_connections)
        logger.info("Detected %d suspicious connections", len(suspicious_connections))

        SuspiciousStartupItem.batch_create(host_id, suspicious_startup)
        logger.info("Detected %d suspicious startup items", len(suspicious_startup))

        if isinstance(registry_keys, list) and registry_keys:
            for item in (registry_keys or []):
                item["source_timestamp"] = (item.get("last_write_time") or item.get("collected_at"))
            RegistryKey.batch_create(host_id, registry_keys)
            logger.info("Extracted %d registry keys", len(registry_keys))

        # 5. 持久化痕迹分析
        all_persistence = PersistenceFinder.find_all(raw_data)
        assessed_persistence = PersistenceFinder.assess_suspicious(all_persistence, rules)
        PersistenceItem.batch_create(host_id, assessed_persistence)
        logger.info("Found %d persistence items (%d suspicious)",
                    len(assessed_persistence),
                    sum(1 for p in assessed_persistence if p.get("is_suspicious")))

        # 5.5 系统服务风险检测
        try:
            from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer
            service_risks = ServiceRiskAnalyzer.analyze(raw_data, host_id)
            logger.info("Service risk analysis: %d services, %d high-risk",
                        service_risks["summary"]["total"],
                        service_risks["summary"]["high_risk_count"])
        except Exception as exc:
            logger.warning("服务风险检测失败: %s", exc)
            service_risks = {"services": [], "aggregate_score": 0, "summary": {"total": 0, "high_risk_count": 0}}

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
            for item in net_data:
                item["source_timestamp"] = (item.get("timestamp") or item.get("collected_at"))
            NetworkConnection.batch_create(host_id, net_data)
            logger.info("Extracted %d network connections", len(net_data))
        # P0-2: 文件哈希
        fh_data = raw_data.get("file_hashes", [])
        if isinstance(fh_data, list) and fh_data:
            for item in fh_data:
                item["source_timestamp"] = (item.get("timestamp") or item.get("collected_at"))
            FileHash.batch_create(host_id, fh_data)
            logger.info("Extracted %d file hashes", len(fh_data))
        # P1-3: WMI 订阅
        wmi_data = raw_data.get("wmi_subscriptions", [])
        if isinstance(wmi_data, list) and wmi_data:
            for item in wmi_data:
                item["source_timestamp"] = (item.get("timestamp") or item.get("collected_at"))
            WmiSubscription.batch_create(host_id, wmi_data)
            logger.info("Extracted %d WMI subscriptions", len(wmi_data))

        # 8.6 文件哈希情报匹配（TI_malware_hash：list 规则 field=file_hash，动态并入 iocs.hash）
        # 把已落库的 FileHash 维度作为 data_items 送入 RuleEngine.evaluate，
        # 使 TI_malware_hash 规则能够命中（此前 FileHash 未进入评估输入，该规则永不执行）。
        # 注意：此处仅「追加」hash 类命中到 ioc_hits，绝不使用 IocHit.batch_create
        # （其会 DELETE 整主机 ioc_hits，破坏 step 6 已写入的常规 IOC 命中）。
        hash_rules = [
            r for r in rules
            if r.get("rule_type") == "list"
            and isinstance(r.get("condition"), dict)
            and r["condition"].get("field") == "file_hash"
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

        # ── Phase 1 双路检测 ──
        knowledge_hits: list[dict] = []
        if AnalysisService._ENABLE_SEMANTIC_DETECTION:
            try:
                from app.services.knowledge_retriever import KnowledgeRetriever, _build_dim_query

                tiered = AnalysisService._build_tiered_data(raw_data)
                # 动态构建查询文本，替代硬编码
                dim_parts: list[str] = []
                for dim in ("process", "connection", "webshell_ms"):
                    q = _build_dim_query(dim, raw_data)
                    if q:
                        dim_parts.append(q)
                dim_summary = " ".join(dim_parts) if dim_parts else "unknown"
                # 传入 _raw_data 供三维并行检索使用
                hits = KnowledgeRetriever.retrieve(
                    {"host_basic": tiered.get("host_basic", {}),
                     "analysis_result": {"summary": dim_summary[:512]},
                     "abnormal_processes_high": tiered.get("abnormal_processes_high", []),
                     "suspicious_connections_high": tiered.get("suspicious_connections_high", []),
                     "webshell_items": tiered.get("webshell_items", []),
                     "memory_shell_items": tiered.get("memory_shell_items", []),
                     "persistence_items": tiered.get("persistence_items", []),
                     "_raw_data": raw_data},
                    limit=10, structured=True)
                if hits:
                    knowledge_hits = AnalysisService._cross_validate(
                        abnormal_processes, hits,
                        suspicious_connections=suspicious_connections,
                        webshell_hits=[],
                        memory_shell_hits=[],
                        persistence_items=assessed_persistence,
                    )
                    # 过滤：只保留 score >= 0.75 或 confidence 为 high/medium 的命中
                    knowledge_hits = [
                        h for h in knowledge_hits
                        if (h.get("score") or 0) >= 0.75 or h.get("confidence") in ("high", "medium")
                    ]
                logger.info("Dual-path: %d hits, %d after xval", len(hits), len(knowledge_hits))
            except Exception as exc:
                logger.warning("RAG-DEBUG-EXC: %s", exc, exc_info=True)
                logger.warning("双路语义检索失败（不影响主流程）: %s", exc, exc_info=True)

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
            "knowledge_hits": knowledge_hits,
            "service_risks": service_risks,
        }
        risk_result = RiskAssessor.assess(findings)

        # ── 分析结果同步到实时告警 ──
        try:
            from app.services.alert_engine import AlertEngine
            from app.services.alert_ws import alert_ws_manager
            from app.models.alert import Alert
            _alert_engine = AlertEngine(ws_manager=alert_ws_manager)
            alert_count = 0

            def _sync_items(items, label, detail_field=None, proc_field=None):
                """通用告警同步辅助."""
                c = 0
                for item in (items or []):
                    sev = item.get("severity", "")
                    if sev not in ("critical", "high"):
                        continue
                    aid, is_new = Alert.create_or_aggregate(
                        host_id=host_id,
                        rule_name=item.get("rule_name", "ANALYSIS-HIGH"),
                        severity=sev,
                        title=item.get("reason", "") or f"[{label}] {item.get(proc_field or 'process_name', '')}",
                        detail=str(item.get(detail_field or "command_line", ""))[:500],
                        source_pid=item.get("pid"),
                        source_process=item.get(proc_field or "process_name"),
                        source_path=item.get("process_path"),
                        rule_label=label,
                    )
                    if aid:
                        c += 1
                return c

            alert_count += _sync_items(abnormal_processes, "分析发现-高风险",
                                       detail_field="command_line")
            alert_count += _sync_items(suspicious_connections, "分析发现-可疑外连",
                                       detail_field="remote_address",
                                       proc_field="process_name")
            alert_count += _sync_items(suspicious_startup_items, "分析发现-可疑启动项",
                                       detail_field="item_path",
                                       proc_field="item_name")
            # WebSocket 广播新告警
            if alert_count:
                import asyncio
                for item in (abnormal_processes or [])[:5]:
                    sev = item.get("severity", "")
                    if sev in ("critical", "high"):
                        from app.models.alert import Alert as _A
                        ad = _A.get_by_id(
                            _A.create_or_aggregate(
                                host_id=host_id, rule_name=item.get("rule_name", ""),
                                severity=sev, title="", detail="")[0]
                        )
                        if ad:
                            asyncio.create_task(alert_ws_manager.broadcast(
                                {"type": "new_alert", "alert": ad}
                            ))
                logger.info("Synced %d high-risk findings to alert center", alert_count)
        except Exception as exc:
            logger.warning("分析结果同步告警失败（不影响主流程）: %s", exc)
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

        # 8.7 融合检测（WebShell 文件型 + 内存码 + 统一关联引擎，A §三/§五）
        # 仅新增分支：既有 detect_processes/detect_connections 调用链完全保留（§三.2）。
        webshell_hits = AnomalyDetector.detect_webshells(raw_data, rules)
        if webshell_hits:
            WebShell.batch_create(host_id, webshell_hits)
            logger.info("Detected %d webshells", len(webshell_hits))

        memory_shell_hits = AnomalyDetector.detect_memory_shells(raw_data, rules)
        if memory_shell_hits:
            MemoryShell.batch_create(host_id, memory_shell_hits)
            logger.info("Detected %d memory shells", len(memory_shell_hits))

        # 事件流（B，已建 ProcessEventConsumer）：与快照并行，激活 P2 #3/#5/#6
        event_hits = ProcessEventConsumer.evaluate(
            host_id, rules, raw_data.get("processes")
        )

        # 统一关联引擎（合并 A correlate_webshell_memory + B 链路评分 / ancestor_map 回溯）
        incidents = AnomalyDetector.correlate_incident(
            raw_data,
            webshell_hits,
            memory_shell_hits,
            abnormal_processes,
            event_hits,
            suspicious_connections=suspicious_connections,
        )
        if incidents:
            # 聚合：同类别 single_alert 多条 → 聚合为 1 条摘要（P0 噪音过滤）
            aggregated = AnalysisService._aggregate_incidents(incidents)
            risk_result.setdefault("details", {})["fusion_incidents"] = aggregated
            logger.info("Correlated %d incident(s)/alert(s)", len(incidents))

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
    def _aggregate_incidents(incidents: list) -> list:
        """聚合同一类别的 single_alert，减少噪音（P0 优化）.

        - 多信号 incident 保持原样不聚合
        - 同 type 的 single_alert 聚合为 1 条摘要
        - 保留 top-3 高置信度单条明细在 details 中
        """
        if len(incidents) <= 3:
            return incidents

        # 分开 incident 和 single_alert
        real_incidents: list[dict] = []
        alerts_by_type: dict[str, list[dict]] = {}
        for inc in incidents:
            if inc.get("kind") == "incident" or "+" in inc.get("type", ""):
                real_incidents.append(inc)
            else:
                t = inc.get("type", "unknown")
                alerts_by_type.setdefault(t, []).append(inc)

        # 构建 output
        output: list[dict] = list(real_incidents)
        sev_rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        for atype, alerts in alerts_by_type.items():
            if len(alerts) <= 2:
                output.extend(alerts)
                continue
            # 聚合：取 top-3 按 confidence 降序
            top3 = sorted(alerts, key=lambda a: a.get("confidence", 0), reverse=True)[:3]
            sevs = {a.get("severity", "") for a in alerts}
            max_conf = max(a.get("confidence", 0) for a in alerts)
            output.append({
                "incident_id": f"AGG-{atype}",
                "type": f"{atype} ×{len(alerts)}",
                "kind": "aggregated_alert",
                "confidence": max_conf,
                "severity": max(sevs, key=lambda s: sev_rank.get(s, 0)),
                "needs_review": True,
                "attack_path": [a.get("attack_path", [[]])[0] for a in top3 if a.get("attack_path")],
                "related_findings": [],
                "attck_techniques": [],
                "signals": [],
                "aggregated_count": len(alerts),
                "aggregated_top": top3,
            })
        return output

    @staticmethod
    def get_analysis(host_id: int) -> Optional[dict]:
        """获取主机的分析结果汇总.

        Args:
            host_id: 主机 ID.

        Returns:
            分析结果字典，不存在时返回 None.

        Note:
            融合检测（A §三/§五）透传：在既有响应基础上**增量**追加
            ``webshells`` / ``memory_shells`` / ``incidents`` 三个顶层字段，
            供前端融合面板直接消费；既有字段（risk_level/risk_score/summary/
            details 等）保持不变，向后兼容。
        """
        result = AnalysisResult.get_by_host(host_id)
        if result is None:
            return None
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        # 仅新增字段，不覆盖既有键
        result.setdefault("webshells", WebShell.list_by_host(host_id))
        result.setdefault("memory_shells", MemoryShell.list_by_host(host_id))
        result.setdefault("incidents", details.get("fusion_incidents", []) or [])
        result.setdefault("knowledge_hits", (details.get("knowledge_hits") or {}).get("items", []) or [])

        # Phase 1 双路检测：将 knowledge_hits 按 process_name 注入到 abnormal_processes
        knowledge_hits = result.get("knowledge_hits", [])
        if knowledge_hits:
            abnormal_procs = result.get("abnormal_processes", [])
            if not abnormal_procs:
                abnormal_procs = AbnormalProcess.list_by_host(host_id)
                result["abnormal_processes"] = abnormal_procs
            for proc in abnormal_procs:
                proc_name = (proc.get("process_name") or proc.get("name") or "").lower()
                # 剥离 .exe/.dll 等扩展名以匹配规则名（对齐 _cross_validate 令牌逻辑）
                proc_name_clean = proc_name.rsplit(".", 1)[0] if "." in proc_name else proc_name
                for kh in knowledge_hits:
                    kh_name = (kh.get("rule_name") or kh.get("title") or "").lower()
                    if proc_name_clean and kh_name and (
                        proc_name_clean in kh_name or kh_name in proc_name_clean or
                        proc_name in kh_name or kh_name in proc_name
                    ):
                        proc["knowledge_hit"] = {
                            "title": kh.get("title", ""),
                            "confidence": kh.get("confidence", "low"),
                            "needs_review": kh.get("needs_review", False),
                            "entry_ref": kh.get("entry_ref"),
                            "evidence_type": kh.get("evidence_type", "process"),
                            "evidence_key": kh.get("evidence_key", ""),
                        }
                        break

        return result

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
        """获取持久化痕迹列表（含 RAG 语义匹配标签）."""
        items = PersistenceItem.list_by_host(host_id)
        # 注入 knowledge_hit 标签供前端 📚 badge 渲染
        result = AnalysisService.get_analysis(host_id)
        knowledge_hits = (result or {}).get("knowledge_hits", [])
        if knowledge_hits:
            for item in items:
                pname = (item.get("name") or "").lower()
                if not pname:
                    continue
                for kh in knowledge_hits:
                    ek = (kh.get("evidence_key") or "").lower()
                    et = kh.get("evidence_type", "")
                    if et == "persistence" and ek and (pname in ek or ek in pname):
                        item["knowledge_hit"] = {
                            "title": kh.get("title", ""),
                            "confidence": kh.get("confidence", "low"),
                            "needs_review": kh.get("needs_review", False),
                            "entry_ref": kh.get("entry_ref"),
                            "evidence_type": et,
                            "evidence_key": ek,
                        }
                        break
        return items

    @staticmethod
    def get_suspicious_connections(host_id: int) -> list:
        """获取可疑外连列表（含 RAG 语义匹配标签）."""
        conns = SuspiciousConnection.list_by_host(host_id)
        # 注入 knowledge_hit 标签供前端 📚 badge 渲染
        result = AnalysisService.get_analysis(host_id)
        knowledge_hits = (result or {}).get("knowledge_hits", [])
        if knowledge_hits:
            for conn in conns:
                remote = (conn.get("remote_address") or conn.get("remote") or "").lower()
                if not remote:
                    continue
                for kh in knowledge_hits:
                    ek = (kh.get("evidence_key") or "").lower()
                    et = kh.get("evidence_type", "")
                    if et == "connection" and ek and (remote in ek or ek in remote):
                        conn["knowledge_hit"] = {
                            "title": kh.get("title", ""),
                            "confidence": kh.get("confidence", "low"),
                            "needs_review": kh.get("needs_review", False),
                            "entry_ref": kh.get("entry_ref"),
                            "evidence_type": et,
                            "evidence_key": ek,
                        }
                        break
        return conns
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
        """获取异常进程列表（含 RAG 语义匹配标签）."""
        procs = AbnormalProcess.list_by_host(host_id)
        # 注入 knowledge_hit 标签供前端 📚 badge 渲染
        result = AnalysisService.get_analysis(host_id)
        knowledge_hits = (result or {}).get("knowledge_hits", [])
        if knowledge_hits:
            for proc in procs:
                pn = (proc.get("process_name") or proc.get("name") or "").lower()
                pc = pn.rsplit(".", 1)[0] if "." in pn else pn
                for kh in knowledge_hits:
                    kn = (kh.get("rule_name") or kh.get("title") or "").lower()
                    if pc and kn and (pc in kn or kn in pc or pn in kn or kn in pn):
                        proc["knowledge_hit"] = {
                            "title": kh.get("title", ""),
                            "confidence": kh.get("confidence", "low"),
                            "needs_review": kh.get("needs_review", False),
                            "entry_ref": kh.get("entry_ref"),
                            "evidence_type": kh.get("evidence_type", "process"),
                            "evidence_key": kh.get("evidence_key", ""),
                        }
                        break
        return procs

    @staticmethod
    def get_startup_items(host_id: int) -> list:
        """获取可疑启动项列表."""
        return SuspiciousStartupItem.list_by_host(host_id)

    @staticmethod
    def get_service_risk(host_id: int) -> Optional[dict]:
        """获取主机服务风险分析（实时计算，不落库）.

        Args:
            host_id: 主机 ID.

        Returns:
            服务风险分析结果字典，无数据时返回 None.
        """
        raw = ImportService.read_raw_json(host_id)
        if not raw:
            return None
        from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer
        return ServiceRiskAnalyzer.analyze(raw, host_id)

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

    @staticmethod
    def _build_tiered_data(raw_data: dict) -> dict:
        """从 raw_data 构建知识检索用的 tiered_data（不依赖 risk_result）.

        提取进程名、外连地址等关键字段供 KnowledgeRetriever 使用。
        """
        tiered: dict = {
            "host_basic": raw_data.get("host_basic", {}),
        }

        # 异常进程（从 raw_data 的 processes 中提取）
        processes = raw_data.get("processes", [])
        if isinstance(processes, list):
            tiered["abnormal_processes_high"] = processes[:10]

        # 网络连接
        net = raw_data.get("network_connections", [])
        if isinstance(net, list):
            tiered["suspicious_connections_high"] = [
                {
                    "remote": c.get("remote_addr", ""),
                    "protocol": c.get("protocol", ""),
                    "process": c.get("process_name", ""),
                }
                for c in net[:5]
            ]

        # summary: 为 _build_query_text 提供分析摘要（对齐 validate-retrieval 的工作格式）
        host = raw_data.get("host_basic", {})
        summary_parts = [host.get("hostname", "")] if host else []
        pnames = [p.get("name", "") for p in (processes or [])[:3] if p.get("name")]
        if pnames:
            summary_parts.append(", ".join(pnames))
        tiered["analysis_result"] = {
            "risk_level": "unknown",
            "summary": " ".join(summary_parts) if summary_parts else "unknown",
        }

        # WebShell 相关数据（从 raw_data 提取）
        ws = raw_data.get("webshell_items") or raw_data.get("webshells", [])
        if isinstance(ws, list):
            tiered["webshell_items"] = ws

        # Memory Shell 相关数据
        ms = raw_data.get("memory_shell_items") or raw_data.get("memory_shells", [])
        if isinstance(ms, list):
            tiered["memory_shell_items"] = ms

        # 持久化痕迹
        persistence_raw = raw_data.get("persistence_items") or raw_data.get("persistence", [])
        if isinstance(persistence_raw, list):
            tiered["persistence_items"] = persistence_raw

        return tiered

    @staticmethod
    def _cross_validate(
        abnormal_processes: list[dict],
        semantic_hits: list[dict],
        suspicious_connections: Optional[list[dict]] = None,
        webshell_hits: Optional[list[dict]] = None,
        memory_shell_hits: Optional[list[dict]] = None,
        persistence_items: Optional[list[dict]] = None,
    ) -> list[dict]:
        """交叉验证：规则命中与语义检索结果合并（多模块扩展）.

        逻辑：
        - process_name/remote_addr/path/class_name/name 相同的命中合并，取最高置信度
        - 规则命中 + 语义命中 → confidence 提升一档（medium→high, low→medium）
        - 仅语义命中无规则 → needs_review=True, confidence="low"
        - 去重后的语义命中追加到结果
        - 每条命中附带 evidence_type / evidence_key 供前端精准跳转

        Args:
            abnormal_processes: 规则引擎检测到的异常进程列表。
            semantic_hits: KnowledgeRetriever.retrieve(structured=True) 的返回结果。
            suspicious_connections: 可疑外连列表（可选）。
            webshell_hits: WebShell 命中列表（可选）。
            memory_shell_hits: Memory Shell 命中列表（可选）。
            persistence_items: 持久化痕迹列表（可选）。

        Returns:
            合并后的 knowledge_hits 列表。
        """
        # 构建规则命中 tokens 集合（进程名 + rule name）
        rule_proc_names: set[str] = set()
        for proc in abnormal_processes:
            name = (proc.get("process_name") or proc.get("name") or "").lower()
            rule_name = (proc.get("rule_name") or "").lower()
            if name:
                rule_proc_names.add(name)
            if rule_name:
                rule_proc_names.add(rule_name)

        # 构建多模块匹配键集合
        conn_remotes: set[str] = set()
        ws_paths: set[str] = set()
        ms_classes: set[str] = set()
        pers_names: set[str] = set()

        for conn in (suspicious_connections or []):
            remote = (conn.get("remote_address") or conn.get("remote") or "").lower()
            if remote:
                conn_remotes.add(remote)

        for ws in (webshell_hits or []):
            path = (ws.get("path") or "").lower()
            if path:
                ws_paths.add(path)

        for ms in (memory_shell_hits or []):
            cname = (ms.get("class_name") or "").lower()
            if cname:
                ms_classes.add(cname)

        for pers in (persistence_items or []):
            name = (pers.get("name") or "").lower()
            if name:
                pers_names.add(name)

        # 构建所有维度的统一匹配键
        all_match_keys: set[str] = set()
        all_match_keys.update(rule_proc_names)
        all_match_keys.update(conn_remotes)
        all_match_keys.update(ws_paths)
        all_match_keys.update(ms_classes)
        all_match_keys.update(pers_names)

        merged: list[dict] = []
        seen_names: set[str] = set()

        for hit in semantic_hits:
            if not isinstance(hit, dict):
                continue
            rule_name = (hit.get("rule_name") or hit.get("title") or "").lower()
            title = (hit.get("title") or "").lower()
            if not rule_name and not title:
                continue

            # 去重
            dedup_key = rule_name or title
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            confidence = hit.get("confidence", "low")
            needs_review = False

            # ── 确定 evidence_type 和 evidence_key ──
            evidence_type = hit.get("evidence_type", "process")
            evidence_key = ""

            # 检查是否与规则引擎命中交叉
            rule_matched = False

            # 停用词：避免通用词 token 造成误匹配（如 anomalous/network/process）
            _STOPWORDS = {
                "anomalous", "network", "process", "suspicious", "abnormal",
                "malicious", "unknown", "default", "system", "service", "exe",
            }
            hit_tokens = set(
                t for t in rule_name.replace("_", " ").replace("-", " ").replace(".", " ").split()
                if t and t not in _STOPWORDS
            )

            # 匹配进程名
            for pn in rule_proc_names:
                pn_tokens = set(
                    t for t in pn.replace("_", " ").replace("-", " ").replace(".", " ").split()
                    if t and t not in _STOPWORDS
                )
                if hit_tokens and hit_tokens & pn_tokens:
                    rule_matched = True
                    evidence_type = "process"
                    evidence_key = pn
                    break
                if rule_name in pn or pn in rule_name or title in pn or pn in title:
                    rule_matched = True
                    evidence_type = "process"
                    evidence_key = pn
                    break

            # 匹配外连地址
            if not rule_matched:
                description = (hit.get("description") or "").lower()
                for remote in conn_remotes:
                    if remote and (remote in rule_name or remote in title or remote in description):
                        rule_matched = True
                        evidence_type = "connection"
                        evidence_key = remote
                        break

            # 匹配 WebShell 路径
            if not rule_matched:
                for path in ws_paths:
                    if path and (path in rule_name or any(tok in path for tok in hit_tokens)):
                        rule_matched = True
                        evidence_type = "webshell"
                        evidence_key = path
                        break

            # 匹配 Memory Shell class_name
            if not rule_matched:
                for cname in ms_classes:
                    if cname and (cname in rule_name or any(tok in cname for tok in hit_tokens)):
                        rule_matched = True
                        evidence_type = "memory_shell"
                        evidence_key = cname
                        break

            # 匹配持久化 name
            if not rule_matched:
                for pname in pers_names:
                    if pname and (pname in rule_name or any(tok in pname for tok in hit_tokens)):
                        rule_matched = True
                        evidence_type = "persistence"
                        evidence_key = pname
                        break

            # ── 兜底：无匹配时做 best-effort 关联 ──
            if not rule_matched and not evidence_key:
                # 优先从异常进程列表取第一个非系统进程名作为上下文锚点
                for proc in abnormal_processes:
                    pn = (proc.get("process_name") or proc.get("name") or "").lower()
                    # 跳过系统进程（process_name_spoof 等的 known system）
                    if not pn or pn in ("system", "secure system", "registry", "memory compression",
                                         "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                                         "services.exe", "lsass.exe", "svchost.exe"):
                        continue
                    evidence_key = pn
                    evidence_type = "process"
                    break
                if not evidence_key and abnormal_processes:
                    evidence_key = abnormal_processes[0].get("process_name", "unknown")

            if rule_matched:
                # 规则命中 + 语义命中 → 置信度提升一档
                if confidence == "medium":
                    confidence = "high"
                elif confidence == "low":
                    confidence = "medium"
            else:
                # 仅语义命中无规则佐证
                needs_review = True
                confidence = "low"

            merged.append({
                "title": hit.get("title", rule_name),
                "rule_name": hit.get("rule_name", rule_name),
                "description": hit.get("description", hit.get("summary", "")),
                "severity": hit.get("severity", "medium"),
                "category": hit.get("category", ""),
                "confidence": confidence,
                "score": hit.get("score", 0.0),
                "needs_review": needs_review,
                "source": "semantic",
                "entry_ref": hit.get("entry_ref"),
                "entry_type": hit.get("entry_type", "unknown"),
                "evidence_type": evidence_type,
                "evidence_key": evidence_key,
                "match_reason": (
                    "规则+语义交叉命中" if rule_matched else "仅语义检索命中"
                ),
            })

        # 按 score 降序排序，取 top-5 高质量命中
        merged.sort(key=lambda h: h.get("score", 0.0), reverse=True)
        return merged[:5]
