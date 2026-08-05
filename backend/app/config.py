"""配置管理模块.

管理数据库路径、密钥、上传目录等全局配置.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    """安全解析布尔环境变量（非法值回退默认，不崩溃）.

    接受 1/true/yes/on（大小写不敏感）视为 True；其余视为 False。

    Args:
        name: 环境变量名。
        default: 默认值。

    Returns:
        解析后的布尔值。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    """安全解析整数环境变量（非法值回退默认，不崩溃）.

    Args:
        name: 环境变量名。
        default: 默认值。

    Returns:
        解析后的整数值。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (ValueError, TypeError):
        logger.warning("Invalid int env %s=%r, using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """安全解析浮点环境变量（非法值回退默认，不崩溃）.

    Args:
        name: 环境变量名。
        default: 默认值。

    Returns:
        解析后的浮点值。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (ValueError, TypeError):
        logger.warning("Invalid float env %s=%r, using default %s", name, raw, default)
        return default


class Settings:
    """全局配置类.

    Attributes:
        BASE_DIR: 项目根目录.
        DB_PATH: SQLite 数据库文件路径.
        SECRET_KEY: JWT 密钥.
        ALGORITHM: JWT 签名算法.
        TOKEN_EXPIRE_HOURS: Token 有效期（小时）.
        UPLOAD_DIR: Agent JSON 原始文件存储目录.
        AGENT_DIR: Agent 二进制文件目录.
        MAX_FILE_SIZE_MB: 上传文件大小限制（MB）.
        DEFAULT_ADMIN_USER: 默认管理员用户名.
        DEFAULT_ADMIN_PASSWORD: 默认管理员密码.
        AI_ENCRYPTION_KEY: AI API Key 加密密钥.
        AI_CIRCUIT_BREAKER_TIMEOUT: 断路器熔断超时（秒）.
        AI_MASKING_DEFAULT: 默认启用脱敏.
        AI_MAX_RETRIES: AI 调用最大重试次数.
        AI_RETRY_BASE_DELAY: 重试基础延迟（秒）.
        AI_CONTEXT_WINDOW: 模型上下文窗口大小.
        AI_INPUT_BUDGET: 输入预算 tokens.
    """

    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    BACKEND_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BACKEND_DIR / "data"
    DB_PATH: str = str(DATA_DIR / "ir_platform.db")
    # SQLite journal mode（A6+A11 环境加固）：生产默认 WAL；测试库置 DELETE 规避
    # Windows 上 -wal/-shm 附属文件锁导致的临时库清理失败与 WAL 争用挂起。
    # 参考操作文档：docs/agent-orchestration-enhance-switches.md
    DB_JOURNAL_MODE: str = os.environ.get("IR_DB_JOURNAL_MODE", "WAL")
    SECRET_KEY: str = os.environ.get(
        "IR_SECRET_KEY",
        "ir-platform-secret-key-2025-please-change-in-production",
    )
    ALGORITHM: str = "HS256"
    TOKEN_EXPIRE_HOURS: int = 24
    UPLOAD_DIR: str = str(DATA_DIR / "imports")
    AGENT_DIR: str = str(BASE_DIR / "agent" / "dist")
    TEMPLATES_DIR: str = str(Path(__file__).resolve().parent / "templates")
    MAX_FILE_SIZE_MB: int = 100
    DEFAULT_ADMIN_USER: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    CORS_ORIGINS: list = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        # 允许外部终端访问（SSE 需要浏览器 CORS 放行）
        "*",
    ]
    # AI分析模块加密密钥（Fernet格式，用于加密存储API Key）
    # 生产环境应从环境变量读取，默认使用固定密钥（开发用）
    AI_ENCRYPTION_KEY: str = os.environ.get(
        "IR_AI_ENCRYPTION_KEY",
        "QSLeoOZ1ZXDfBM0SrbJq1cBcRznji1L62SMCJae7nEo=",
    )
    # AI 断路器熔断超时（秒）
    AI_CIRCUIT_BREAKER_TIMEOUT: int = 300
    # AI 默认启用脱敏
    AI_MASKING_DEFAULT: bool = True
    # AI 调用最大重试次数
    AI_MAX_RETRIES: int = 3
    # 重试基础延迟（秒），指数退避：delay * (2 ** attempt)
    AI_RETRY_BASE_DELAY: float = 1.0
    # 模型上下文窗口大小
    AI_CONTEXT_WINDOW: int = 128000
    # 输入预算 tokens
    AI_INPUT_BUDGET: int = 80000

    # ── 部署形态（F14 / M9 DeploymentConfig）──────────────
    # 无状态模式开关：True 表示后端无本地会话态（如 Serverless / 容器化水平扩展）。
    STATELESS_MODE: bool = False
    # Redis 连接串（可选；未配置时 DeploymentConfig.redis_connected=false）。
    REDIS_URL: str = ""

    # ── IOC 外联威胁情报（Enrichment / Outbound）──────────────
    # 总开关：是否启用"威胁情报平台回灌到规则引擎"功能（默认开）。
    ENABLE_THREAT_INTEL_ENRICHMENT: bool = True
    # 自动外联总开关：调度器是否自动扫描并外联查询（默认关，推荐用 --once + cron）。
    AUTO_ENRICHMENT: bool = False
    # 兜底默认值常量（与 backend/config/threat_intel_settings.json 保持一致）
    DEFAULT_DAILY_QUOTA: int = 1000
    DEFAULT_RECHECK_DAYS: int = 30
    DEFAULT_SCHEDULER_INTERVAL: int = 3600
    DEFAULT_RATE_LIMIT_QPS: int = 2
    DEFAULT_ENABLE_ENRICHMENT_FEEDBACK: bool = True
    # 配置文件路径
    THREAT_INTEL_PROVIDERS_PATH: Path = BACKEND_DIR / "scripts" / "threat_intel_providers.json"
    THREAT_INTEL_SETTINGS_PATH: Path = BACKEND_DIR / "config" / "threat_intel_settings.json"
    # 报告模板配置路径（任务⑤ 分级报告）
    REPORT_TEMPLATE_PATH: Path = BACKEND_DIR / "config" / "report_template.json"
    # 内存去重 TTL（秒），防止运行时短时间重复打 API
    THREAT_INTEL_DEDUP_TTL: int = 600
    # 支持外联查询的 IOC 类型
    ENRICH_SUPPORTED_TYPES: list = ["ip", "domain"]
    # 分级缓存 TTL（任务④ 决策⑦）：按判定分级决定外联情报缓存有效期，优先于 recheck_days
    # 恶意情报缓存 24 小时、干净情报缓存 7 天、未知/可疑情报缓存 3 天（recheck_days 兜底）
    DEFAULT_CACHE_TTL_MALICIOUS_HOURS: int = 24
    DEFAULT_CACHE_TTL_CLEAN_DAYS: int = 7
    DEFAULT_CACHE_TTL_UNKNOWN_DAYS: int = 3


    # ── 手工日志导入（Manual Log Import）────────────────────
    LOG_FILE_RETENTION_DAYS: int = 7       # 上传日志文件保留天数
    MAX_LOG_FILE_SIZE_MB: int = 500        # 单文件大小上限（MB）
    ASYNC_THRESHOLD_MB: int = 100          # 异步处理阈值（MB）

    # ── 规则引擎（Rule Engine）────────────────────────────────
    USE_BEHAVIOR_DB_RULES: bool = False    # 灰度开关：行为分析引擎从 DB 读取规则

    # ── 自动 RAG 注入（P1）────────────────────────────────────
    # 总开关：LLM 类节点执行前自动检索知识库 Top-K 并注入 Prompt。默认关，
    # 保证存量流水线零行为变化；节点级 input_params.rag_enhance 可覆盖。
    IR_RAG_AUTO_ENHANCE: bool = _env_flag("IR_RAG_AUTO_ENHANCE", False)
    # Top-K：每次注入的检索命中条数（节点级 input_params.rag_top_k 可覆盖，夹取 [1,10]）。
    IR_RAG_AUTO_ENHANCE_K: int = _env_int("IR_RAG_AUTO_ENHANCE_K", 3)
    # 检索超时（秒）：KnowledgeRetriever.retrieve 为同步阻塞，经 to_thread 包裹后
    # 用 wait_for 限时，超时按未命中处理，不阻断节点。
    IR_RAG_RETRIEVE_TIMEOUT: float = _env_float("IR_RAG_RETRIEVE_TIMEOUT", 5.0)
    # 注入块头（可自定义；默认与页面 RAG 示意语义一致）。
    IR_RAG_INJECT_HEADER: str = os.environ.get(
        "IR_RAG_INJECT_HEADER",
        "[知识增强] 以下为知识库检索到的历史处置经验（Top-K），供分析/处置参考；如与当前事件无关请忽略：",
    )

    # ── 长期记忆（P2：agent_memories）──────────────────────────
    # 自动沉淀总开关：关键节点执行成功后自动写长期记忆（纯追加，不读记忆、不改 prompt，
    # 对存量流水线零影响）。默认 True；节点级 input_params.remember 可 opt-out/opt-in。
    IR_MEMORY_AUTO_WRITE: bool = _env_flag("IR_MEMORY_AUTO_WRITE", True)
    # 记忆增强总开关：LLM 类节点执行前自动检索历史记忆 Top-K 并注入 Prompt。默认关，
    # 保证存量流水线 prompt 零变化；节点级 input_params.memory_enhance 可覆盖。
    IR_MEMORY_AUTO_ENHANCE: bool = _env_flag("IR_MEMORY_AUTO_ENHANCE", False)
    # 记忆增强 Top-K：每次注入的检索命中条数（节点级 input_params.memory_top_k 可覆盖，夹取 [1,10]）。
    IR_MEMORY_ENHANCE_K: int = _env_int("IR_MEMORY_ENHANCE_K", 3)
    # 记忆检索超时（秒）：AgentMemory.search 为同步阻塞，经 to_thread 包裹后
    # 用 wait_for 限时，超时按未命中处理，不阻断节点。
    IR_MEMORY_RETRIEVE_TIMEOUT: float = _env_float("IR_MEMORY_RETRIEVE_TIMEOUT", 3.0)
    # 记忆正文最大长度（字符）：自动沉淀 / 手动写入统一截断，防单条记忆撑爆上下文。
    IR_MEMORY_MAX_CONTENT: int = _env_int("IR_MEMORY_MAX_CONTENT", 4000)
    # 记忆注入块头（可自定义；默认与页面「长期记忆」语义一致）。
    IR_MEMORY_INJECT_HEADER: str = os.environ.get(
        "IR_MEMORY_INJECT_HEADER",
        "[记忆增强] 以下为历史事件记忆（结论/摘要/处置记录，Top-K），供本次分析参考；如与当前事件无关请忽略：",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._warn_default_encryption_key()

    def _warn_default_encryption_key(self) -> None:
        """生产环境若未设置 IR_AI_ENCRYPTION_KEY，发出告警。"""
        default_key = "QSLeoOZ1ZXDfBM0SrbJq1cBcRznji1L62SMCJae7nEo="
        if self.AI_ENCRYPTION_KEY == default_key:
            logger.warning(
                "⚠️ AI_ENCRYPTION_KEY 使用默认开发密钥！"
                "生产环境请设置环境变量 IR_AI_ENCRYPTION_KEY"
            )


settings = Settings()
