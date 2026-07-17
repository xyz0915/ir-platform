"""格式检测器 — 三级检测策略：扩展名 → Magic Bytes → 内容特征.

核心类 FormatDetector 通过静态方法 detect() 统一入口，
返回 (log_source, detected_format) 二元组。

关联：
    - access_log_parser.FORMAT_TEMPLATES 用于第三级内容特征匹配
"""

import logging
import re
from pathlib import Path
from typing import Optional

from app.parsers.access_log_parser import FORMAT_TEMPLATES

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """不支持的日志格式异常."""

    def __init__(self, filename: str, reason: str = ""):
        self.filename = filename
        self.reason = reason
        super().__init__(f"Unsupported log format: {filename} — {reason}")


# ── Access Log 内容特征模式（供第三级检测用）───────────────
# 仅用于格式检测 vs. 完整解析，正则更宽松
ACCESS_LOG_PATTERNS: dict[str, Optional[str]] = {
    # ... 现有 Access Log 模式保持不变 ...
    "nginx_combined": (
        r'^(?P<src_ip>\S+)\s+\S+\s+\S+\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<url>\S+)\s+\S+"\s+'
        r'(?P<status_code>\d+)\s+\d+\s+'
        r'"(?P<referer>[^"]*)"\s+'
        r'"(?P<user_agent>[^"]*)"'
    ),
    "nginx_common": (
        r'^(?P<src_ip>\S+)\s+\S+\s+\S+\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<url>\S+)\s+\S+"\s+'
        r'(?P<status_code>\d+)\s+\d+'
    ),
    "iis_w3c_auto": None,  # 动态构建，由 #Fields: 行判定
    # Syslog
    "syslog_rfc3164": r"^<\d{1,3}>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+?:",
    "syslog_rfc5424": r"^<\d{1,3}>\d+\s+\S+",
}


class FormatDetector:
    """格式检测器 — 三级检测策略."""

    # 扩展名 → log_source 映射
    EXTENSION_MAP: dict[str, str] = {
        ".evtx": "evtx",
        ".evt": "evtx",
        ".log": "unknown",
        ".txt": "unknown",
    }

    # EVTX Magic Bytes
    EVTX_MAGIC = b"ElfFile\x00"

    @classmethod
    def detect(
        cls,
        filename: str,
        file_header_bytes: Optional[bytes] = None,
        first_lines: Optional[list[str]] = None,
    ) -> tuple[str, str]:
        """三级检测策略：扩展名 → Magic Bytes → 内容特征.

        Args:
            filename: 文件名（含扩展名）。
            file_header_bytes: 文件头字节（通常前 16 字节），可选。
            first_lines: 文件前几行文本，可选。

        Returns:
            tuple[str, str]: (log_source, detected_format)。
                log_source 如 'evtx', 'nginx_access', 'apache_access' 等。

        Raises:
            UnsupportedFormatError: 无法识别格式时抛出。
        """
        # 第一级：扩展名检测
        result = cls._check_extension(filename)
        if result and result != "unknown":
            fmt = result
            if fmt == "evtx":
                return fmt, fmt
            # unknown 继续下一级

        # 第二级：Magic Bytes 检测
        if file_header_bytes:
            result = cls._check_magic_bytes(file_header_bytes)
            if result:
                return result, result

        # 第三级：内容特征检测
        if first_lines:
            result = cls._check_access_log_format(first_lines)
            if result:
                # 将格式名（如 nginx_combined, nginx_common）映射为 log_source（如 nginx_access）
                base_name = result.split("_")[0]  # "nginx", "apache", "iis"
                log_source = f"{base_name}_access"
                return log_source, result
            # 尝试 IIS W3C 头检测
            if cls._check_iis_w3c_header(first_lines):
                return "iis_access", "iis_w3c"

        raise UnsupportedFormatError(filename, "No matching format found after 3-level detection")

    @classmethod
    def _check_extension(cls, filename: str) -> Optional[str]:
        """第一级：扩展名检测.

        Args:
            filename: 文件名。

        Returns:
            str | None: 对应的 log_source 或 None。
        """
        ext = Path(filename).suffix.lower()
        return cls.EXTENSION_MAP.get(ext)

    @classmethod
    def _check_magic_bytes(cls, data: bytes) -> Optional[str]:
        """第二级：Magic Bytes 检测.

        Args:
            data: 文件头字节。

        Returns:
            str | None: 格式名称或 None。
        """
        if data[:8] == cls.EVTX_MAGIC:
            return "evtx"
        return None

    @classmethod
    def _check_access_log_format(cls, first_lines: list[str]) -> Optional[str]:
        """第三级：内容特征检测（Access Log 格式）.

        遍历 ACCESS_LOG_PATTERNS 匹配首行，返回格式名或 None。

        Args:
            first_lines: 文件前几行文本。

        Returns:
            str | None: 格式名称（如 'nginx_combined'）。
        """
        for line in first_lines:
            stripped = line.strip()
            if not stripped:
                continue

            for fmt_name, pattern in ACCESS_LOG_PATTERNS.items():
                if pattern is None:
                    continue
                m = re.match(pattern, stripped)
                if m:
                    return fmt_name

        return None

    @classmethod
    def _check_iis_w3c_header(cls, first_lines: list[str]) -> bool:
        """检测是否包含 IIS W3C 头行.

        Args:
            first_lines: 文件前几行文本。

        Returns:
            bool: 是否包含 IIS W3C 头。
        """
        for line in first_lines:
            stripped = line.strip()
            if stripped.startswith("#Software:") or stripped.startswith("#Fields:"):
                return True
            if stripped.startswith("#"):
                continue
            # 非注释行则不再继续
            break
        return False


def detect_encoding(file_path: str) -> str:
    """检测文件编码. 返回 'utf-8', 'utf-16-le', 'gbk' 等.

    先尝试用 chardet 库检测，失败则用 try/except 兜底方案。

    Args:
        file_path: 文件路径.

    Returns:
        str: 检测到的编码名称.
    """
    try:
        import chardet
        with open(file_path, "rb") as f:
            raw = f.read(4096)  # 读取前 4KB 用于检测
        if raw[:2] == b"\xff\xfe":
            return "utf-16-le"
        if raw[:2] == b"\xfe\xff":
            return "utf-16-be"
        result = chardet.detect(raw)
        enc = result.get("encoding", "utf-8").lower()
        # 映射常见编码名
        if enc in ("gb2312", "gbk", "gb18030", "gb2312"):
            return "gbk"
        if enc == "ascii":
            return "utf-8"
        return enc if enc in ("utf-8", "utf-16") else "utf-8"
    except Exception:
        return detect_encoding_fallback(file_path)


def detect_encoding_fallback(file_path: str) -> str:
    """兜底编码检测：顺序尝试常见编码，返回首个能解码的编码名.

    Args:
        file_path: 文件路径.

    Returns:
        str: 检测到的编码名称，默认 'utf-8'.
    """
    encodings = ["utf-8", "gbk", "utf-16-le", "utf-16-be"]
    with open(file_path, "rb") as f:
        raw = f.read(4096)
    for enc in encodings:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"  # 默认
