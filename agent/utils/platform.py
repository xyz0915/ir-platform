"""平台检测与工具函数."""

import logging
import platform as _platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_windows() -> bool:
    """检测当前是否为 Windows 平台."""
    return _platform.system() == "Windows"


def is_linux() -> bool:
    """检测当前是否为 Linux 平台."""
    return _platform.system() == "Linux"


def get_platform_name() -> str:
    """获取平台名称."""
    if is_windows():
        return "windows"
    if is_linux():
        return "linux"
    return "unknown"


def _get_system_encoding() -> str:
    """获取系统默认编码.

    Windows 中文系统使用 GBK/CP936，Linux 通常 UTF-8.
    """
    import locale
    if is_windows():
        # Windows 中文系统默认 GBK (cp936)
        try:
            enc = locale.getpreferredencoding()
            if enc and enc.lower().startswith("cp"):
                return enc
        except Exception:
            pass
        return "gbk"
    return "utf-8"


SYSTEM_ENCODING = _get_system_encoding()


def run_command(cmd: str, timeout: int = 30) -> str:
    """安全执行系统命令并返回输出.

    Args:
        cmd: 要执行的命令字符串.
        timeout: 命令超时时间（秒）.

    Returns:
        命令的标准输出（已去除首尾空白），失败时返回空字符串.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding=SYSTEM_ENCODING,
            errors="replace",
        )
        output = result.stdout
        if output is None:
            return ""
        return output.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out: %s", cmd)
        return ""
    except Exception as exc:
        logger.warning("Command failed: %s -> %s", cmd, exc)
        return ""


def run_command_list(cmd_list: list, timeout: int = 30) -> str:
    """安全执行系统命令（列表形式）并返回输出.

    Args:
        cmd_list: 命令及参数列表（如 ["netstat", "-ano"]）.
        timeout: 命令超时时间（秒）.

    Returns:
        命令的标准输出，失败时返回空字符串.
    """
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding=SYSTEM_ENCODING,
            errors="replace",
        )
        output = result.stdout
        if output is None:
            return ""
        return output.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out: %s", cmd_list)
        return ""
    except Exception as exc:
        logger.warning("Command failed: %s -> %s", cmd_list, exc)
        return ""


def read_file_safe(path: str, encoding: str = "utf-8") -> Optional[str]:
    """安全读取文件内容.

    Args:
        path: 文件路径.
        encoding: 文件编码.

    Returns:
        文件内容字符串，失败时返回 None.
    """
    try:
        with open(path, "r", encoding=encoding) as f:
            return f.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        logger.debug("Failed to read file %s: %s", path, exc)
        return None


def read_file_lines_safe(path: str, encoding: str = "utf-8") -> list:
    """安全读取文件行列表.

    Args:
        path: 文件路径.
        encoding: 文件编码.

    Returns:
        文件行列表，失败时返回空列表.
    """
    content = read_file_safe(path, encoding)
    if content is None:
        return []
    return content.splitlines()


def get_timestamp() -> str:
    """返回 ISO 8601 格式的当前时间戳."""
    return datetime.now().astimezone().isoformat()


def format_timestamp(dt: datetime) -> str:
    """将 datetime 对象格式化为 ISO 8601 字符串.

    Args:
        dt: datetime 对象.

    Returns:
        ISO 8601 格式的时间字符串.
    """
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """安全转换为整数."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
