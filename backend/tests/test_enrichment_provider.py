#!/usr/bin/env python3
"""ThreatBookProvider 单元测试（T2 验收点）.

使用 unittest.mock 替换 httpx.Client，不发起真实网络请求，验证:
  - NormalizedIntel 归一化与 verdict 映射（judgments 优先 / risk_score 兜底）
  - api_key_ref 经 expand_env 展开后作为查询参数 apikey 传递
  - response_code != 0 上抛 ThreatIntelQueryError（不落库）
  - 不支持的 ioc_type 上抛 UnsupportedIocTypeError
"""

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.enrichment_service import (  # noqa: E402
    ThreatBookProvider,
    UnsupportedIocTypeError,
    ThreatIntelQueryError,
    expand_env,
)


def _make_provider(api_key_ref="$THREATBOOK_KEY"):
    cfg = {
        "name": "threatbook",
        "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": api_key_ref,
        "endpoints": {"ip": "/v3/scene/ip", "domain": "/v3/domain/adv"},
        "rate_limit_qps": 2,
    }
    return ThreatBookProvider(cfg)


@contextmanager
def _patch_httpx(payload):
    """替换 httpx.Client，返回可在 with 块内断言的 post mock 上下文."""
    with mock.patch("app.services.enrichment_service.httpx.Client") as MC:
        ctx = MC.return_value.__enter__.return_value
        fake_resp = mock.MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = payload
        ctx.post.return_value = fake_resp
        yield ctx


class TestThreatBookProvider(unittest.TestCase):
    """ThreatBookProvider 行为测试."""

    def test_expand_api_key_ref(self):
        """api_key_ref 以 $ENV_VAR 引用，expand_env 应展开为环境变量值."""
        os.environ["THREATBOOK_KEY"] = "supersecret123"
        provider = _make_provider()
        self.assertEqual(provider.expand_api_key(), "supersecret123")
        del os.environ["THREATBOOK_KEY"]

    def test_query_ip_malicious(self):
        """IP 查询：judgments 含 malicious → threat_level=high."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "1.2.3.4": {
                    "risk_score": 92,
                    "judgments": ["malicious"],
                    "tags": ["c2", "botnet"],
                    "confidence": 95,
                    "company": ["evil-apt"],
                    "attck": [{"tactic": "C2"}],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("ip", "1.2.3.4")
        self.assertEqual(intel.ioc_type, "ip")
        self.assertEqual(intel.ioc_value, "1.2.3.4")
        self.assertEqual(intel.provider, "threatbook")
        self.assertEqual(intel.risk_score, 92)
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.tags, ["c2", "botnet"])
        self.assertEqual(intel.company, ["evil-apt"])
        # URL 拼接与 apikey 参数校验
        ctx.post.assert_called_once()
        call_args = ctx.post.call_args
        self.assertTrue(call_args.kwargs["params"]["apikey"])
        self.assertIn("/v3/scene/ip", call_args.args[0])

    def test_query_domain_suspicious(self):
        """域名查询：judgments 含 suspicious → threat_level=medium."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "evil.example.com": {
                    "risk_score": 65,
                    "judgments": ["suspicious"],
                    "tags": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("domain", "evil.example.com")
        self.assertEqual(intel.threat_level, "medium")
        self.assertEqual(intel.ioc_type, "domain")

    def test_judgments_missing_fallback_by_risk(self):
        """judgments 缺失时按 risk_score 兜底：>=80 high / 60-79 medium / <60 None."""
        provider = _make_provider()
        os.environ["THREATBOOK_KEY"] = "testkey"

        for score, expected in [(85, "high"), (65, "medium"), (30, None)]:
            payload = {
                "response_code": 0,
                "data": {"1.2.3.4": {"risk_score": score, "judgments": []}},
            }
            with _patch_httpx(payload) as ctx:
                intel = provider.query("ip", "1.2.3.4")
            self.assertEqual(
                intel.threat_level, expected, f"risk_score={score} 期望 {expected}"
            )

    def test_response_code_nonzero_raises(self):
        """response_code != 0 应上抛 ThreatIntelQueryError（不落库）."""
        provider = _make_provider()
        payload = {
            "response_code": 401,
            "verbose_msg": "invalid apikey",
            "data": {},
        }
        with _patch_httpx(payload) as ctx:
            with self.assertRaises(ThreatIntelQueryError):
                provider.query("ip", "1.2.3.4")

    def test_unsupported_type_raises(self):
        """不支持的 ioc_type（如 url）应上抛 UnsupportedIocTypeError."""
        provider = _make_provider()
        with self.assertRaises(UnsupportedIocTypeError):
            provider.query("url", "http://x")

    def test_missing_apikey_raises(self):
        """api_key 未配置/环境变量未设置时上抛 ThreatIntelQueryError."""
        provider = _make_provider(api_key_ref="$NOT_SET_VAR_XYZ")
        if "NOT_SET_VAR_XYZ" in os.environ:
            del os.environ["NOT_SET_VAR_XYZ"]
        with self.assertRaises(ThreatIntelQueryError):
            provider.query("ip", "1.2.3.4")

    def test_expand_env_helper(self):
        """expand_env 对 $ 前缀展开，非占位原样返回."""
        os.environ["MY_TEST_KEY"] = "abc"
        self.assertEqual(expand_env("$MY_TEST_KEY"), "abc")
        self.assertEqual(expand_env("plain"), "plain")
        del os.environ["MY_TEST_KEY"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
