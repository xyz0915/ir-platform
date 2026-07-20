"""分析结果 Pydantic 模型."""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, root_validator

from app.rules.rule_engine import BEHAVIOR_PATTERNS, validate_behavior_pattern

# ── 枚举约束 ────────────────────────────────────────────────────────
SEVERITY_ENUM: List[str] = ["critical", "high", "medium", "low"]
RULE_TYPE_ENUM: List[str] = ["regex", "list", "threshold", "behavior", "composite", "exists", "attack_chain"]
IOC_TYPE_ENUM: List[str] = ["ip", "domain", "url", "hash", "cert"]

SeverityType = Literal["critical", "high", "medium", "low"]


class AnalysisResultResponse(BaseModel):
    """分析结果响应模型."""
    id: int
    host_id: int
    risk_level: str
    risk_score: int
    total_findings: int
    summary: Optional[str] = None
    details: Optional[Any] = None
    analyzed_at: str

    class Config:
        from_attributes = True


class HostProfileResponse(BaseModel):
    """主机画像响应模型."""
    id: int
    host_id: int
    cpu_info: Optional[str] = None
    memory_info: Optional[str] = None
    disk_info: Optional[str] = None
    network_info: Optional[str] = None
    installed_software: Optional[str] = None
    user_accounts: Optional[str] = None
    security_products: Optional[str] = None
    system_summary: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class TimelineEventResponse(BaseModel):
    """时间线事件响应模型."""
    id: int
    host_id: int
    timestamp: str
    event_type: Optional[str] = None
    source: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class IocHitResponse(BaseModel):
    """IOC 命中响应模型."""
    id: int
    host_id: int
    ioc_type: Optional[str] = None
    ioc_value: Optional[str] = None
    matched_in: Optional[str] = None
    context: Optional[str] = None
    severity: Optional[str] = None

    class Config:
        from_attributes = True


class PersistenceItemResponse(BaseModel):
    """持久化痕迹响应模型."""
    id: int
    host_id: int
    type: Optional[str] = None
    name: Optional[str] = None
    command: Optional[str] = None
    location: Optional[str] = None
    user: Optional[str] = None
    is_suspicious: int = 0
    reason: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class SuspiciousConnectionResponse(BaseModel):
    """可疑外连响应模型."""
    id: int
    host_id: int
    protocol: Optional[str] = None
    local_address: Optional[str] = None
    local_port: Optional[int] = None
    remote_address: Optional[str] = None
    remote_port: Optional[int] = None
    state: Optional[str] = None
    process_name: Optional[str] = None
    pid: Optional[int] = None
    reason: Optional[str] = None
    rule_name: Optional[str] = None
    severity: Optional[str] = None

    class Config:
        from_attributes = True


class AbnormalProcessResponse(BaseModel):
    """异常进程响应模型."""
    id: int
    host_id: int
    pid: Optional[int] = None
    process_name: Optional[str] = None
    process_path: Optional[str] = None
    command_line: Optional[str] = None
    parent_pid: Optional[int] = None
    parent_name: Optional[str] = None
    reason: Optional[str] = None
    rule_name: Optional[str] = None
    severity: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class RuleResponse(BaseModel):
    """规则响应模型."""
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    rule_type: Optional[str] = None
    condition: Optional[Any] = None
    severity: str = "medium"
    enabled: bool = True
    created_at: str
    updated_at: str
    # 本地化与来源字段（F-1）
    label: Optional[str] = None
    source: Optional[str] = None
    mitre_attack: Optional[str] = None

    class Config:
        from_attributes = True


class RuleCreate(BaseModel):
    """创建规则请求模型."""
    name: str
    category: str
    rule_type: str
    condition: dict
    severity: SeverityType = "medium"
    description: Optional[str] = None
    # 本地化中文展示名（F-2）；来源默认 'user'（用户创建）
    label: Optional[str] = None
    source: str = "user"


class RuleUpdate(BaseModel):
    """更新规则请求模型."""
    enabled: Optional[bool] = None
    condition: Optional[dict] = None
    severity: Optional[SeverityType] = None
    description: Optional[str] = None
    name: Optional[str] = None
    owner: Optional[str] = None
    label: Optional[str] = None
    mitre_attack: Optional[str] = None


class RuleResetResponse(BaseModel):
    """重置默认规则响应模型."""
    updated: int = 0
    inserted: int = 0
    preserved_user: int = 0
    message: str = "success"


