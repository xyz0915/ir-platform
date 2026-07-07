"""配置管理模块.

管理数据库路径、密钥、上传目录等全局配置.
"""

import os
from pathlib import Path


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
    ]
    # AI分析模块加密密钥（Fernet格式，用于加密存储API Key）
    # 生产环境应从环境变量读取，默认使用固定密钥（开发用）
    AI_ENCRYPTION_KEY: str = os.environ.get(
        "IR_AI_ENCRYPTION_KEY",
        "QSLeoOZ1ZXDfBM0SrbJq1cBcRznji1L62SMCJae7nEo=",
    )


settings = Settings()
