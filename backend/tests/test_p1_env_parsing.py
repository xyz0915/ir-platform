"""P1 测试：env 安全解析（_env_flag/_env_int/_env_float + Settings 启动不崩）。

依据：
- ``p1-design.md`` §2.5（开关机制，env 解析用模块级安全助手，非法值回退默认不崩启动）
- ``p1-dev.md`` §2.1（``config.py`` L13-68 安全助手 + L127-145 四个常量）

覆盖（按任务 T4）：
- ``_env_flag``：1/true/yes/on（大小写不敏感）→ True；其余/未设置 → 默认；
- ``_env_int``：合法 → 值；非法 → 默认 + logger.warning；
- ``_env_float``：合法 → 值；非法 → 默认；
- Settings 启动：IR_RAG_AUTO_ENHANCE=abc / IR_RAG_AUTO_ENHANCE_K=999 /
  IR_RAG_RETRIEVE_TIMEOUT=xyz 时 import 不崩（子进程验证，避免污染本进程 settings 单例）；
  合法值（true/7/2.5）正确解析。
"""

import os
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from app.config import _env_flag, _env_int, _env_float


class TestEnvFlag:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True", "yes", "on", " 1 ", " ON "])
    def test_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv("IR_TEST_FLAG", raw)
        assert _env_flag("IR_TEST_FLAG", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "abc", "", "2"])
    def test_falsy_values(self, monkeypatch, raw):
        monkeypatch.setenv("IR_TEST_FLAG", raw)
        assert _env_flag("IR_TEST_FLAG", False) is False

    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("IR_TEST_FLAG", raising=False)
        assert _env_flag("IR_TEST_FLAG", False) is False
        assert _env_flag("IR_TEST_FLAG", True) is True


class TestEnvInt:
    def test_valid(self, monkeypatch):
        monkeypatch.setenv("IR_TEST_INT", "7")
        assert _env_int("IR_TEST_INT", 3) == 7

    def test_invalid_falls_back_default(self, monkeypatch, caplog):
        monkeypatch.setenv("IR_TEST_INT", "notanint")
        assert _env_int("IR_TEST_INT", 3) == 3
        assert "Invalid int env" in caplog.text

    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("IR_TEST_INT", raising=False)
        assert _env_int("IR_TEST_INT", 3) == 3


class TestEnvFloat:
    def test_valid(self, monkeypatch):
        monkeypatch.setenv("IR_TEST_FLOAT", "2.5")
        assert _env_float("IR_TEST_FLOAT", 5.0) == 2.5

    def test_invalid_falls_back_default(self, monkeypatch, caplog):
        monkeypatch.setenv("IR_TEST_FLOAT", "abc")
        assert _env_float("IR_TEST_FLOAT", 5.0) == 5.0
        assert "Invalid float env" in caplog.text

    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("IR_TEST_FLOAT", raising=False)
        assert _env_float("IR_TEST_FLOAT", 5.0) == 5.0


class TestSettingsStartup:
    _PROBE = (
        "from app.config import settings; "
        "print(settings.IR_RAG_AUTO_ENHANCE, settings.IR_RAG_AUTO_ENHANCE_K, "
        "settings.IR_RAG_RETRIEVE_TIMEOUT)"
    )

    def _run_probe(self, env_updates):
        env = dict(os.environ)
        env.update(env_updates)
        proc = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_BACKEND),
            timeout=60,
        )
        return proc

    def test_invalid_env_falls_back_no_crash(self):
        """非法 env：IR_RAG_AUTO_ENHANCE=abc → False；K=999 → 解析合法为 999（夹取在 _rag_top_k）；
        RETRIEVE_TIMEOUT=xyz → 回退 5.0；import 不崩。"""
        proc = self._run_probe({
            "IR_RAG_AUTO_ENHANCE": "abc",
            "IR_RAG_AUTO_ENHANCE_K": "999",
            "IR_RAG_RETRIEVE_TIMEOUT": "xyz",
        })
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout.strip().splitlines()[-1]
        assert out == "False 999 5.0"

    def test_valid_env_parsed(self):
        """合法 env：true / 7 / 2.5 → True / 7 / 2.5。"""
        proc = self._run_probe({
            "IR_RAG_AUTO_ENHANCE": "true",
            "IR_RAG_AUTO_ENHANCE_K": "7",
            "IR_RAG_RETRIEVE_TIMEOUT": "2.5",
        })
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout.strip().splitlines()[-1]
        assert out == "True 7 2.5"

    def test_unset_env_defaults(self):
        """未设 env：False / 3 / 5.0（默认）。"""
        env = dict(os.environ)
        for key in ("IR_RAG_AUTO_ENHANCE", "IR_RAG_AUTO_ENHANCE_K", "IR_RAG_RETRIEVE_TIMEOUT"):
            env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_BACKEND),
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout.strip().splitlines()[-1]
        assert out == "False 3 5.0"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
