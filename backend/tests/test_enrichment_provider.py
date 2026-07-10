#!/usr/bin/env python3
"""ThreatBookProvider 单元测试（T2 验收点）.

使用 unittest.mock 替换 httpx.Client，不发起真实网络请求，验证:
  - GET + query params(apikey/resource) 发请求（对齐微步官方示例）
  - normalize 适配微步真实返回结构（IP / 域名分别处理）
  - threat_level / judgments / risk_score 派生正确
  - clean 特判（仅白名单类）→ threat_level=None、judgments=["clean"]（不回灌）
  - response_code != 0 上抛 ThreatIntelQueryError（不落库）
  - 不支持的 ioc_type 上抛 UnsupportedIocTypeError
  - api_key 未配置上抛 ThreatIntelQueryError
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
        "endpoints": {"ip": "/v3/scene/ip_reputation", "domain": "/v3/domain/query"},
        "rate_limit_qps": 2,
    }
    return ThreatBookProvider(cfg)


@contextmanager
def _patch_httpx(payload):
    """替换 httpx.Client，返回可在 with 块内断言的 get mock 上下文."""
    with mock.patch("app.services.enrichment_service.httpx.Client") as MC:
        ctx = MC.return_value.__enter__.return_value
        fake_resp = mock.MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = payload
        ctx.get.return_value = fake_resp
        yield ctx


def _assert_get_params(ctx, ioc_value, endpoint_substr):
    """断言请求为 GET 且 query params 含 apikey + resource."""
    ctx.get.assert_called_once()
    call_args = ctx.get.call_args
    # 端点路径正确
    assert endpoint_substr in call_args.args[0], (
        f"URL 不含预期端点 '{endpoint_substr}': {call_args.args[0]}"
    )
    # 通过 query params 传递 apikey + resource，不再用 form body(data)
    assert "data" not in call_args.kwargs, "不应再使用 form body(data)"
    params = call_args.kwargs.get("params", {})
    assert params.get("apikey"), "params 缺少 apikey"
    assert params.get("resource") == ioc_value, (
        f"params.resource 应为 {ioc_value!r}，实际 {params.get('resource')!r}"
    )


class TestThreatBookProvider(unittest.TestCase):
    """ThreatBookProvider 行为测试（对齐微步真实返回结构）."""

    def test_expand_api_key_ref(self):
        """api_key_ref 以 $ENV_VAR 引用，expand_env 应展开为环境变量值."""
        os.environ["THREATBOOK_KEY"] = "supersecret123"
        provider = _make_provider()
        self.assertEqual(provider.expand_api_key(), "supersecret123")
        del os.environ["THREATBOOK_KEY"]

    def test_query_ip_malicious(self):
        """IP 查询：severity=high → threat_level=high, judgments=[malicious], risk_score=90."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "8.8.8.8": {
                    "is_malicious": True,
                    "severity": "high",
                    "confidence_level": "high",
                    "judgments": ["Botnet", "C2"],
                    "tags_classes": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("ip", "8.8.8.8")
        self.assertEqual(intel.ioc_type, "ip")
        self.assertEqual(intel.ioc_value, "8.8.8.8")
        self.assertEqual(intel.provider, "threatbook")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.risk_score, 90)
        self.assertEqual(intel.tags, ["Botnet", "C2"])
        self.assertEqual(intel.company, None)
        self.assertEqual(intel.attck, [])
        _assert_get_params(ctx, "8.8.8.8", "/v3/scene/ip_reputation")

    def test_query_domain_malicious(self):
        """域名查询：judgments 含 C2/Malware → threat_level=high."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "evil.example.com": {
                    "judgments": ["C2", "Malware"],
                    "samples": [{"threat_level": "malicious"}],
                    "tags_classes": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("domain", "evil.example.com")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.risk_score, 90)
        self.assertEqual(intel.ioc_type, "domain")
        self.assertEqual(intel.company, None)
        self.assertEqual(intel.attck, [])
        _assert_get_params(ctx, "evil.example.com", "/v3/domain/query")

    def test_query_ip_clean(self):
        """IP 查询：仅白名单类(Whitelist)且非恶意 → threat_level=None, judgments=[clean]."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "1.2.3.4": {
                    "is_malicious": False,
                    "severity": "info",
                    "confidence_level": "low",
                    "judgments": ["Whitelist"],
                    "tags_classes": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("ip", "1.2.3.4")
        self.assertIsNone(intel.threat_level)
        self.assertEqual(intel.judgments, ["clean"])
        self.assertEqual(intel.tags, ["Whitelist"])
        _assert_get_params(ctx, "1.2.3.4", "/v3/scene/ip_reputation")

    def test_query_domain_whitelist(self):
        """域名查询：judgments 全白名单(Whitelist/ICP) → threat_level=None, judgments=[clean]."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "good.example.com": {
                    "judgments": ["Whitelist", "ICP"],
                    "samples": [],
                    "tags_classes": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("domain", "good.example.com")
        self.assertIsNone(intel.threat_level)
        self.assertEqual(intel.judgments, ["clean"])
        _assert_get_params(ctx, "good.example.com", "/v3/domain/query")

    def test_query_ip_medium(self):
        """IP 查询：severity=medium → threat_level=medium, judgments=[suspicious]."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        provider = _make_provider()
        payload = {
            "response_code": 0,
            "data": {
                "5.5.5.5": {
                    "severity": "medium",
                    "confidence_level": "medium",
                    "judgments": ["Scanner"],
                    "tags_classes": [],
                }
            },
        }
        with _patch_httpx(payload) as ctx:
            intel = provider.query("ip", "5.5.5.5")
        self.assertEqual(intel.threat_level, "medium")
        self.assertEqual(intel.judgments, ["suspicious"])
        self.assertEqual(intel.risk_score, 70)
        _assert_get_params(ctx, "5.5.5.5", "/v3/scene/ip_reputation")

    def test_ip_severity_maps_to_level(self):
        """IP severity → threat_level 映射：critical/high→high, medium→medium, low/info→low."""
        os.environ["THREATBOOK_KEY"] = "testkey"
        cases = [
            ("critical", "high"),
            ("high", "high"),
            ("medium", "medium"),
            ("low", "low"),
            ("info", "low"),
        ]
        for severity, expect in cases:
            payload = {
                "response_code": 0,
                "data": {
                    "1.2.3.4": {
                        "severity": severity,
                        "confidence_level": "low",
                        "judgments": [],
                        "tags_classes": [],
                    }
                },
            }
            provider = _make_provider()
            with _patch_httpx(payload):
                intel = provider.query("ip", "1.2.3.4")
            self.assertEqual(
                intel.threat_level, expect, f"severity={severity} 期望 {expect}"
            )

    def test_response_code_nonzero_raises(self):
        """response_code != 0 应上抛 ThreatIntelQueryError（不落库）."""
        provider = _make_provider()
        payload = {
            "response_code": 401,
            "verbose_msg": "invalid apikey",
            "data": {},
        }
        with _patch_httpx(payload):
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
