"""AI配置模型 — ai_config 表 CRUD 操作."""

import json
import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiConfig:
    """AI大模型配置模型."""

    @staticmethod
    def get() -> Optional[dict]:
        """获取AI配置（仅一条记录）."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM ai_config ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    @staticmethod
    def save(api_base_url: str, api_key_encrypted: str, model_name: str,
             enabled: int = 0, max_tokens: int = 4096,
             temperature: float = 0.3, system_prompt: str = "") -> dict:
        """保存AI配置（覆盖旧配置，未传新Key时保留旧Key）."""
        with get_connection() as conn:
            existing = conn.execute("SELECT * FROM ai_config ORDER BY id DESC LIMIT 1").fetchone()
            final_api_key = api_key_encrypted or (existing["api_key"] if existing else "")
            conn.execute("DELETE FROM ai_config")
            conn.execute(
                """
                INSERT INTO ai_config
                (api_base_url, api_key, model_name, enabled, max_tokens, temperature, system_prompt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (api_base_url, final_api_key, model_name, enabled,
                 max_tokens, temperature, system_prompt),
            )
        return AiConfig.get()

    @staticmethod
    def update_enabled(enabled: int) -> Optional[dict]:
        """更新AI功能开启/关闭状态."""
        with get_connection() as conn:
            conn.execute("UPDATE ai_config SET enabled = ?, updated_at = datetime('now')", (enabled,))
        return AiConfig.get()

    @staticmethod
    def get_decrypted_api_key() -> Optional[str]:
        """获取解密后的API Key."""
        config = AiConfig.get()
        if not config or not config.get("api_key"):
            return None
        from app.services.ai_service import AiService
        return AiService.decrypt_api_key(config["api_key"])
