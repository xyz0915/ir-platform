"""手工日志导入编排服务 — 串联解析器 + 规则匹配 + 告警引擎.

处理流程:
  1. 保存上传文件到磁盘
  2. FormatDetector 三级检测格式
  3. 创建 ImportRecord（状态 processing）
  4. 根据文件大小决定同步/异步处理
  5. 解析 → 范式化 → 翻译 → 去重 → 批量写入 → 规则匹配 → 告警
"""

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.database import get_connection
from app.models.host import Host
from app.models.import_record import ImportRecord
from app.models.import_result import ImportResult
from app.models.normalized_log import NormalizedLog

from app.parsers.format_detector import FormatDetector, UnsupportedFormatError
from app.parsers.evtx_parser import EvtxParser
from app.parsers.access_log_parser import AccessLogParser
from app.parsers.syslog_parser import SyslogParser
from app.parsers.translator import Translator

logger = logging.getLogger(__name__)


def read_file_with_encoding(file_path: str) -> list[str]:
    """自动检测编码并返回文件行列表.

    Args:
        file_path: 文件路径.

    Returns:
        list[str]: 按行读取的文件内容列表.
    """
    try:
        from app.parsers.format_detector import detect_encoding
        enc = detect_encoding(file_path)
    except Exception:
        enc = "utf-8"
    with open(file_path, "r", encoding=enc, errors="replace") as f:
        return f.readlines()


