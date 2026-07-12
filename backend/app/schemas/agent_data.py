"""Agent JSON Schema 定义 — Pydantic 模型用于导入校验.

对应架构文档 3.2 节的 Agent 输出 JSON Schema.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    """Agent 元数据."""
    agent_version: str = "1.1.0"
    collection_time: str = ""
    platform: str = "unknown"
    hostname: str = "unknown"
    operator: str = "agent"
    log_days: int = 7

    class Config:
        extra = "allow"


class CpuInfo(BaseModel):
    """CPU 信息."""
    model: Optional[str] = None
    cores: Optional[int] = None
    logical_cores: Optional[int] = None


class MemoryInfo(BaseModel):
    """内存信息."""
    total_gb: Optional[float] = None
    available_gb: Optional[float] = None


class DiskInfo(BaseModel):
    """磁盘信息."""
    device: Optional[str] = None
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None
    fs_type: Optional[str] = None


class SystemInfo(BaseModel):
    """系统基础信息."""
    hostname: Optional[str] = None
    os: Optional[str] = None
    os_version: Optional[str] = None
    architecture: Optional[str] = None
    install_date: Optional[str] = None
    uptime_seconds: Optional[int] = None
    timezone: Optional[str] = None
    cpu: Optional[CpuInfo] = None
    memory: Optional[MemoryInfo] = None
    disks: list[DiskInfo] = Field(default_factory=list)


class UserInfo(BaseModel):
    """用户信息."""
    username: Optional[str] = None
    uid: Optional[int] = None
    home_dir: Optional[str] = None
    last_logon: Optional[str] = None
    is_admin: Optional[bool] = None
    is_disabled: Optional[bool] = None


class ProcessInfo(BaseModel):
    """进程信息."""
    pid: Optional[int] = None
    ppid: Optional[int] = None
    name: Optional[str] = None
    path: Optional[str] = None
    command_line: Optional[str] = None
    user: Optional[str] = None
    start_time: Optional[str] = None
    threads: Optional[int] = None
    connections: list = Field(default_factory=list)
    # T14/P2 扩展字段（均 Optional，向后兼容；配合 extra="allow" 可承载更多 Agent 端数据）
    session: Optional[int] = None          # 会话 ID（跨会话父子检测 cross_session 使用）
    memory_sections: Optional[list] = None  # 内存节区（fileless/反射注入检测 memory_injection 使用）
    state: Optional[str] = None            # 进程状态（如 Running/Suspended，可选）

    class Config:
        extra = "allow"  # 向后兼容：Agent 端新增字段（whitelisted/parent_name/...）不报错


class ServiceInfo(BaseModel):
    """服务信息."""
    name: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None
    start_type: Optional[str] = None
    binary_path: Optional[str] = None
    account: Optional[str] = None


class StartupItem(BaseModel):
    """启动项信息."""
    name: Optional[str] = None
    command: Optional[str] = None
    location: Optional[str] = None
    user: Optional[str] = None
    type: Optional[str] = None


class NetworkConnection(BaseModel):
    """网络连接信息."""
    protocol: Optional[str] = None
    local_address: Optional[str] = None
    local_port: Optional[int] = None
    remote_address: Optional[str] = None
    remote_port: Optional[int] = None
    state: Optional[str] = None
    pid: Optional[int] = None
    process_name: Optional[str] = None


class NetworkInterface(BaseModel):
    """网卡接口信息."""
    name: Optional[str] = None
    ip: Optional[str] = None
    mac: Optional[str] = None
    netmask: Optional[str] = None
    gateway: Optional[str] = None


class DnsCacheEntry(BaseModel):
    """DNS 缓存条目."""
    domain: Optional[str] = None
    type: Optional[str] = None
    value: Optional[str] = None
    ttl: Optional[int] = None


class NetworkInfo(BaseModel):
    """网络信息."""
    connections: list[NetworkConnection] = Field(default_factory=list)
    interfaces: list[NetworkInterface] = Field(default_factory=list)
    dns_cache: list[DnsCacheEntry] = Field(default_factory=list)
    hosts_file: Optional[str] = None
    routing_table: list[dict] = Field(default_factory=list)


class AgentData(BaseModel):
    """Agent JSON 输出完整 Schema.

    用于导入时校验 JSON 数据格式.
    """
    metadata: AgentMetadata = Field(default_factory=AgentMetadata)
    system_info: Any = Field(default_factory=dict)
    users: list[Any] = Field(default_factory=list)
    processes: list[Any] = Field(default_factory=list)
    services: list[Any] = Field(default_factory=list)
    startup_items: list[Any] = Field(default_factory=list)
    network: Any = Field(default_factory=dict)
    files: Any = Field(default_factory=dict)
    registry: Any = Field(default_factory=dict)
    logs: Any = Field(default_factory=dict)
    security: Any = Field(default_factory=dict)
    browser: Any = Field(default_factory=dict)
    usb: Any = Field(default_factory=dict)
    remote_control: Any = Field(default_factory=dict)
    persistence: Any = Field(default_factory=dict)
    ioc: Any = Field(default_factory=dict)
    timeline: list[Any] = Field(default_factory=list)
    network_connections: list[Any] = Field(default_factory=list)
    file_hashes: list[Any] = Field(default_factory=list)
    wmi_subscriptions: list[Any] = Field(default_factory=list)
    registry_keys: list[Any] = Field(default_factory=list)
    # 融合扩充（A §2.2）：WebShell 文件型检测与内存码（Java 内存马 / PHP 扩展）检测。
    # 使用宽松模型（list[Any] + extra="allow"），老 Agent 不产出这些键时照常入库，
    # 新字段缺失时规则优雅降级（与 processes 同风格）。
    webshells: list[Any] = Field(default_factory=list)
    memory_shells: list[Any] = Field(default_factory=list)

    class Config:
        extra = "allow"


class MemorySection(BaseModel):
    """进程内存区段（融合统一契约 §2.1）.

    合并 B 注入/PE 痕迹 + A 内存马/JVM 语义。宽松模型（``extra="allow"``）：
    Agent 端新增的区段子字段不报错，下游规则缺字段时由各自 ``_match_*`` 降级返回 False。
    """

    base_address: Optional[str] = None
    end_address: Optional[str] = None
    size: Optional[int] = None
    protection: Optional[str] = None          # R / RW / RX / RWX / ...
    type: Optional[str] = None                # mem_image | image | heap | stack | mapped | pe | jvm_generated
    is_non_image: Optional[bool] = None       # 非镜像映射（无文件背景）
    pe_in_memory: Optional[bool] = None        # 内存中 PE（无文件落盘）
    injection: Optional[bool] = None           # 注入标志（RWX 匿名 / 反射加载）
    is_anonymous_rwx: Optional[bool] = None    # 匿名可执行映射（shellcode 启发式）
    mapped_path: Optional[str] = None          # 有文件背景时；匿名时为 null
    jvm: Optional[Any] = None                  # JVM 层语义（class_signals/agent_signals/...）
    evidence: Optional[str] = None
    confidence: Optional[float] = None

    class Config:
        extra = "allow"


class WebShell(BaseModel):
    """WebShell 文件型证据（融合契约 §2.2）.

    宽松模型（``extra="allow"``）兼容老 Agent / 不同采集端拓展字段。
    """

    path: Optional[str] = None
    name: Optional[str] = None
    size: Optional[int] = None
    mtime: Optional[str] = None
    ctime: Optional[str] = None
    owner: Optional[str] = None
    perms: Optional[str] = None
    sha256: Optional[str] = None
    web_root: Optional[str] = None
    middleware: Optional[str] = None
    suspicious_funcs: Optional[list] = None
    obfuscation_score: Optional[float] = None
    behinder_godzilla_signal: Optional[bool] = None
    risk_score: Optional[float] = None
    scan_engine: Optional[str] = None

    class Config:
        extra = "allow"


class MemoryShell(BaseModel):
    """内存码证据（Java 内存马 / PHP 扩展，融合契约 §2.2）.

    ``pid`` 为与进程富化的关联锚点；宽松模型（``extra="allow"``）兼容拓展字段。
    """

    pid: Optional[int] = None
    process_name: Optional[str] = None
    type: Optional[str] = None                 # java_filter | java_agent | php | unknown
    evidence: Optional[str] = None
    class_signals: Optional[list] = None
    agent_signals: Optional[list] = None
    conn_signals: Optional[list] = None
    thread_signals: Optional[list] = None
    confidence: Optional[float] = None
    detect_method: Optional[str] = None

    class Config:
        extra = "allow"
