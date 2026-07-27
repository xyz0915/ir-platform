"""平台检测与工具函数."""

import logging
import platform as _platform
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 统一目标时区：UTC+8
TARGET_TZ = timezone(timedelta(hours=8))


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


def _parse_dotnet_date(ts: str) -> Optional[str]:
    """解析 .NET ``/Date(ms)/`` 格式时间戳.

    Args:
        ts: 形如 ``/Date(1785118871000)/`` 的字符串.

    Returns:
        ISO 8601 格式时间字符串（带 UTC+8 时区），解析失败返回 None.
    """
    try:
        match = re.match(r'/Date\((-?\d+)\)/', ts.strip())
        if not match:
            return None
        ms = int(match.group(1))
        # 使用 timedelta 代替 fromtimestamp，避免负数时间戳在 Windows 上抛 OSError
        unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        dt = unix_epoch + timedelta(seconds=ms / 1000.0)
        # 转为 UTC+8
        dt = dt.astimezone(TARGET_TZ)
        return dt.isoformat()
    except (ValueError, OSError, OverflowError) as exc:
        logger.warning("Failed to parse .NET date '%s': %s", ts, exc)
        return None


def _parse_chrome_epoch(ts: str) -> Optional[str]:
    """解析 Chrome epoch（1601-01-01 微秒计数）时间戳.

    Chrome/Firefox 使用 WebKit 时间：自 1601-01-01 UTC 以来的微秒数.

    Args:
        ts: 数字字符串，如 ``132626567210000000``.

    Returns:
        ISO 8601 格式时间字符串（带 UTC+8 时区），解析失败返回 None.
    """
    try:
        microseconds = int(ts)
        # Chrome epoch 起始：1601-01-01 UTC
        chrome_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        dt = chrome_epoch + timedelta(microseconds=microseconds)
        dt = dt.astimezone(TARGET_TZ)
        return dt.isoformat()
    except (ValueError, OSError, OverflowError) as exc:
        logger.warning("Failed to parse Chrome epoch '%s': %s", ts, exc)
        return None


def _get_local_timezone() -> timezone:
    """获取当前系统的本地时区偏移."""
    now = datetime.now().astimezone()
    return now.tzinfo  # type: ignore[return-value]


def normalize_timestamp(ts: Any, source: str = "") -> str:
    """统一格式化时间戳：输入任意格式 → ISO 8601 带 UTC+8 时区.

    支持的输入格式：
      - ``2026-07-27T10:21:47``          → 加系统时区
      - ``2026-07-27T10:21:47+08:00``    → 保持（转为 UTC+8���
      - ``2026-07-27 10:21:47``          → 替换空格为 T + 加时区
      - ``/Date(1785118871000)/``         → .NET 格式
      - ``132626567210000000``            → Chrome epoch（需 17+ 位数字）
      - ``""`` / ``None``                 → 返回 ``""``

    Args:
        ts: 任意格式的时间戳.
        source: 来源标记（如采集器名），用于日志.

    Returns:
        标准化后的 ISO 8601 时间字符串（带 UTC+8 时区）.
        解析失败返回原值（不抛异常）.
    """
    if not ts:
        return ""

    ts_str = str(ts).strip()
    if not ts_str:
        return ""

    # ── 已包含时区信息的 ISO 8601（带 +/- 或 Z） ──
    if re.search(r'[+-]\d{2}:\d{2}$', ts_str) or ts_str.endswith('Z'):
        try:
            # 处理末尾 Z → +00:00
            normalized = ts_str
            if normalized.endswith('Z'):
                normalized = normalized[:-1] + '+00:00'
            dt = datetime.fromisoformat(normalized)
            dt = dt.astimezone(TARGET_TZ)
            return dt.isoformat()
        except (ValueError, TypeError):
            pass

    # ── .NET /Date(ms)/ 格式 ──
    if '/Date(' in ts_str:
        result = _parse_dotnet_date(ts_str)
        if result:
            return result

    # ── Chrome epoch（17+ 位纯数字） ──
    # 2026 年的 Unix ms ≈ 1.78e12（13 位），Chrome epoch ≈ 1.32e17（18 位）
    if re.match(r'^\d{17,}$', ts_str):
        result = _parse_chrome_epoch(ts_str)
        if result:
            return result

    # ── 空格分隔格式：2026-07-27 10:21:47 ──
    if ' ' in ts_str:
        # 检查是否类似 ISO 日期+时间（日期部分 + 空格 + 时间部分）
        space_match = re.match(
            r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)$',
            ts_str,
        )
        if space_match:
            iso_str = f"{space_match.group(1)}T{space_match.group(2)}"
            try:
                dt = datetime.fromisoformat(iso_str)
                # 无时区 → 假设本地时区
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_get_local_timezone())
                dt = dt.astimezone(TARGET_TZ)
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

    # ── ISO 8601 无时区：2026-07-27T10:21:47 ──
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_get_local_timezone())
        dt = dt.astimezone(TARGET_TZ)
        return dt.isoformat()
    except (ValueError, TypeError):
        pass

    # ── 纯日期格式：2026-07-27 ──
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d")
        dt = dt.replace(tzinfo=_get_local_timezone())
        dt = dt.astimezone(TARGET_TZ)
        return dt.isoformat()
    except (ValueError, TypeError):
        pass

    # ── 所有解析均失败 → 记录警告，返回原值 ──
    logger.warning(
        "normalize_timestamp: unable to parse '%s' (source=%s), keeping original",
        ts_str, source,
    )
    return ts_str


def to_utc8(dt: datetime) -> str:
    """将 datetime 对象统一转为 UTC+8 并返回 ISO 格式字符串.

    Args:
        dt: 待转换的 datetime 对象。无时区时假设为本地时区.

    Returns:
        ISO 8601 格式时间字符串（带 +08:00 时区）.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_get_local_timezone())
    dt = dt.astimezone(TARGET_TZ)
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