# ── 条件结构校验（T-P1-7）─────────────────────────────────────────
class ConditionModel(BaseModel):
    """规则条件结构模型（宽松解析，按 rule_type 分支校验见 validate_condition）.

    所有字段均为可选，未列出的扩展字段通过 extra='allow' 保留，
    以兼容 behavior 规则的 min_chain_length / suspicious_*_patterns 等参数。
    """

    field: Optional[str] = None
    pattern: Optional[str] = None
    values: Optional[list] = None
    match_mode: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[Any] = None
    logic: Optional[str] = None
    sub_rules: Optional[List["ConditionModel"]] = None
    flags: Optional[str] = None
    description: Optional[str] = None
    mitre_attack: Optional[str] = None
    _meta: Optional[dict] = None
    # ── attack_chain 规则条件字段（任务①）──────────────────────────
    # ordered_steps: 有序步骤列表，每步含 dimension（跨维度）+ match（复用既有类型）
    # window_minutes: 攻击链首末步骤最大时间跨度（默认 60，上限 1440）
    # host_scope: "single"（默认，单主机下钻）— 预留集群级扩展
    window_minutes: Optional[int] = None
    host_scope: Optional[str] = None
    ordered_steps: Optional[List[dict]] = None

    class Config:
        extra = "allow"


# 解析自引用类型注解（sub_rules: List["ConditionModel"]）
ConditionModel.model_rebuild()


def validate_condition(rule_type: str, condition: dict) -> None:
    """按 rule_type 分支校验条件结构，非法时抛出 ValueError.

    Args:
        rule_type: 规则类型（regex/list/threshold/behavior/composite/exists）.
        condition: 条件字典.

    Raises:
        ValueError: 结构不合法（缺必填字段或 behavior pattern 非法）.
    """
    if not isinstance(condition, dict):
        raise ValueError("condition 必须是对象")

    # 1) 宽松结构解析（捕获字段类型错误，如 values 非列表）
    try:
        ConditionModel.parse_obj(condition)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"条件结构无效: {exc}")

    # 2) 按 rule_type 分支校验必填字段
    if rule_type == "regex":
        if not condition.get("field") or not condition.get("pattern"):
            raise ValueError("regex 规则必须包含 field 与 pattern")
    elif rule_type == "list":
        if not condition.get("field"):
            raise ValueError("list 规则必须包含 field")
        # 允许 values 为空列表：当 field 命中 FIELD_TO_IOC_TYPE 动态 IOC 映射时，
        # 引擎会在运行时从 iocs 表动态并入对应类型指标（如 TI_malware_hash 的
        # field=file_hash、attack_chain C2 步骤的 remote_address）。仅当 values
        # 键缺失（None）时才视为非法结构。
        if condition.get("values") is None:
            raise ValueError("list 规则必须包含 values（可为空列表以仅依赖动态 IOC 引用）")
    elif rule_type == "threshold":
        if not condition.get("field"):
            raise ValueError("threshold 规则必须包含 field")
        if condition.get("operator") is None:
            raise ValueError("threshold 规则必须包含 operator")
        if condition.get("value") is None:
            raise ValueError("threshold 规则必须包含 value")
    elif rule_type == "behavior":
        pattern = condition.get("pattern")
        if not pattern:
            raise ValueError("behavior 规则必须包含 pattern")
        if not validate_behavior_pattern(pattern):
            raise ValueError(
                f"非法 behavior pattern: '{pattern}'，不在引擎支持的 "
                f"{len(BEHAVIOR_PATTERNS)} 种白名单中"
            )
    elif rule_type == "composite":
        if not condition.get("sub_rules"):
            raise ValueError("composite 规则必须包含 sub_rules")
    elif rule_type == "exists":
        if not condition.get("field"):
            raise ValueError("exists 规则必须包含 field")
    elif rule_type == "attack_chain":
        # 跨维度顺序关联：ordered_steps 非空，每步含 dimension + match
        steps = condition.get("ordered_steps")
        if not isinstance(steps, list) or len(steps) == 0:
            raise ValueError("attack_chain 规则必须包含非空的 ordered_steps")
        valid_dims = {"process", "connection", "registry", "persistence", "timeline", "ioc"}
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"attack_chain 第 {idx + 1} 步必须是对象")
            dim = step.get("dimension")
            if dim not in valid_dims:
                raise ValueError(
                    f"attack_chain 第 {idx + 1} 步 dimension 非法: {dim!r}，"
                    f"应为 {sorted(valid_dims)}"
                )
            match = step.get("match")
            if not isinstance(match, dict) or not match.get("type"):
                raise ValueError(f"attack_chain 第 {idx + 1} 步必须包含 match.type")
            mtype = match.get("type")
            if mtype not in RULE_TYPE_ENUM:
                raise ValueError(
                    f"attack_chain 第 {idx + 1} 步 match.type 非法: {mtype!r}"
                )
        # window_minutes 可选，缺省 60；若提供须为 1..1440 的整数
        wm = condition.get("window_minutes")
        if wm is not None:
            if not isinstance(wm, int) or isinstance(wm, bool) or wm < 1 or wm > 1440:
                raise ValueError("attack_chain window_minutes 须为 1..1440 的整数")
    else:
        raise ValueError(f"未知 rule_type: {rule_type}")


