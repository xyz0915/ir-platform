"""Agent 端资源预算常量（融合方案 §4.2，已拍板采纳）.

集中定义采集端开销上限，供各采集器复用，保证 Agent 在高频主机上的可控开销：
- ETW / 事件流批量 flush：每 5s 或满 500 条上报一次；
- ``memory_sections`` 降采样：仅对解释器 / 年轻进程(<60s) / 无签名进程采集，单进程区段上限 ≤64；
- Web 目录扫描：文件 ≤5MB 读全文，更大读头尾各 64KB + 均匀采样；文件数超阈值采样；
- 单 Agent 上报体量上限默认 16 MB（可配置）。
"""

from typing import Optional

# ── 事件流批量上报（Mode B）─────────────────────────────────────────
EVENT_FLUSH_INTERVAL_SEC: int = 5          # 每 5s flush 一次到 /process-events
EVENT_FLUSH_BATCH_SIZE: int = 500         # 或满 500 条 flush 一次

# ── memory_sections 降采样（仅解释器 / 年轻<60s / 无签名进程）────────
MEM_SECTION_MAX_PER_PROCESS: int = 64      # 单进程区段上限 ≤64
YOUNG_PROCESS_THRESHOLD_SEC: int = 60      # 年轻进程阈值（启动 <60s）

# ── Web 目录扫描 ─────────────────────────────────────────────────
WEBSHELL_FULL_READ_BYTES: int = 5 * 1024 * 1024          # ≤5MB 文件读全文
WEBSHELL_HEAD_TAIL_BYTES: int = 64 * 1024                 # 大文件头尾各 64KB
WEBSHELL_SAMPLE_CHUNK_BYTES: int = 4 * 1024               # 均匀采样块大小
WEBSHELL_MAX_FILES_PER_ROOT: int = 2000                  # 单 web 根文件数阈值（超则采样）

# ── 单 Agent 上报体量上限（默认 16MB，可经环境变量覆盖）─────────────
import os as _os

_DEFAULT_MAX_REPORT_MB = _os.environ.get("IR_AGENT_MAX_REPORT_MB")
MAX_REPORT_BYTES: int = (
    int(_DEFAULT_MAX_REPORT_MB) * 1024 * 1024
    if _DEFAULT_MAX_REPORT_MB and _DEFAULT_MAX_REPORT_MB.isdigit()
    else 16 * 1024 * 1024
)

# 支持的 WebShell / 内存马相关文件扩展名
WEBSHELL_EXTENSIONS = (".php", ".php3", ".php4", ".php5", ".phtml",
                       ".jsp", ".jspx", ".asp", ".aspx", ".war", ".jspf")
# 解释器进程名（用于 memory_sections 降采样判定）
INTERPRETER_NAMES = frozenset({
    "java", "python", "python3", "perl", "ruby", "node", "php", "php-fpm",
    "powershell", "pwsh", "lua", "ruby",
})


def is_young_process(start_time: Optional[str], threshold_sec: int = YOUNG_PROCESS_THRESHOLD_SEC) -> bool:
    """判断进程是否年轻（启动时间距当前 < threshold_sec）.

    Args:
        start_time: ISO 8601 启动时间字符串（可能为空）.
        threshold_sec: 年轻阈值（秒）.

    Returns:
        无法解析或为空时返回 False（保守：不视为年轻，避免误采）。
    """
    if not start_time:
        return False
    try:
        from datetime import datetime, timezone
        try:
            ts = datetime.fromisoformat(start_time)
        except ValueError:
            # 兼容无时区后缀的情况
            ts = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return 0 <= age < threshold_sec
    except (ValueError, TypeError, OSError):
        return False