class ImportLogService:
    """手工日志导入编排服务."""

    # ── 异步任务进度追踪 ──────────────────────────────────────
    _async_progress: dict[str, dict] = {}  # task_id → {phase, parsed, total, pct}
    _lock = threading.Lock()

    @staticmethod
    def update_progress(task_id: str, phase: str, parsed: int = 0, total: int = 0) -> None:
        """更新异步任务进度.

        Args:
            task_id: 任务 ID（字符串形式的 record_id）.
            phase: 当前阶段 (detecting|parsing|translating|matching|completed).
            parsed: 已处理数量.
            total: 总数量.
        """
        pct = int((parsed / total) * 100) if total > 0 else 0
        with ImportLogService._lock:
            ImportLogService._async_progress[task_id] = {
                "phase": phase,
                "parsed": parsed,
                "total": total,
                "pct": min(pct, 100),
            }

    @staticmethod
    def get_async_progress(task_id: str) -> dict:
        """查询异步任务进度.

        Args:
            task_id: 任务 ID.

        Returns:
            dict: {phase, parsed, total, pct} 或 {"phase": "unknown", "pct": 0}.
        """
        with ImportLogService._lock:
            return ImportLogService._async_progress.get(
                task_id, {"phase": "unknown", "parsed": 0, "total": 0, "pct": 0},
            )

    @staticmethod
    def _save_uploaded_file(host_id: int, file: Any) -> str:
        """保存上传文件到磁盘.

        Args:
            host_id: 主机 ID.
            file: FastAPI UploadFile 对象.

        Returns:
            str: 保存的文件路径.
        """
        upload_base = getattr(settings, "UPLOAD_DIR", "./uploads")
        host_dir = Path(upload_base) / f"host_{host_id}"
        host_dir.mkdir(parents=True, exist_ok=True)

        # 安全文件名：仅保留字母数字 . _ -
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or "upload")
        file_path = str(host_dir / safe_name)

        # 写入文件
        content = file.file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        logger.info("Saved uploaded file to %s (%d bytes)", file_path, len(content))
        return file_path

    @staticmethod
    def import_file(
        host_id: int,
        file: Any,
        log_type_str: Optional[str] = None,
    ) -> dict:
        """导入日志文件：保存 → 检测 → 创建记录 → 同步/异步处理.

        Args:
            host_id: 主机 ID.
            file: FastAPI UploadFile 对象.
            log_type_str: 用户指定的日志类型（可选，覆盖自动检测）.

        Returns:
            dict: {record_id, file_name, file_size, log_type, status, ...}
        """
        # 1. 保存文件
        file_path = ImportLogService._save_uploaded_file(host_id, file)
        file_size = os.path.getsize(file_path)

        # 2. 格式检测
        try:
            if log_type_str:
                log_source = log_type_str
                detected_format = log_type_str
            else:
                # 读取文件头 16 字节 + 前 5 行
                with open(file_path, "rb") as f:
                    header = f.read(16)

                first_lines: list[str] = []
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f):
                            if i >= 5:
                                break
                            first_lines.append(line)
                except Exception:
                    pass

                log_source, detected_format = FormatDetector.detect(
                    file.filename or "unknown",
                    header,
                    first_lines,
                )
        except UnsupportedFormatError:
            # 创建失败记录
            record = ImportRecord.create(
                host_id=host_id,
                file_name=file.filename or "unknown",
                file_path=file_path,
                status="failed",
                error_message="不支持的日志格式",
                log_type="unknown",
                file_size=file_size,
            )
            return {
                "record_id": record["id"],
                "file_name": file.filename,
                "file_size": file_size,
                "log_type": "unknown",
                "status": "failed",
                "message": "不支持的日志格式",
            }

        # 3. 创建导入记录
        record = ImportRecord.create(
            host_id=host_id,
            file_name=file.filename or "unknown",
            file_path=file_path,
            status="processing",
            log_type=log_source,
            file_size=file_size,
        )
        record_id = record["id"]

        # 4. 决定同步/异步
        async_threshold = getattr(settings, "ASYNC_THRESHOLD_MB", 100) * 1024 * 1024
        if file_size > async_threshold:
            # 异步处理
            thread = threading.Thread(
                target=ImportLogService.process_file_async,
                args=(host_id, file_path, log_source, record_id),
                daemon=True,
            )
            thread.start()
            return {
                "record_id": record_id,
                "file_name": file.filename,
                "file_size": file_size,
                "log_type": log_source,
                "status": "processing",
                "message": "文件较大，已在后台异步处理",
            }
        else:
            # 同步处理
            result = ImportLogService.process_file_sync(
                host_id, file_path, log_source, record_id,
            )
            return {
                "record_id": record_id,
                "file_name": file.filename,
                "file_size": file_size,
                "log_type": log_source,
                "status": result.get("status", "completed"),
                "parsed_count": result.get("parsed_count", 0),
                "event_count": result.get("event_count", 0),
            }

    @staticmethod
    def process_file_sync(
        host_id: int,
        file_path: str,
        log_source: str,
        record_id: int,
    ) -> dict:
        """同步处理日志文件：解析 → 范式化 → 翻译 → 去重 → 规则匹配.

        Args:
            host_id: 主机 ID.
            file_path: 文件路径.
            log_source: 日志来源（如 'evtx', 'nginx_access'）.
            record_id: 导入记录 ID.

        Returns:
            dict: {status, parsed_count, event_count}.
        """
        task_id = str(record_id)
        try:
            # 1. 查主机名
            host = Host.get_by_id(host_id)
            hostname = host.get("hostname", f"host_{host_id}") if host else f"host_{host_id}"

            # 2. 解析
            ImportLogService.update_progress(task_id, "detecting")
            parsed_items: list[dict] = []
            if log_source == "evtx":
                parsed_items = EvtxParser.parse(file_path, host_id, hostname)
            elif log_source.startswith("syslog"):
                lines = read_file_with_encoding(file_path)
                total_lines = len(lines)
                ImportLogService.update_progress(task_id, "parsing", 0, total_lines)
                parsed_items = SyslogParser.parse(lines, log_source, host_id, hostname)
                ImportLogService.update_progress(task_id, "parsing", total_lines, total_lines)
            else:
                # 先统计总行数
                lines = read_file_with_encoding(file_path)
                total_lines = len(lines)
                ImportLogService.update_progress(task_id, "parsing", 0, total_lines)
                parsed_items = AccessLogParser.parse(lines, log_source, host_id, hostname)
                ImportLogService.update_progress(task_id, "parsing", total_lines, total_lines)

            parsed_count = len(parsed_items)
            logger.info("Parsed %d items from %s (log_source=%s)", parsed_count, file_path, log_source)

            # 3. 范式化写入 normalized_logs
            ImportLogService.update_progress(task_id, "translating", 0, max(parsed_count, 1))
            if parsed_items:
                NormalizedLog.batch_create(parsed_items)

            # 4. 翻译为 SecurityEvent 格式
            translated = Translator.translate(parsed_items, host_id)
            logger.info("Translated %d events", len(translated))

            # 5. 去重并批量写入 security_events
            ImportLogService.update_progress(task_id, "matching")
            new_events = ImportLogService._dedup_and_insert_events(translated, host_id)
            event_count = len(new_events)

            # 6. 写入 import_results
            for item in parsed_items:
                event_key = item.get("event_key", "")
                if not event_key and log_source == "evtx":
                    event_key = f"{item.get('event_id', '')}:{item.get('timestamp', '')}"
                ImportResult.create(
                    import_id=record_id,
                    log_source=log_source,
                    parsed_line=parsed_items.index(item) + 1,
                    event_type=item.get("event_type", "unknown"),
                    severity=item.get("severity", "info"),
                    event_key_hash=event_key,
                )

            # 7. 规则匹配 + 告警（不阻塞主流程）
            ImportLogService._run_rule_matching(new_events)
            ImportLogService._create_alerts(new_events)

            # 8. 写入 agent_imports 表（日志检索模块可用，非阻塞）
            try:
                from app.services.log_importer import import_batch as log_import_batch
                records_to_import = [{
                    "collector_type": log_source,
                    "collector_name": log_source,
                    "raw_json": json.dumps(parsed_items, ensure_ascii=False),
                }]
                log_import_batch(host_id, records_to_import, case_id=None)
                logger.info("Written %d items to agent_imports for host %d", len(parsed_items), host_id)
            except ImportError:
                logger.info("log_importer not available, skipping agent_imports write")
            except Exception as exc:
                logger.warning("agent_imports write failed (non-blocking): %s", exc)

            # 9. 更新 ImportRecord 状态
            ImportRecord.update_status(
                record_id=record_id,
                status="completed",
                parsed_count=parsed_count,
                event_count=event_count,
            )
            ImportLogService.update_progress(task_id, "completed", parsed_count, max(parsed_count, 1))

            return {
                "status": "completed",
                "parsed_count": parsed_count,
                "event_count": event_count,
            }

        except Exception as e:
            logger.error("process_file_sync failed: %s", e, exc_info=True)
            error_msg = str(e)[:500] if str(e) else "未知错误"
            ImportRecord.update_status(
                record_id=record_id,
                status="failed",
                parsed_count=0,
                event_count=0,
                error_message=error_msg,
            )
            ImportLogService.update_progress(task_id, "failed", 0, 1)
            return {
                "status": "failed",
                "parsed_count": 0,
                "event_count": 0,
                "error": error_msg,
            }

    @staticmethod
    def process_file_async(
        host_id: int,
        file_path: str,
        log_source: str,
        record_id: int,
    ) -> None:
        """异步处理日志文件（在线程中调用 process_file_sync）.

        包含 30 分钟超时保护：超时后自动将记录标记为失败。

        Args:
            host_id: 主机 ID.
            file_path: 文件路径.
            log_source: 日志来源.
            record_id: 导入记录 ID.
        """
        task_id = str(record_id)
        # 初始化进度
        ImportLogService.update_progress(task_id, "pending")

        timeout_flag = threading.Event()
        result_container: dict = {}

        def _run_with_timeout():
            try:
                result = ImportLogService.process_file_sync(
                    host_id, file_path, log_source, record_id,
                )
                result_container["result"] = result
            except Exception as e:
                result_container["error"] = e

        worker = threading.Thread(target=_run_with_timeout, daemon=True)
        timer = threading.Timer(
            1800.0,  # 30 分钟超时
            lambda: timeout_flag.set(),
        )

        worker.start()
        timer.start()

        worker.join(timeout=1860)  # 略大于 timer，确保 timer 先触发
        timer.cancel()

        if timeout_flag.is_set():
            logger.error("Async import TIMEOUT: record_id=%d (exceeded 30min)", record_id)
            ImportRecord.update_status(
                record_id=record_id,
                status="failed",
                error_message="处理超时（超过 30 分钟）",
            )
        elif "error" in result_container:
            e = result_container["error"]
            logger.error("Async import failed: record_id=%d, error=%s", record_id, e)
            ImportRecord.update_status(
                record_id=record_id,
                status="failed",
                error_message=str(e)[:500],
            )
        else:
            res = result_container.get("result", {})
            logger.info(
                "Async import completed: record_id=%d, status=%s",
                record_id, res.get("status"),
            )

    @staticmethod
    def _dedup_and_insert_events(
        translated: list[dict],
        host_id: int,
    ) -> list[dict]:
        """对翻译后的事件去重并批量写入 security_events 表.

        Args:
            translated: Translator.translate() 的输出.
            host_id: 主机 ID.

        Returns:
            list[dict]: 新写入（不重复）的事件列表.
        """
        if not translated:
            return []

        now = datetime.now().isoformat()
        new_events: list[dict] = []

        with get_connection() as conn:
            for event in translated:
                event_key = event.get("event_key", "")
                if not event_key:
                    continue

                # 查重
                existing = conn.execute(
                    "SELECT id FROM security_events WHERE event_key=? AND host_id=?",
                    (event_key, host_id),
                ).fetchone()

                if existing:
                    continue

                event_id = event.get("id", event_key)
                evidence_json = json.dumps(event.get("evidence", {}), ensure_ascii=False)
                timestamp = event.get("timestamp", now)

                conn.execute(
                    """
                    INSERT INTO security_events
                        (id, timestamp, host_id, event_type, severity, source_collector,
                         event_key, attack_stage, ioc_matches, evidence, status,
                         matched_rules, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        timestamp,
                        host_id,
                        event.get("event_type", "unknown"),
                        event.get("severity", "info"),
                        event.get("source_collector", "manual_import"),
                        event_key,
                        event.get("attack_stage", "unknown"),
                        event.get("ioc_matches", "[]"),
                        evidence_json,
                        "pending",
                        event.get("matched_rules", "[]"),
                        now,
                        now,
                    ),
                )
                new_events.append(event)

            conn.commit()

        logger.info("Inserted %d new security_events (deduped %d duplicates)", len(new_events), len(translated) - len(new_events))
        return new_events

    @staticmethod
    def _run_rule_matching(events: list[dict]) -> None:
        """对事件执行规则匹配（不阻塞，ImportError 则跳过）.

        Args:
            events: 新创建的事件列表.
        """
        try:
            from app.services.rule_matcher import RuleMatcher
            matcher = RuleMatcher()
            for event in events:
                try:
                    matcher.match_event(event)
                except Exception as e:
                    logger.debug("Rule matching failed for event %s: %s", event.get("id"), e)
        except ImportError:
            logger.info("rule_matcher not available, skipping rule matching")
        except Exception as e:
            logger.warning("Rule matching error: %s", e)

    @staticmethod
    def _create_alerts(events: list[dict]) -> None:
        """对事件创建告警（不阻塞，ImportError 则跳过）.

        Args:
            events: 新创建的事件列表.
        """
        try:
            from app.services.alert_engine import AlertEngine
            engine = AlertEngine()
            for event in events:
                try:
                    engine.process_event(event.get("host_id", 0), event)
                except Exception as e:
                    logger.debug("Alert creation failed for event %s: %s", event.get("id"), e)
        except ImportError:
            logger.info("alert_engine not available, skipping alert creation")
        except Exception as e:
            logger.warning("Alert creation error: %s", e)