# ── IOC 模型（T-P1-4）─────────────────────────────────────────────
class IocCreate(BaseModel):
    """创建 IOC 请求模型."""
    ioc_type: str
    ioc_value: str
    description: Optional[str] = None
    enabled: bool = True

    @root_validator(skip_on_failure=True)
    def _check_type(cls, values):
        ioc_type = values.get("ioc_type")
        if ioc_type not in IOC_TYPE_ENUM:
            raise ValueError(f"非法 ioc_type: '{ioc_type}'，应为 {IOC_TYPE_ENUM}")
        if not values.get("ioc_value"):
            raise ValueError("ioc_value 不能为空")
        return values


class IocImportItem(BaseModel):
    """批量导入的单条 IOC."""
    ioc_type: str
    ioc_value: str
    description: Optional[str] = None

    @root_validator(skip_on_failure=True)
    def _check_type(cls, values):
        ioc_type = values.get("ioc_type")
        if ioc_type not in IOC_TYPE_ENUM:
            raise ValueError(f"非法 ioc_type: '{ioc_type}'，应为 {IOC_TYPE_ENUM}")
        if not values.get("ioc_value"):
            raise ValueError("ioc_value 不能为空")
        return values


class IocImportRequest(BaseModel):
    """批量导入 IOC 请求."""
    items: List[IocImportItem]


class IocUpdate(BaseModel):
    """更新 IOC 请求模型（部分字段更新，启用开关小闭环核心）.

    全部字段可选；仅传入的字段会被更新。enabled 用于前端 el-switch 实时切换。
    """

    enabled: Optional[bool] = None
    description: Optional[str] = None
    source: Optional[str] = None


class IocResponse(BaseModel):
    """IOC 响应模型."""
    id: int
    ioc_type: str
    ioc_value: str
    source: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    created_at: str

    class Config:
        from_attributes = True


# ── IOC 外联威胁情报（Enrichment）模型 ──────────────────────────────
class ThreatIntelResponse(BaseModel):
    """威胁情报外联结果响应模型."""
    id: int
    ioc_id: Optional[int] = None
    ioc_type: str
    ioc_value: str
    provider: str
    risk_score: int = 0
    judgments: list = []
    tags: list = []
    confidence: int = 0
    attck: list = []
    company: list = []
    threat_level: Optional[str] = None
    queried_at: str
    raw_summary: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class EnrichRequest(BaseModel):
    """单条外联查询请求（可选指定 provider）."""
    provider: Optional[str] = None


class EnrichBatchRequest(BaseModel):
    """批量外联查询请求：ids 或 filter 二选一."""
    ids: Optional[list] = None
    filter: Optional[dict] = None

    @root_validator(skip_on_failure=True)
    def _check_target(cls, values):
        if not values.get("ids") and not values.get("filter"):
            raise ValueError("必须提供 ids 或 filter 之一")
        return values


class ProviderConfigInput(BaseModel):
    """Provider 配置写入模型（含 api_key_ref 占位，仅落 JSON 配置，不进 DB）."""
    name: str
    type: str = "threatbook"
    base_url: str
    api_key_ref: Optional[str] = ""
    enabled: bool = True
    rate_limit_qps: int = 2
    endpoints: Optional[dict] = None


class ProviderConfig(BaseModel):
    """Provider 配置响应模型（剔除 api_key_ref，不泄露密钥引用）."""
    name: str
    type: str = "threatbook"
    base_url: str
    enabled: bool = True
    rate_limit_qps: int = 2
    endpoints: Optional[dict] = None


class EnrichSettings(BaseModel):
    """运行策略响应模型."""
    enable_enrichment_feedback: bool = True
    auto_enrichment: bool = False
    daily_quota: int = 1000
    recheck_days: int = 30
    scheduler_interval: int = 3600
    rate_limit_qps: int = 2


class EnrichResult(BaseModel):
    """批量外联查询结果模型."""
    total: int = 0
    enriched: int = 0
    skipped: int = 0
    failed: int = 0
    details: list = []
