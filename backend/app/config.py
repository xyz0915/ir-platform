"""配置管理模块.

管理数据库路径、密钥、上传目录等全局配置.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


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
