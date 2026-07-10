"""AI配置模型 — ai_config_profiles 表 CRUD 操作（多 Profile 支持）."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiConfigProfile:
    """AI大模型配置多Profile模型.

    支持同时管理多个AI服务配置（如不同供应商、不同模型），
    通过 is_active 标识当前使用的配置.
    """

    @staticmethod
    def list_all(user_id: Optional[int] = None, role: str = "admin") -> list[dict]:
        """列出所有AI配置Profile.

        Args:
            user_id: 当前用户ID，用于权限过滤（管理员看全部，普通用户看自己的+公开的）.
            role: 用户角色（admin / user）.

        Returns:
            Profile 列表.
        """
        with get_connection() as conn:
            if role == "admin":
                rows = conn.execute(
                    "SELECT * FROM ai_config_profiles ORDER BY is_active DESC, id ASC"
                ).fetchall()
            elif user_id is not None:
                rows = conn.execute(
                    """SELECT * FROM ai_config_profiles
                       WHERE owner_user_id = ? OR is_public = 1
                       ORDER BY is_active DESC, id ASC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ai_config_profiles WHERE is_public = 1 ORDER BY is_active DESC, id ASC"
                ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_active() -> Optional[dict]:
        """获取当前激活的AI配置Profile."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_config_profiles WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_id(profile_id: int) -> Optional[dict]:
        """根据ID获取AI配置Profile."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_config_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(
        profile_name: str = "默认配置",
        provider: str = "openai",
        api_base_url: str = "",
        api_key: str = "",
        model_name: str = "gpt-4o",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system_prompt: str = "",
    ) -> dict:
        """创建新的AI配置Profile.

        如果这是第一个Profile，自动设为激活状态.
        """
        with get_connection() as conn:
            # 检查是否已有Profile
            existing = conn.execute("SELECT COUNT(*) as cnt FROM ai_config_profiles").fetchone()
            is_active = 1 if existing["cnt"] == 0 else 0

            cursor = conn.execute(
                """
                INSERT INTO ai_config_profiles
                (profile_name, provider, api_base_url, api_key, model_name,
                 max_tokens, temperature, system_prompt, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_name, provider, api_base_url, api_key, model_name,
                    max_tokens, temperature, system_prompt, is_active,
                ),
            )
            profile_id = cursor.lastrowid
        return AiConfigProfile.get_by_id(profile_id)

    @staticmethod
    def update(profile_id: int, **kwargs: Any) -> Optional[dict]:
        """更新指定的AI配置Profile.

        Args:
            profile_id: Profile ID.
            **kwargs: 需要更新的字段（支持 profile_name, provider, api_base_url,
                      api_key, model_name, max_tokens, temperature, system_prompt）.

        Returns:
            更新后的Profile字典，不存在返回None.
        """
        allowed_fields = {
            "profile_name", "provider", "api_base_url", "api_key",
            "model_name", "max_tokens", "temperature", "system_prompt",
        }
        update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not update_data:
            return AiConfigProfile.get_by_id(profile_id)

        set_clauses = [f"{field} = ?" for field in update_data]
        values = list(update_data.values())
        # 添加 updated_at
        set_clauses.append("updated_at = datetime('now')")
        values.append(profile_id)

        with get_connection() as conn:
            conn.execute(
                f"UPDATE ai_config_profiles SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
        return AiConfigProfile.get_by_id(profile_id)

    @staticmethod
    def delete(profile_id: int) -> bool:
        """删除指定的AI配置Profile.

        不允许删除当前激活的Profile，除非是唯一的一个.

        Args:
            profile_id: Profile ID.

        Returns:
            是否删除成功.

        Raises:
            ValueError: 尝试删除唯一的激活Profile时抛出.
        """
        with get_connection() as conn:
            profile = conn.execute(
                "SELECT * FROM ai_config_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if profile is None:
                return False

            if profile["is_active"] == 1:
                # 检查是否还有其他Profile
                count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM ai_config_profiles WHERE id != ?",
                    (profile_id,),
                ).fetchone()
                if count["cnt"] == 0:
                    # 这是唯一的一个Profile，允许删除
                    pass
                else:
                    raise ValueError("不能删除当前激活的配置，请先激活另一个配置")

            conn.execute("DELETE FROM ai_config_profiles WHERE id = ?", (profile_id,))
        return True

    @staticmethod
    def set_active(profile_id: int) -> Optional[dict]:
        """设置指定的Profile为激活状态.

        自动将其他Profile的 is_active 设为 0.
        """
        with get_connection() as conn:
            profile = conn.execute(
                "SELECT id FROM ai_config_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if profile is None:
                return None

            # 先将所有Profile设为非激活
            conn.execute(
                "UPDATE ai_config_profiles SET is_active = 0, updated_at = datetime('now')"
            )
            # 激活目标Profile
            conn.execute(
                "UPDATE ai_config_profiles SET is_active = 1, updated_at = datetime('now') WHERE id = ?",
                (profile_id,),
            )
        return AiConfigProfile.get_by_id(profile_id)

    @staticmethod
    def test_connection(profile_id: int) -> dict:
        """测试AI服务的连接.

        通过调用 /models 端点验证API连接是否正常.

        Args:
            profile_id: Profile ID.

        Returns:
            {"success": bool, "message": str, "models": list | None}
        """
        import httpx

        profile = AiConfigProfile.get_by_id(profile_id)
        if not profile:
            return {"success": False, "message": "配置不存在", "models": None}

        api_base_url = profile.get("api_base_url", "").rstrip("/")
        api_key_encrypted = profile.get("api_key", "")

        if not api_base_url:
            return {"success": False, "message": "API地址未配置", "models": None}
        if not api_key_encrypted:
            return {"success": False, "message": "API Key未配置", "models": None}

        # 解密API Key
        try:
            from app.services.ai_service import AiService
            api_key = AiService.decrypt_api_key(api_key_encrypted)
        except Exception as e:
            return {"success": False, "message": f"API Key解密失败: {str(e)}", "models": None}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        models_url = api_base_url + "/models"

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(models_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    model_list = [m.get("id", "") for m in data.get("data", [])]
                    return {
                        "success": True,
                        "message": f"连接成功，共 {len(model_list)} 个可用模型",
                        "models": model_list[:20],
                    }
                elif resp.status_code == 401:
                    return {"success": False, "message": "认证失败（API Key无效）", "models": None}
                elif resp.status_code == 404:
                    # 有的代理网关不支持 /models，尝试 /chat/completions 探测
                    resp2 = client.post(
                        api_base_url + "/chat/completions",
                        headers=headers,
                        json={
                            "model": profile.get("model_name", "gpt-4o"),
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 1,
                        },
                    )
                    if resp2.status_code in (200, 400):
                        return {
                            "success": True,
                            "message": "连接成功（/models端点不可用，但chat端点可达）",
                            "models": None,
                        }
                    return {
                        "success": False,
                        "message": f"连接失败 (HTTP {resp2.status_code})",
                        "models": None,
                    }
                else:
                    return {
                        "success": False,
                        "message": f"连接失败 (HTTP {resp.status_code})",
                        "models": None,
                    }
        except httpx.ConnectError:
            return {"success": False, "message": "无法连接API服务器，请检查地址", "models": None}
        except httpx.TimeoutException:
            return {"success": False, "message": "连接超时（15秒）", "models": None}
        except Exception as e:
            logger.exception("test_connection error for profile_id=%d", profile_id)
            return {"success": False, "message": f"连接测试失败: {str(e)}", "models": None}


# ================================================================
# 向后兼容层：旧 AiConfig 类映射到新的 AiConfigProfile
# ================================================================


class AiConfig:
    """AI配置模型（向后兼容适配器）.

    将旧的单记录 ai_config 操作映射到新的多 Profile ai_config_profiles 表。
    所有操作默认针对当前激活的 Profile（is_active=1）.
    """

    @staticmethod
    def get() -> Optional[dict]:
        """获取当前激活的AI配置（兼容旧接口，返回 aktiv Profile 的扁平字典）."""
        profile = AiConfigProfile.get_active()
        if not profile:
            # 回退：检查旧的 ai_config 表
            with get_connection() as conn:
                old_row = conn.execute(
                    "SELECT * FROM ai_config ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if old_row:
                    return dict(old_row)
            return None
        # 将 Profile 字段映射为旧 ai_config 字段名（带 enabled 兼容）
        result = dict(profile)
        result["enabled"] = profile.get("is_active", 0)
        return result

    @staticmethod
    def save(api_base_url: str, api_key_encrypted: str, model_name: str,
             enabled: int = 0, max_tokens: int = 4096,
             temperature: float = 0.3, system_prompt: str = "") -> dict:
        """保存AI配置（兼容旧接口，操作激活Profile）."""
        active = AiConfigProfile.get_active()
        if active:
            # 更新激活的Profile
            AiConfigProfile.update(
                active["id"],
                api_base_url=api_base_url,
                api_key=api_key_encrypted or active.get("api_key", ""),
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            if enabled == 1:
                AiConfigProfile.set_active(active["id"])
        else:
            # 创建新Profile
            AiConfigProfile.create(
                profile_name="默认配置",
                provider="openai",
                api_base_url=api_base_url,
                api_key=api_key_encrypted,
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            # 如果要求启用，激活它
            if enabled == 1:
                profile = AiConfigProfile.get_active()
                if profile:
                    AiConfigProfile.set_active(profile["id"])

        return AiConfig.get()

    @staticmethod
    def update_enabled(enabled: int) -> Optional[dict]:
        """更新AI功能开启/关闭状态（兼容旧接口）."""
        active = AiConfigProfile.get_active()
        if active and enabled == 0:
            # 将 is_active 置0但保留Profile数据
            with get_connection() as conn:
                conn.execute(
                    "UPDATE ai_config_profiles SET is_active = 0, updated_at = datetime('now') WHERE id = ?",
                    (active["id"],),
                )
            # 返回被禁用前的 Profile 数据（enabled=0）
            result = dict(active)
            result["enabled"] = 0
            result["is_active"] = 0
            return result
        elif not active and enabled == 1:
            # 尝试激活第一个可用Profile
            profiles = AiConfigProfile.list_all()
            if profiles:
                AiConfigProfile.set_active(profiles[0]["id"])
        elif active and enabled == 1:
            # 已经激活，无需操作
            AiConfigProfile.set_active(active["id"])

        return AiConfig.get()

    @staticmethod
    def get_decrypted_api_key() -> Optional[str]:
        """获取解密后的API Key（兼容旧接口）."""
        config = AiConfig.get()
        if not config or not config.get("api_key"):
            return None
        # 避免循环导入，延迟导入
        from app.services.ai_service import AiService
        return AiService.decrypt_api_key(config["api_key"])


class AiPromptVersion:
    """AI提示词历史版本模型 — ai_prompt_versions 表 CRUD 操作."""

    @staticmethod
    def create(profile_id: int, content: str, version: Optional[int] = None) -> dict:
        """创建新的提示词版本.

        Args:
            profile_id: 关联的 Profile ID.
            content: 提示词内容.
            version: 版本号（None 则自动递增）.

        Returns:
            创建的版本记录.
        """
        with get_connection() as conn:
            if version is None:
                max_ver_row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) as max_ver FROM ai_prompt_versions WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()
                version = max_ver_row["max_ver"] + 1

            cursor = conn.execute(
                """INSERT INTO ai_prompt_versions (profile_id, version, content)
                   VALUES (?, ?, ?)""",
                (profile_id, version, content),
            )
            vid = cursor.lastrowid
        return AiPromptVersion.get_by_id(vid)

    @staticmethod
    def get_by_id(version_id: int) -> Optional[dict]:
        """根据ID获取提示词版本."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_prompt_versions WHERE id = ?", (version_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_profile(profile_id: int, limit: int = 5) -> list[dict]:
        """列出指定 Profile 的提示词历史版本（最新优先）.

        Args:
            profile_id: Profile ID.
            limit: 返回数量上限.

        Returns:
            版本列表.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM ai_prompt_versions
                   WHERE profile_id = ?
                   ORDER BY version DESC LIMIT ?""",
                (profile_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_latest(profile_id: int) -> Optional[dict]:
        """获取指定 Profile 的最新提示词版本."""
        versions = AiPromptVersion.list_by_profile(profile_id, limit=1)
        return versions[0] if versions else None

    @staticmethod
    def clean_old_versions(profile_id: int, keep: int = 5) -> int:
        """清理旧版本，仅保留最新的 N 个.

        Args:
            profile_id: Profile ID.
            keep: 保留的版本数量.

        Returns:
            删除的记录数.
        """
        with get_connection() as conn:
            # 获取需要保留的最旧版本号
            rows = conn.execute(
                """SELECT version FROM ai_prompt_versions
                   WHERE profile_id = ?
                   ORDER BY version DESC LIMIT 1 OFFSET ?""",
                (profile_id, keep - 1),
            ).fetchall()
            if not rows:
                return 0
            min_version = rows[0]["version"]
            cursor = conn.execute(
                """DELETE FROM ai_prompt_versions
                   WHERE profile_id = ? AND version < ?""",
                (profile_id, min_version),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned %d old prompt versions for profile %d", deleted, profile_id)
            return deleted
