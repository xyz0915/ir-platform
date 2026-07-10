"""验证后端启动时通过 python-dotenv 从 backend/.env 加载环境变量（修复 THREATBOOK_KEY 缺失 Bug）.

背景:
  - 平台后端由 backend/run.py 起 uvicorn，或由 `uvicorn app.main:app` 直接启动；
    这两个入口原先都不加载 .env，导致进程内 os.environ["THREATBOOK_KEY"] 为空，
    ThreatBookProvider.query() 抛 “api_key 未配置或环境变量未设置”。
  - 修复 = 在 run.py / app/main.py / 独立脚本顶部 load_dotenv(backend/.env, override=False)，
    使无论终端 / IDE / 计划任务启动都能可靠读到 .env 兜底的 key；终端已设的变量优先不被覆盖。

本测试不写入真实微步 key，仅用本地测试假值，并会备份/还原被测目录可能存在的真实 backend/.env。
"""

import os
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent

from app.services.enrichment_service import (  # noqa: E402
    create_provider,
    expand_env,
    ThreatIntelQueryError,
)


def _backup_env_file() -> str:
    """若存在 backend/.env 则读取其内容为备份字符串（不存在返回 None）。"""
    env_path = BACKEND_ROOT / ".env"
    return env_path.read_text(encoding="utf-8") if env_path.exists() else None


def _restore_env_file(backup: str | None, previous_term_value: str | None) -> None:
    """还原 backend/.env 与终端环境变量，避免污染仓库与后续测试。"""
    env_path = BACKEND_ROOT / ".env"
    if backup is None:
        if env_path.exists():
            env_path.unlink()
    else:
        env_path.write_text(backup, encoding="utf-8")
    if previous_term_value is not None:
        os.environ["THREATBOOK_KEY"] = previous_term_value
    else:
        os.environ.pop("THREATBOOK_KEY", None)


def test_load_dotenv_populates_environ_and_expand_env() -> None:
    """load_dotenv(override=False) 后，.env 中的 THREATBOOK_KEY 应进入 os.environ 且 expand_env 可展开。"""
    backup = _backup_env_file()
    previous_term_value = os.environ.get("THREATBOOK_KEY")
    os.environ.pop("THREATBOOK_KEY", None)  # 模拟“终端未设该变量”的场景
    try:
        env_path = BACKEND_ROOT / ".env"
        env_path.write_text("THREATBOOK_KEY=dotenv_loaded_key\n", encoding="utf-8")
        load_dotenv(env_path, override=False)
        assert os.environ.get("THREATBOOK_KEY") == "dotenv_loaded_key"
        assert expand_env("$THREATBOOK_KEY") == "dotenv_loaded_key"
    finally:
        _restore_env_file(backup, previous_term_value)


def test_load_dotenv_does_not_override_existing_environ() -> None:
    """override=False 时，已存在的终端环境变量不被 .env 覆盖。"""
    backup = _backup_env_file()
    previous_term_value = os.environ.get("THREATBOOK_KEY")
    os.environ["THREATBOOK_KEY"] = "term_var"  # 模拟终端已设置的变量
    try:
        env_path = BACKEND_ROOT / ".env"
        env_path.write_text("THREATBOOK_KEY=dotenv_other_value\n", encoding="utf-8")
        load_dotenv(env_path, override=False)
        assert os.environ.get("THREATBOOK_KEY") == "term_var"
    finally:
        _restore_env_file(backup, previous_term_value)


def test_threatbook_provider_no_api_key_error_when_dotenv_provides_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当 .env 提供了 key 时，ThreatBookProvider.query() 不再因“api_key 未配置”抛错（httpx 被桩）。"""
    backup = _backup_env_file()
    previous_term_value = os.environ.get("THREATBOOK_KEY")
    os.environ.pop("THREATBOOK_KEY", None)
    try:
        env_path = BACKEND_ROOT / ".env"
        env_path.write_text(
            "THREATBOOK_KEY=dotenv_fake_key_for_test\n", encoding="utf-8"
        )
        # 确保本测试场景下从 .env 取到 key（无终端变量，故 override 与否都生效）
        load_dotenv(env_path, override=True)

        class _FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                # 最小合法业务响应：response_code=0，data 留空由归一化兜底
                return {"response_code": 0, "data": {}}

        def _fake_get(self: httpx.Client, url: str, params=None, **kwargs):
            return _FakeResponse()

        monkeypatch.setattr(httpx.Client, "get", _fake_get)

        provider = create_provider(
            {
                "name": "threatbook",
                "type": "threatbook",
                "base_url": "https://api.threatbook.cn/v3",
                "api_key_ref": "$THREATBOOK_KEY",
                "endpoints": {"ip": "/v3/scene/ip_reputation"},
            }
        )

        # 仅验证“越过 api_key 校验”这一环；归一化是否完整不在本测试范围
        try:
            provider.query("ip", "8.8.8.8")
        except ThreatIntelQueryError as exc:
            assert "api_key 未配置" not in str(
                exc
            ), f"不应再报 api_key 未配置: {exc}"
    finally:
        _restore_env_file(backup, previous_term_value)
