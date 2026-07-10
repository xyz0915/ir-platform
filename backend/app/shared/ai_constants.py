"""AI分析模块共享常量定义.

包含任务状态、断路器状态、审计日志状态、脱敏规则、Token预算策略等.
"""

import re
from enum import Enum


class TaskStatus(str, Enum):
    """异步任务状态枚举."""
    PENDING = "pending"          # 已提交，等待执行
    RUNNING = "running"          # 执行中
    COMPLETED = "completed"      # 成功完成
    FAILED = "failed"            # 执行失败
    CANCELLED = "cancelled"      # 用户取消


class CircuitBreakerState(str, Enum):
    """断路器状态枚举."""
    CLOSED = "CLOSED"            # 正常通行
    OPEN = "OPEN"                # 熔断拒绝（5分钟）
    HALF_OPEN = "HALF_OPEN"      # 半开试探


class AuditLogStatus(str, Enum):
    """审计日志状态枚举."""
    SUCCESS = "success"          # 调用成功
    FAILED = "failed"            # 调用失败（含重试耗尽）
    CANCELLED = "cancelled"      # 用户取消


class AIMode(str, Enum):
    """AI 分析模式枚举（统一在 ai_constants 定义，供任务分派/前端复用）.

    - STANDARD   标准全量分析
    - DEEP_DIVE  深挖模式（聚焦单一维度/线索）
    - MODULE     模块级分析（按 focus_area 指定模块）
    - OVERVIEW   全貌分析：还原攻击故事线（story_line）
    - REMEDIATION 处置建议：生成可审核但绝不自动执行的处置脚本
    """

    STANDARD = "standard"
    DEEP_DIVE = "deep_dive"
    MODULE = "module"
    OVERVIEW = "overview"
    REMEDIATION = "remediation"

    @classmethod
    def values(cls) -> list[str]:
        """返回所有合法模式字符串列表."""
        return [m.value for m in cls]


# Token 预算策略 (默认 128K 上下文)
AI_CONTEXT_WINDOW: int = 128000
AI_INPUT_BUDGET: int = 80000
AI_OUTPUT_RESERVE: int = 16000

# 数据优先级排序（用于 prompt 构建时截断决策）
DATA_PRIORITY_ORDER: list[str] = [
    "host_basic",
    "analysis_result",
    "ioc_hits",
    "abnormal_processes",
    "suspicious_connections",
    "timeline",
    "persistence",
    "profile",
]


# ---- 脱敏规则 ----


def mask_ipv4(ip: str) -> str:
    """脱敏 IPv4 地址: 192.168.1.100 -> 192.168.*.*"""
    parts = ip.split(".")
    if len(parts) == 4:
        parts[2] = "*"
        parts[3] = "*"
        return ".".join(parts)
    return ip


def mask_ipv6(ip: str) -> str:
    """脱敏 IPv6 地址: 截断为前两段."""
    parts = ip.split(":")
    if len(parts) >= 2:
        return ":".join(parts[:2]) + ":****"
    return ip


def mask_ip(ip: str) -> str:
    """自动判断 IPv4/IPv6 并脱敏."""
    if not ip:
        return ip
    if ":" in ip:
        return mask_ipv6(ip)
    if "." in ip:
        return mask_ipv4(ip)
    return ip


def mask_path(path: str) -> str:
    """脱敏路径: C:\\Users\\admin\\恶意.exe -> C:\\Users\\***\\恶意.exe

    只脱敏文件名之前的最后一个目录名（通常是用户名）.
    """
    if not path:
        return path
    is_windows = "\\" in path
    parts = path.replace("\\", "/").split("/")
    if len(parts) >= 3:
        # 脱敏倒数第二个元素（文件名前的目录）
        parts[-2] = "***"
    masked = "/".join(parts)
    if is_windows:
        masked = masked.replace("/", "\\")
    return masked


def mask_username(username: str) -> str:
    """脱敏用户名: admin -> a***n"""
    if not username or len(username) <= 2:
        return username
    return username[0] + "***" + username[-1]


def mask_domain(domain: str) -> str:
    """脱敏域名: evil.com -> e***.com"""
    if not domain or "." not in domain:
        return domain
    parts = domain.split(".")
    if len(parts) >= 2:
        name = parts[0]
        if len(name) > 1:
            parts[0] = name[0] + "***"
        else:
            parts[0] = name + "***"
    return ".".join(parts)


def apply_masking(text: str, fields_to_mask: list[str] | None = None) -> str:
    """对文本中的敏感字段进行脱敏.

    Args:
        text: 需要脱敏的文本.
        fields_to_mask: 需要脱敏的字段名列表，None 表示脱敏所有已知字段.

    Returns:
        脱敏后的文本.
    """
    if not text:
        return text

    # 默认脱敏所有 IP 和路径模式
    # IPv4 模式
    ipv4_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

    def _replace_ipv4(m: re.Match) -> str:
        return mask_ipv4(m.group(1))

    text = ipv4_pattern.sub(_replace_ipv4, text)

    # 常见路径模式
    path_pattern = re.compile(r'([A-Za-z]:\\[^\s,;"]+)')

    def _replace_path(m: re.Match) -> str:
        return mask_path(m.group(1))

    text = path_pattern.sub(_replace_path, text)

    return text
