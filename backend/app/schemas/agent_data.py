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

    class Config:
        extra = "allow"
