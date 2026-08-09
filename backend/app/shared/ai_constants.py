"""AI分析模块共享常量定义.

包含任务状态、断路器状态、审计日志状态、脱敏规则、Token预算策略等.
"""

import re
from enum import Enum
from typing import Optional


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


# ============================================================
# v1.3.0「AI 分析作战化」关键常量（评分可信化 / 基线降噪 / 稀有提级）
# 集中定义，运营可改、不散落。
# ============================================================

# 评分信号权重（可扩展）。risk_score 权威 = sum(score_breakdown.contribution)。
SCORE_WEIGHTS: dict[str, int] = {
    "malicious_behavior": 30,   # 恶意行为
    "persistence": 15,          # 持久化
    "c2_external": 10,          # 外连 C2
    "lateral_movement": 10,     # 横向移动
    "defense_evasion": 10,      # 防御规避
    "privilege_escalation": 10, # 提权
    "data_exfiltration": 10,    # 数据渗出
    "reconnaissance": 5,        # 侦察
    "other": 5,                 # 其他
}

# 风险等级阈值（0-100 整数分）
RISK_SCORE_THRESHOLD_HIGH: int = 60   # >= 60 高危
RISK_SCORE_THRESHOLD_MID: int = 30    # 30-59 中危；< 30 低危/安全

# 输入质量阈值（P2 预留，本期仅定义常量；自动重算留 v1.3.1）
INPUT_QUALITY_THRESHOLD: int = 60

# 基线降噪系数：historical_known=true 的 score_breakdown 项贡献乘以该系数（即下调 50%）。
BASELINE_PENALTY: float = 0.5

# 稀有高危信号清单：命中其一即强制 P0 + 独立高亮卡 + escalation_conditions 触发。
RARE_HIGH_SIGNALS: list[str] = [
    "wmi_subscription",
    "fileless_powershell",
    "anomalous_service",
    "hidden_scheduled_task",
    "reflective_dll_injection",
    "amsi_bypass",
    "registry_hive_dump",
    "shadow_copy_deletion",
    "dns_over_https_tunnel",
    "kernel_driver_without_signature",
]

# 受众默认值
AUDIENCE_DEFAULT: str = "both"  # both | technical | executive


# ---- 降级消息模板 — 当 AI 摘要未生成时各 Agent 统一使用此文案（P1-5）----
# 注意：模板含 {reason} 占位符，禁止直接做 f-string 插值，
# 必须经 build_degraded_message() 格式化，否则页面会出现 "{reason}" 字面量。
DEGRADED_REASON_UNKNOWN: str = "未知原因"

DEGRADED_MESSAGE_TEMPLATE = (
    "AI 摘要未生成（原因：{reason}），以上结论基于真实数据自动生成"
)


def build_degraded_message(reason: Optional[str] = None) -> str:
    """格式化降级横幅，reason 为空时回退到默认文案（P1-5）。

    Args:
        reason: 降级原因（来自 ``AgentLLM._degraded`` 的 error，或 agent 捕获的异常摘要）。

    Returns:
        可直接拼入 Agent 正文的横幅文本。
    """
    text = (reason or "").strip() or DEGRADED_REASON_UNKNOWN
    return DEGRADED_MESSAGE_TEMPLATE.format(reason=text[:120])


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
