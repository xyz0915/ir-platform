"""导入服务 — JSON 解析、校验、存储."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.models.host import Host
from app.models.import_record import ImportRecord
from app.schemas.agent_data import AgentData

logger = logging.getLogger(__name__)


class ImportService:
    """JSON 导入业务逻辑层."""

    @staticmethod
    def validate_schema(data: dict) -> AgentData:
        """使用 Pydantic 校验 JSON 数据格式.

        Args:
            data: Agent JSON 数据字典.

        Returns:
            校验通过的 AgentData 对象.

        Raises:
            ValueError: 校验失败时抛出，包含错误详情.
        """
        try:
            return AgentData(**data)
        except Exception as exc:
            logger.warning("Schema validation failed: %s", exc)
            raise ValueError(f"JSON Schema 校验失败: {exc}")

    @staticmethod
    def save_raw_json(host_id: int, data_or_bytes: dict | bytes) -> str:
        """保存原始 JSON 到文件系统.

        Args:
            host_id: 主机 ID.
            data_or_bytes: JSON 数据字典或原始字节（优先）。

        Returns:
            保存的文件路径.
        """
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"host_{host_id}_{timestamp}.json"
        file_path = Path(settings.UPLOAD_DIR) / file_name
        if isinstance(data_or_bytes, bytes):
            # 直接保存原始字节，避免重复序列化（性能优化）
            with open(file_path, "wb") as f:
                f.write(data_or_bytes)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data_or_bytes, f, ensure_ascii=False, indent=2)
        return str(file_path)

    @staticmethod
    def build_data_summary(data: dict) -> str:
        """构建数据摘要（各类数据条数统计）.

        Args:
            data: Agent JSON 数据.

        Returns:
            JSON 格式的摘要字符串.
        """
        summary = {}
        for key in ["users", "processes", "services", "startup_items", "timeline"]:
            val = data.get(key, [])
            summary[key] = len(val) if isinstance(val, list) else 0
        network = data.get("network", {})
        if isinstance(network, dict):
            summary["network_connections"] = len(network.get("connections", []))
            summary["network_interfaces"] = len(network.get("interfaces", []))
        persistence = data.get("persistence", {})
        if isinstance(persistence, dict):
            summary["persistence_items"] = sum(
                len(v) for v in persistence.values() if isinstance(v, list)
            )
        # 新增 4 个顶层字段计数（数据采集增强）
        for new_key in ["network_connections", "file_hashes",
                        "wmi_subscriptions", "registry_keys",
                        "files", "logs", "security", "browser",
                        "usb", "remote_control", "ioc"]:
            val = data.get(new_key, [])
            summary[new_key] = len(val) if isinstance(val, list) else (len(val.keys()) if isinstance(val, dict) else 0)
        return json.dumps(summary, ensure_ascii=False)

    @staticmethod
    def import_json(host_id: int, file_content: bytes, file_name: str) -> dict:
        """完整导入流程：校验 → 保存 → 更新主机状态 → 记录导入.

        Args:
            host_id: 主机 ID.
            file_content: 文件内容（字节）.
            file_name: 原始文件名.

        Returns:
            导入记录字典.

        Raises:
            ValueError: JSON 解析或 Schema 校验失败.
        """
        # 检查文件大小
        max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_content) > max_size:
            raise ValueError(
                f"文件大小超过限制（{settings.MAX_FILE_SIZE_MB}MB）"
            )

        # 解析 JSON
        try:
            data = json.loads(file_content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("JSON parse failed: %s", exc)
            record = ImportRecord.create(
                host_id=host_id,
                file_name=file_name,
                file_path="",
                status="failed",
                error_message=f"JSON 解析失败: {exc}",
            )
            raise ValueError(f"JSON 解析失败: {exc}")

        # 校验 Schema
        try:
            agent_data = ImportService.validate_schema(data)
        except ValueError as exc:
            record = ImportRecord.create(
                host_id=host_id,
                file_name=file_name,
                file_path="",
                status="failed",
                error_message=str(exc),
            )
            raise

        # 保存原始 JSON（直接存上传的字节，避免重序列化）
        file_path = ImportService.save_raw_json(host_id, file_content)

        # 构建数据摘要
        data_summary = ImportService.build_data_summary(data)

        # 更新主机信息
        system_info = data.get("system_info", {})
        metadata = data.get("metadata", {})
        Host.update_status(
            host_id,
            status="imported",
            raw_json_path=file_path,
            agent_version=metadata.get("agent_version"),
            collection_time=metadata.get("collection_time"),
            os_type=metadata.get("platform"),
            hostname=system_info.get("hostname") if isinstance(system_info, dict) else None,
            os_version=system_info.get("os_version") if isinstance(system_info, dict) else None,
        )

        # 日志范式化（不阻塞导入）
        try:
            from app.analysis.log_normalizer import LogNormalizer
            from app.models.normalized_log import NormalizedLog
            host_info = Host.get_by_id(host_id)
            hostname = host_info.get("hostname", "") if host_info else ""
            logs_data = data.get("logs", {})
            if logs_data:
                normalized = LogNormalizer.normalize_host_logs(logs_data, host_id, hostname)
                if normalized:
                    count = NormalizedLog.batch_create(normalized)
                    if count:
                        logger.info("Normalized %d log entries for host %d", count, host_id)
        except Exception as exc:
            logger.warning("Log normalization failed (non-blocking): %s", exc)

        # ── ★ 新增：写入 agent_imports 表（日志检索模块）──
        try:
            from app.services.log_importer import import_batch as log_import_batch
            # Agent JSON 中的采集器映射到 log_importer 的 collector_type
            COLLECTOR_MAP = {
                "processes": "processes",
                "network_connections": "network",
                "registry_keys": "registry",
                "file_hashes": "files",
                "files": "files",
                "logs": "logs",
                "security": "security",
                "browser": "browser",
                "usb": "usb",
                "remote_control": "remote_control",
                "ioc": "ioc",
                "persistence_items": "persistence",
                "wmi_subscriptions": "wmi",
                "startup_items": "startup",
                "services": "services",
                "users": "users",
                "network_interfaces": "network",
                "scheduled_tasks": "scheduled_tasks",
            }
            records_to_import = []
            for key, collector_type in COLLECTOR_MAP.items():
                items = data.get(key, [])
                if not items:
                    continue
                if isinstance(items, dict):
                    items = [items]
                raw_json_str = json.dumps(items, ensure_ascii=False)
                records_to_import.append({
                    "collector_type": collector_type,
                    "raw_json": raw_json_str,
                })
            if records_to_import:
                # 从 host 获取 case_id
                host_case_id = host_info.get("case_id") if host_info else None
                log_import_batch(host_id, records_to_import, case_id=host_case_id)
                logger.info(
                    "Imported %d collector groups to agent_imports for host %d",
                    len(records_to_import), host_id,
                )
        except Exception as exc:
            logger.warning("agent_imports write failed (non-blocking): %s", exc)

        # ── ★ 新增：触发事件归一化 → 写入 security_events（分析中心模块）──
        try:
            from app.services.event_normalizer import normalize_batch, bulk_insert
            # 构造 raw_events：每条记录加 event_type 和 host_id
            # 注入 _fallback_ts（仅当 mapper 没有找到更精确的时间时使用）
            fallback_ts = None
            metadata = data.get("metadata", {})
            if isinstance(metadata, dict):
                fallback_ts = metadata.get("collection_time") or metadata.get("timestamp")
            raw_events = []
            EVENT_TYPE_MAP = {
                "processes": "process_start",
                "network_connections": "network_outbound",
                "registry_keys": "registry_modify",
                "file_hashes": "file_create",
                "files": "file_event",
                "logs": "log_event",
                "security": "security_event",
                "browser": "browser_event",
                "usb": "usb_event",
                "remote_control": "remote_control_event",
                "ioc": "ioc_event",
                "persistence_items": "persistence_register",
                "wmi_subscriptions": "wmi_subscribe",
                "startup_items": "persistence_register",
                "services": "service_operation",
                "users": "user_login",
                "network_interfaces": "network_listen",
            }
            # 构建 persistence.services 交叉索引（用于服务事件补全 path）
            persistence_data = data.get("persistence", {})
            if isinstance(persistence_data, dict):
                persist_services = persistence_data.get("services", [])
            else:
                persist_services = []
            persist_map: dict[str, str] = {}
            if isinstance(persist_services, list):
                for ps in persist_services:
                    if isinstance(ps, dict) and ps.get("name"):
                        persist_map[ps["name"]] = ps.get("command")

            # ── 展平 logs dict → list ──
            logs_data = data.get("logs", {})
            if isinstance(logs_data, dict):
                flat_logs: list[dict] = []
                for log_name, entries in logs_data.items():
                    if isinstance(entries, list):
                        for entry in entries:
                            if isinstance(entry, dict):
                                entry.setdefault("log_name", log_name)
                                flat_logs.append(entry)
                data["logs"] = flat_logs

            for key, event_type in EVENT_TYPE_MAP.items():
                items = data.get(key, [])
                if not items:
                    continue
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            item["event_type"] = event_type
                            item["host_id"] = host_id
                            # 服务事件注入 persistence 路径映射
                            if event_type == "service_operation" and persist_map:
                                item["_persist_path"] = persist_map.get(item.get("name"))
                            if fallback_ts and "timestamp" not in item:
                                item["_fallback_ts"] = fallback_ts
                            raw_events.append(item)
            if raw_events:
                events = normalize_batch(raw_events, validate=False)
                if events:
                    # 规则匹配：自动标记 matched_rules
                    from app.services.event_normalizer import _enrich_with_matched_rules
                    _enrich_with_matched_rules(events)
                    inserted, skipped = bulk_insert(events)
                    logger.info(
                        "Normalized %d events (inserted=%d, skipped=%d) for host %d",
                        len(events), inserted, skipped, host_id,
                    )
        except Exception as exc:
            logger.warning("Event normalization failed (non-blocking): %s", exc)

        # 创建导入记录
        record = ImportRecord.create(
            host_id=host_id,
            file_name=file_name,
            file_path=file_path,
            status="success",
            data_summary=data_summary,
        )

        logger.info("Import completed for host %d, file: %s", host_id, file_name)
        return record

    @staticmethod
    def read_raw_json(host_id: int) -> Optional[dict]:
        """读取主机的原始 JSON 数据.

        Args:
            host_id: 主机 ID.

        Returns:
            JSON 数据字典，不存在时返回 None.
        """
        host = Host.get_by_id(host_id)
        if not host or not host.get("raw_json_path"):
            return None
        file_path = Path(host["raw_json_path"])
        if not file_path.exists():
            logger.warning("Raw JSON file not found: %s", file_path)
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
