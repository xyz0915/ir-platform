"""EVTX 解析器 — 使用 python-evtx 库解析 Windows Event Log 文件.

输出格式化的日志条目列表，每条包含 EventID、TimeCreated、EventData 等字段。
"""

import logging
import xml.etree.ElementTree as ET
from typing import Any, Optional

from app.analysis.log_normalizer import WINDOWS_EVENT_MAP

logger = logging.getLogger(__name__)


class EvtxParser:
    """EVTX 解析器."""

    @staticmethod
    def parse(file_path: str, host_id: int, hostname: str) -> list[dict[str, Any]]:
        """解析 EVTX 文件，返回格式化日志条目列表.

        Args:
            file_path: EVTX 文件路径。
            host_id: 主机 ID。
            hostname: 主机名。

        Returns:
            list[dict]: 解析后的日志条目列表。
        """
        from python_evtx.evtx import EvtxFile

        results: list[dict[str, Any]] = []

        try:
            with EvtxFile(file_path) as evtx:
                for record in evtx.records():
                    try:
                        item = EvtxParser._parse_record(record, host_id, hostname)
                        if item:
                            results.append(item)
                    except Exception as e:
                        logger.debug("Skipping EVTX record due to parse error: %s", e)
                        continue
        except FileNotFoundError:
            logger.error("EVTX file not found: %s", file_path)
            raise
        except Exception as e:
            logger.error("Failed to open EVTX file %s: %s", file_path, e)
            raise

        logger.info("Parsed %d records from %s", len(results), file_path)
        return results

    @staticmethod
    def _parse_record(record: Any, host_id: int, hostname: str) -> Optional[dict[str, Any]]:
        """解析单条 EVTX Record.

        Args:
            record: EvtxRecord 对象。
            host_id: 主机 ID。
            hostname: 主机名。

        Returns:
            dict | None: 解析后的条目。
        """
        xml_str = record.xml()
        if not xml_str:
            return None

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            logger.debug("Failed to parse EVTX record XML")
            return None

        # 提取 EventID
        event_id = EvtxParser._extract_event_id(root)

        # 提取 TimeCreated
        timestamp = EvtxParser._extract_time_created(root)

        # 提取 EventData
        raw_data = EvtxParser._extract_event_data(root)

        # 根据 EventID 映射事件类型、严重度、MITRE
        event_type, event_label, severity, mitre = EvtxParser._map_event_id(event_id)

        return {
            "host_id": host_id,
            "hostname": hostname,
            "log_source": "evtx",
            "event_id": event_id,
            "event_type": event_type,
            "event_label": event_label,
            "severity": severity,
            "mitre_attack": mitre,
            "timestamp": timestamp,
            "raw_data": raw_data,
        }

    @staticmethod
    def _extract_event_id(root: ET.Element) -> int:
        """从 XML 中提取 EventID."""
        # System/EventID
        event_id_elem = root.find(".//{*}EventID")
        if event_id_elem is not None:
            try:
                return int(event_id_elem.text or 0)
            except (ValueError, TypeError):
                pass
        return 0

    @staticmethod
    def _extract_time_created(root: ET.Element) -> str:
        """从 XML 中提取 TimeCreated ISO 字符串."""
        time_elem = root.find(".//{*}TimeCreated")
        if time_elem is not None:
            return time_elem.get("SystemTime", "")
        return ""

    @staticmethod
    def _extract_event_data(root: ET.Element) -> dict[str, str]:
        """从 XML 中提取 EventData 字段.

        遍历 EventData/Data 元素，提取 Name 属性值和文本内容。
        """
        raw_data: dict[str, str] = {}

        # EventData 中的 Data 元素
        data_elems = root.findall(".//{*}EventData/{*}Data")
        for data_elem in data_elems:
            name = data_elem.get("Name", "")
            text = (data_elem.text or "").strip()
            if name:
                raw_data[name] = text

        # 也尝试从 UserData 提取
        user_data_elems = root.findall(".//{*}UserData/*")
        for elem in user_data_elems:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            text = (elem.text or "").strip()
            if tag:
                raw_data[tag] = text

        # 从 System/Channel 获取日志来源
        channel_elem = root.find(".//{*}Channel")
        if channel_elem is not None:
            raw_data["channel"] = (channel_elem.text or "").strip()

        # 从 System/Computer 获取计算机名
        computer_elem = root.find(".//{*}Computer")
        if computer_elem is not None:
            raw_data["computer"] = (computer_elem.text or "").strip()

        return raw_data

    @staticmethod
    def _map_event_id(event_id: int) -> tuple[str, str, str, str]:
        """将 EventID 映射为 (event_type, event_label, severity, mitre_attack).

        未注册的 EventID 返回 generic 类型。
        """
        mapping = WINDOWS_EVENT_MAP.get(event_id)
        if mapping:
            return mapping
        return (f"unknown_{event_id}", f"事件 {event_id}", "info", "")
