"""IOC 提取器 — 从 evidence JSON 中自动提取威胁指标."""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

IPV4_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
DOMAIN_RE = re.compile(r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b')
SHA256_RE = re.compile(r'\b[0-9a-fA-F]{64}\b')
SHA1_RE = re.compile(r'\b[0-9a-fA-F]{40}\b')
MD5_RE = re.compile(r'\b[0-9a-fA-F]{32}\b')
FILEPATH_RE = re.compile(r'[a-zA-Z]:\\(?:[^\\"]+\\)*[^\\"]+\.\w+')


def _match_all(text: str) -> dict:
    """对单个字符串提取所有 IOC 类型."""
    return {
        "ips": list(set(m.group() for m in IPV4_RE.finditer(text))),
        "domains": list(set(m.group() for m in DOMAIN_RE.finditer(text) if '.' in m.group())),
        "md5": list(set(m.group() for m in MD5_RE.finditer(text) if not SHA256_RE.match(m.group()))),
        "sha1": list(set(m.group() for m in SHA1_RE.finditer(text) if not SHA256_RE.match(m.group()))),
        "sha256": list(set(m.group() for m in SHA256_RE.finditer(text))),
        "file_paths": list(set(m.group() for m in FILEPATH_RE.finditer(text))),
    }


def _merge(dest: dict, src: dict):
    for k in dest:
        dest[k].extend(src.get(k, []))


def extract_iocs(data: Any, max_depth: int = 5, _depth: int = 0) -> dict:
    """从任意嵌套结构（dict/list/str）中递归提取 IOC.

    Args:
        data: 待提取的数据（通常为 security_events.evidence）.
        max_depth: 最大递归深度.

    Returns:
        {"ips": [...], "domains": [...], "md5": [...], "sha1": [...], "sha256": [...], "file_paths": [...]}
    """
    result = {"ips": [], "domains": [], "md5": [], "sha1": [], "sha256": [], "file_paths": []}

    def _recurse(val: Any, depth: int):
        if depth > max_depth:
            return
        if isinstance(val, dict):
            for v in val.values():
                _recurse(v, depth + 1)
        elif isinstance(val, list):
            for item in val:
                _recurse(item, depth + 1)
        elif isinstance(val, str):
            _merge(result, _match_all(val))

    _recurse(data, _depth)

    # 去重
    for k in result:
        seen = set()
        deduped = []
        for item in result[k]:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        result[k] = deduped

    return result
