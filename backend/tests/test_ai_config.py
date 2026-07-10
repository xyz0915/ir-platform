"""AI配置 Profile 测试套件.

测试范围:
    - AiConfigProfile 创建/编辑/删除
    - 激活 Profile (is_active 互斥)
    - 向后兼容 (AiConfig 适配器)
    - API Key 加密/解密
"""

import os
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_config.db")


class TestAiConfigProfile(unittest.TestCase):
    """测试 AI 配置 Profile (多Profile支持)."""

    @classmethod
    def setUpClass(cls):
        """设置测试数据库."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

    def test_01_create_first_profile_auto_active(self):
        """创建第一个 Profile 应自动激活."""
        from app.models.ai_config import AiConfigProfile

        profile = AiConfigProfile.create(
            profile_name="OpenAI 主配置",
            provider="openai",
            api_base_url="https://api.openai.com/v1",
            api_key="sk-test-key-12345",
            model_name="gpt-4o",
            max_tokens=4096,
            temperature=0.3,
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile["profile_name"], "OpenAI 主配置")
        self.assertEqual(profile["provider"], "openai")
        self.assertEqual(profile["is_active"], 1)
        self.assertEqual(profile["model_name"], "gpt-4o")

    def test_02_create_second_profile_not_active(self):
        """创建第二个 Profile 不应自动激活."""
        from app.models.ai_config import AiConfigProfile

        profile = AiConfigProfile.create(
            profile_name="Azure 备用",
            provider="azure",
            api_base_url="https://my-resource.openai.azure.com",
            api_key="sk-azure-key-67890",
            model_name="gpt-4",
            max_tokens=8192,
            temperature=0.5,
        )
        self.assertEqual(profile["is_active"], 0)

    def test_03_list_all_profiles(self):
        """list_all 应返回所有 Profile，激活的排在前面."""
        from app.models.ai_config import AiConfigProfile

        profiles = AiConfigProfile.list_all()
        self.assertEqual(len(profiles), 2)
        # 激活的排在前面
        self.assertEqual(profiles[0]["is_active"], 1)

    def test_04_get_active(self):
        """get_active 应返回当前激活的 Profile."""
        from app.models.ai_config import AiConfigProfile

        active = AiConfigProfile.get_active()
        self.assertIsNotNone(active)
        self.assertEqual(active["is_active"], 1)
        self.assertEqual(active["profile_name"], "OpenAI 主配置")

    def test_05_get_by_id(self):
        """get_by_id 应返回正确的 Profile."""
        from app.models.ai_config import AiConfigProfile

        profile = AiConfigProfile.get_by_id(1)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["id"], 1)

        nonexistent = AiConfigProfile.get_by_id(999)
        self.assertIsNone(nonexistent)

    def test_06_update_profile(self):
        """更新 Profile 字段."""
        from app.models.ai_config import AiConfigProfile

        updated = AiConfigProfile.update(
            1,
            profile_name="OpenAI 主配置 (已更新)",
            model_name="gpt-4o-mini",
            max_tokens=2048,
        )
        self.assertEqual(updated["profile_name"], "OpenAI 主配置 (已更新)")
        self.assertEqual(updated["model_name"], "gpt-4o-mini")
        self.assertEqual(updated["max_tokens"], 2048)

    def test_07_update_nonexistent(self):
        """更新不存在的 Profile."""
        from app.models.ai_config import AiConfigProfile

        result = AiConfigProfile.update(999, profile_name="Ghost")
        self.assertIsNone(result)

    def test_08_set_active_mutual_exclusion(self):
        """激活一个 Profile 时，其他 Profile 的 is_active 应为 0."""
        from app.models.ai_config import AiConfigProfile

        # 激活第二个 Profile
        result = AiConfigProfile.set_active(2)
        self.assertIsNotNone(result)
        self.assertEqual(result["is_active"], 1)

        # 检查第一个 Profile 是否变为非激活
        profile1 = AiConfigProfile.get_by_id(1)
        self.assertEqual(profile1["is_active"], 0)

        # 第二个应为激活
        profile2 = AiConfigProfile.get_by_id(2)
        self.assertEqual(profile2["is_active"], 1)

    def test_09_set_active_nonexistent(self):
        """激活不存在的 Profile."""
        from app.models.ai_config import AiConfigProfile

        result = AiConfigProfile.set_active(999)
        self.assertIsNone(result)

    def test_10_delete_non_active(self):
        """删除非激活的 Profile（应成功）."""
        from app.models.ai_config import AiConfigProfile

        # 当前激活的是2，删除1
        result = AiConfigProfile.delete(1)
        self.assertTrue(result)
        self.assertIsNone(AiConfigProfile.get_by_id(1))

    def test_11_delete_active_raises_when_others_exist(self):
        """删除激活的 Profile 且还有其他 Profile 时应抛出 ValueError."""
        from app.models.ai_config import AiConfigProfile

        # 先创建第三个Profile（确保除了激活的2之外还有其他）
        AiConfigProfile.create(
            profile_name="额外配置",
            provider="anthropic",
            api_base_url="https://api.anthropic.com",
            api_key="sk-extra",
            model_name="claude-3",
        )
        # 现在有 profile 2 (激活) 和 profile 3 (非激活)
        # 删除激活的 profile 2 应该抛出 ValueError
        with self.assertRaises(ValueError) as ctx:
            AiConfigProfile.delete(2)
        self.assertIn("不能删除当前激活的配置", str(ctx.exception))

    def test_12_delete_last_profile_allowed(self):
        """删除唯一的（激活的）Profile 应被允许."""
        from app.models.ai_config import AiConfigProfile

        # 先激活 profile 3，然后删除 profile 2（非激活）
        AiConfigProfile.set_active(3)

        # 现在删除 profile 2 (非激活，可以删除)
        result = AiConfigProfile.delete(2)
        self.assertTrue(result)

        # 现在只有 profile 3，是唯一且激活的
        active = AiConfigProfile.get_active()
        self.assertEqual(active["id"], 3)

        # 删除最后一个
        result = AiConfigProfile.delete(3)
        self.assertTrue(result)

        # 确认现在没有 Profile
        self.assertIsNone(AiConfigProfile.get_active())
        self.assertEqual(len(AiConfigProfile.list_all()), 0)


class TestAiConfigBackwardCompatibility(unittest.TestCase):
    """测试旧 AiConfig API 的向后兼容性."""

    @classmethod
    def setUpClass(cls):
        """重新设置测试数据库."""
        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        # 确保数据库已初始化
        from app.database import init_db
        init_db()

        from app.models.ai_config import AiConfigProfile

        # 确保有一个可用的 Profile
        active = AiConfigProfile.get_active()
        if not active:
            profiles = AiConfigProfile.list_all()
            if profiles:
                AiConfigProfile.set_active(profiles[0]["id"])
            else:
                AiConfigProfile.create(
                    profile_name="兼容测试配置",
                    provider="openai",
                    api_base_url="https://api.openai.com/v1",
                    api_key="sk-compat-test",
                    model_name="gpt-4o",
                )

    def test_01_ai_config_get(self):
        """旧 AiConfig.get() 应返回当前激活 Profile 的数据."""
        from app.models.ai_config import AiConfig

        config = AiConfig.get()
        self.assertIsNotNone(config)
        self.assertIn("api_base_url", config)
        self.assertIn("model_name", config)
        # 应有 enabled 兼容字段
        self.assertIn("enabled", config)

    def test_02_ai_config_save_updates_active(self):
        """旧 AiConfig.save() 应更新当前激活 Profile."""
        from app.models.ai_config import AiConfig

        config = AiConfig.save(
            api_base_url="https://updated.example.com",
            api_key_encrypted="new-encrypted-key",
            model_name="gpt-4o-mini",
            enabled=1,
            max_tokens=4096,
            temperature=0.7,
            system_prompt="test prompt",
        )
        self.assertIsNotNone(config)
        # 验证数据已更新
        config2 = AiConfig.get()
        self.assertEqual(config2["api_base_url"], "https://updated.example.com")

    def test_03_ai_config_update_enabled(self):
        """旧 AiConfig.update_enabled()."""
        from app.models.ai_config import AiConfig

        # 禁用
        config = AiConfig.update_enabled(0)
        self.assertIsNotNone(config)

        # 重新启用
        config = AiConfig.update_enabled(1)
        self.assertIsNotNone(config)


class TestApiKeyEncryption(unittest.TestCase):
    """测试 API Key 加密/解密/脱敏."""

    def test_01_encrypt_decrypt_roundtrip(self):
        """加密后解密应还原原始值."""
        from app.services.ai_service import AiService

        original = "sk-proj-1234567890abcdefghij"
        encrypted = AiService.encrypt_api_key(original)
        self.assertNotEqual(encrypted, original)

        decrypted = AiService.decrypt_api_key(encrypted)
        self.assertEqual(decrypted, original)

    def test_02_mask_api_key(self):
        """脱敏 API Key: 仅显示最后4位."""
        from app.services.ai_service import AiService

        key = "sk-proj-1234567890abcdefghij"
        masked = AiService.mask_api_key(key)
        self.assertTrue(masked.startswith("****"))
        self.assertTrue(masked.endswith("hij"))
        self.assertEqual(len(masked), 8)  # **** + last 4 chars

    def test_03_mask_short_key(self):
        """短 Key 脱敏."""
        from app.services.ai_service import AiService

        self.assertEqual(AiService.mask_api_key("ab"), "****")
        self.assertEqual(AiService.mask_api_key(""), "****")

    def test_04_encrypt_different_keys(self):
        """不同 Key 加密结果不同."""
        from app.services.ai_service import AiService

        enc1 = AiService.encrypt_api_key("key-a")
        enc2 = AiService.encrypt_api_key("key-b")
        self.assertNotEqual(enc1, enc2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
