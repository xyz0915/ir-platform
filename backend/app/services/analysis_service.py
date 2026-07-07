"""分析编排服务 — 协调各分析模块完成完整分析流程."""

import json
import logging
from typing import Any, Optional

from app.analysis.profile_builder import ProfileBuilder
from app.analysis.anomaly_detector import AnomalyDetector
from app.analysis.timeline_builder import TimelineBuilder
from app.analysis.ioc_checker import IocChecker
from app.analysis.persistence_finder import PersistenceFinder
from app.analysis.risk_assessor import RiskAssessor
from app.models.analysis import (
    AnalysisResult, HostProfile, AbnormalProcess, SuspiciousConnection,
    SuspiciousStartupItem, PersistenceItem, TimelineEvent, IocHit,
    clear_analysis_by_host,
)
from app.models.host import Host
from app.rules.rule_engine import RuleEngine
from app.services.import_service import ImportService

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

        # 4. 异常检测
        abnormal_processes = AnomalyDetector.detect_processes(raw_data, rules)
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

        # 8. 风险评估
        findings = {
            "abnormal_processes": abnormal_processes,
            "suspicious_connections": suspicious_connections,
            "suspicious_startup_items": suspicious_startup,
            "persistence_items": assessed_persistence,
            "ioc_hits": ioc_hits,
            "timeline_events": timeline_events,
        }
        risk_result = RiskAssessor.assess(findings)

        # 9. 保存分析结果
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
    def get_abnormal_processes(host_id: int) -> list:
        """获取异常进程列表."""
        return AbnormalProcess.list_by_host(host_id)

    @staticmethod
    def get_startup_items(host_id: int) -> list:
        """获取可疑启动项列表."""
        return SuspiciousStartupItem.list_by_host(host_id)
