#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立回归测试：ThreatBookProvider.normalize 映射规则（严过关 QA 补强）.

本文件独立于工程师的补充测试，直接针对 team-lead 给定的 normalize 映射规则构造
微步「真实返回结构」mock（无 risk_score/attck/company 字段），断言：

  IP 分支:
    - 恶意 (critical):  severity=critical 或 is_malicious=True
                        → threat_level=high, judgments=["malicious"], risk_score=100
    - 可疑 (medium):    severity=medium 或 confidence_level=medium
                        → threat_level=medium, judgments=["suspicious"], risk_score=70
    - 干净 (白名单):    judgments 仅 Whitelist/Info/ICP/CDN 且非恶意
                        → threat_level=None, judgments=["clean"]（不回灌）
    - 未知 (severity 缺省): 无任何 severity/confidence/is_malicious
                        → 兜底 threat_level=low, judgments=["clean"], risk_score=0

  IP 派生细节:
    - risk_score:  critical=100/high=90/medium=70/low=40/info=20,
                  无 severity 时按 confidence_level 映射
    - confidence:  high=100/medium=70/low=40（缺省 0）
    - attck=[]、company=None（NormalizedIntel 契约不变）

  域名 分支:
    - 恶意:  任一 judgment∈MALICIOUS_TYPES 或 sample 含 malicious
             → threat_level=high, judgments=["malicious"], risk_score=90
    - 可疑:  任一 judgment∈SUSPICIOUS_TYPES 或 sample 含 suspicious
             → threat_level=medium, judgments=["suspicious"], risk_score=70
    - 干净:  judgments 全白名单 → threat_level=None, judgments=["clean"], risk_score=10
    - 样本含 malicious:  samples=[{threat_level:"malicious"}] → high
    - confidence: intelligences.threatbook_lab[0].confidence（缺省 0）

运行: backend/venv/Scripts/python.exe -m pytest tests/test_threatbook_normalize.py -q
"""

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.enrichment_service import (  # noqa: E402
    ThreatBookProvider,
    ThreatIntelQueryError,
)


def _make_provider(api_key_ref="$QA_TB_NORM_KEY"):
    return ThreatBookProvider({
        "name": "threatbook",
        "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": api_key_ref,
        "endpoints": {"ip": "/v3/scene/ip_reputation", "domain": "/v3/domain/query"},
        "rate_limit_qps": 2,
    })


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
    ctx.get.assert_called_once()
    call_args = ctx.get.call_args
    assert endpoint_substr in call_args.args[0], (
        f"URL 不含预期端点 '{endpoint_substr}': {call_args.args[0]}"
    )
    assert "data" not in call_args.kwargs, "不应再使用 form body(data)"
    params = call_args.kwargs.get("params", {})
    assert params.get("apikey"), "params 缺少 apikey"
    assert params.get("resource") == ioc_value, (
        f"params.resource 应为 {ioc_value!r}，实际 {params.get('resource')!r}"
    )


# ── 微步真实返回结构构造器 ─────────────────────────────────────
def _tb_ip(value, judgments=None, severity=None, confidence_level=None,
           is_malicious=None, tags_classes=None):
    rec = {"judgments": judgments or [], "tags_classes": tags_classes or []}
    if severity is not None:
        rec["severity"] = severity
    if confidence_level is not None:
        rec["confidence_level"] = confidence_level
    if is_malicious is not None:
        rec["is_malicious"] = is_malicious
    return {"response_code": 0, "data": {value: rec}}


def _tb_domain(value, judgments=None, samples=None, intelligences=None,
               tags_classes=None):
    return {
        "response_code": 0,
        "data": {
            value: {
                "judgments": judgments or [],
                "samples": samples or [],
                "tags_classes": tags_classes or [],
                "intelligences": intelligences or {},
            }
        },
    }


class TestThreatBookNormalizeIP(unittest.TestCase):
    """IP 情报归一化映射规则（/v3/scene/ip_reputation 真实结构）."""

    def setUp(self):
        os.environ["QA_TB_NORM_KEY"] = "qa-fake-key"

    def tearDown(self):
        os.environ.pop("QA_TB_NORM_KEY", None)

    def test_ip_malicious_critical(self):
        """IP 恶意(critical): threat_level=high, judgments=[malicious], risk_score=100."""
        payload = _tb_ip(
            "1.1.1.1", judgments=["Botnet", "C2"], severity="critical",
            confidence_level="high", is_malicious=True,
        )
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("ip", "1.1.1.1")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.risk_score, 100)
        self.assertEqual(intel.confidence, 100)
        self.assertIsNone(intel.company)
        self.assertEqual(intel.attck, [])
        _assert_get_params(ctx, "1.1.1.1", "/v3/scene/ip_reputation")

    def test_ip_malicious_is_malicious_flag(self):
        """IP 仅靠 is_malicious=True（severity=low）也应判 high."""
        payload = _tb_ip(
            "2.2.2.2", judgments=["Malware"], severity="low",
            confidence_level="low", is_malicious=True,
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("ip", "2.2.2.2")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.risk_score, 40)  # severity=low → 40

    def test_ip_suspicious_medium(self):
        """IP 可疑(medium): threat_level=medium, judgments=[suspicious], risk_score=70."""
        payload = _tb_ip(
            "3.3.3.3", judgments=["Scanner"], severity="medium",
            confidence_level="medium",
        )
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("ip", "3.3.3.3")
        self.assertEqual(intel.threat_level, "medium")
        self.assertEqual(intel.judgments, ["suspicious"])
        self.assertEqual(intel.risk_score, 70)
        self.assertEqual(intel.confidence, 70)
        _assert_get_params(ctx, "3.3.3.3", "/v3/scene/ip_reputation")

    def test_ip_medium_by_confidence_only(self):
        """IP 无 severity 但 confidence_level=medium → threat_level=medium, risk_score=70."""
        payload = _tb_ip(
            "3.3.3.4", judgments=["Dynamic IP"], confidence_level="medium",
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("ip", "3.3.3.4")
        self.assertEqual(intel.threat_level, "medium")
        self.assertEqual(intel.risk_score, 70)
        self.assertEqual(intel.confidence, 70)

    def test_ip_clean_whitelist(self):
        """IP 干净(仅白名单类且非恶意): threat_level=None, judgments=[clean]."""
        payload = _tb_ip(
            "4.4.4.4", judgments=["Whitelist"], severity="info",
            confidence_level="low", is_malicious=False,
        )
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("ip", "4.4.4.4")
        self.assertIsNone(intel.threat_level)
        self.assertEqual(intel.judgments, ["clean"])
        self.assertEqual(intel.tags, ["Whitelist"])
        _assert_get_params(ctx, "4.4.4.4", "/v3/scene/ip_reputation")

    def test_ip_clean_whitelist_not_overridden_by_malicious_flag(self):
        """IP 矛盾输入(is_malicious=True 但 judgments=Whitelist): 恶意优先 → high."""
        payload = _tb_ip(
            "4.4.4.5", judgments=["Whitelist"], severity="info",
            confidence_level="low", is_malicious=True,
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("ip", "4.4.4.5")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])

    def test_ip_unknown_severity_defaults_low(self):
        """IP 未知(severity/confidence/is_malicious 全缺省): 兜底 low/clean, risk_score=0."""
        payload = _tb_ip("5.5.5.5", judgments=[])
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("ip", "5.5.5.5")
        self.assertEqual(intel.threat_level, "low")
        self.assertEqual(intel.judgments, ["clean"])
        self.assertEqual(intel.risk_score, 0)
        self.assertEqual(intel.confidence, 0)
        _assert_get_params(ctx, "5.5.5.5", "/v3/scene/ip_reputation")

    def test_ip_risk_score_mapping(self):
        """IP severity→risk_score: critical=100/high=90/medium=70/low=40/info=20."""
        cases = [
            ("critical", 100), ("high", 90), ("medium", 70),
            ("low", 40), ("info", 20),
        ]
        for severity, expect in cases:
            payload = _tb_ip(
                "6.6.6.6", judgments=[], severity=severity,
                confidence_level="low",
            )
            with _patch_httpx(payload):
                intel = _make_provider().query("ip", "6.6.6.6")
            self.assertEqual(intel.risk_score, expect, f"severity={severity}")

    def test_ip_confidence_mapping(self):
        """IP confidence_level→confidence: high=100/medium=70/low=40, 缺省 0."""
        for level, expect in [("high", 100), ("medium", 70), ("low", 40)]:
            payload = _tb_ip(
                "7.7.7.7", judgments=[], severity="info",
                confidence_level=level,
            )
            with _patch_httpx(payload):
                intel = _make_provider().query("ip", "7.7.7.7")
            self.assertEqual(intel.confidence, expect, f"confidence_level={level}")
        # 缺省
        payload = _tb_ip("7.7.7.8", judgments=[])
        with _patch_httpx(payload):
            intel = _make_provider().query("ip", "7.7.7.8")
        self.assertEqual(intel.confidence, 0)


class TestThreatBookNormalizeDomain(unittest.TestCase):
    """域名情报归一化映射规则（/v3/domain/query 真实结构）."""

    def setUp(self):
        os.environ["QA_TB_NORM_KEY"] = "qa-fake-key"

    def tearDown(self):
        os.environ.pop("QA_TB_NORM_KEY", None)

    def test_domain_malicious_by_judgment(self):
        """域名 恶意(judgment 命中 MALICIOUS_TYPES): high, [malicious], risk_score=90."""
        payload = _tb_domain("evil.example.com", judgments=["C2", "Malware"])
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("domain", "evil.example.com")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])
        self.assertEqual(intel.risk_score, 90)
        self.assertIsNone(intel.company)
        self.assertEqual(intel.attck, [])
        _assert_get_params(ctx, "evil.example.com", "/v3/domain/query")

    def test_domain_malicious_by_sample(self):
        """域名 样本含 malicious: threat_level=high, [malicious]."""
        payload = _tb_domain(
            "sample.example.com", judgments=["Whitelist"],
            samples=[{"threat_level": "malicious", "tags": ["C2"]}],
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("domain", "sample.example.com")
        self.assertEqual(intel.threat_level, "high")
        self.assertEqual(intel.judgments, ["malicious"])

    def test_domain_suspicious_by_judgment(self):
        """域名 可疑(judgment∈SUSPICIOUS_TYPES): medium, [suspicious], risk_score=70."""
        payload = _tb_domain("sus.example.com", judgments=["Suspicious"])
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("domain", "sus.example.com")
        self.assertEqual(intel.threat_level, "medium")
        self.assertEqual(intel.judgments, ["suspicious"])
        self.assertEqual(intel.risk_score, 70)
        _assert_get_params(ctx, "sus.example.com", "/v3/domain/query")

    def test_domain_suspicious_by_sample(self):
        """域名 样本含 suspicious: threat_level=medium."""
        payload = _tb_domain(
            "sus2.example.com", judgments=[],
            samples=[{"threat_level": "suspicious"}],
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("domain", "sus2.example.com")
        self.assertEqual(intel.threat_level, "medium")

    def test_domain_clean_whitelist(self):
        """域名 干净(judgments 全白名单): threat_level=None, [clean], risk_score=10."""
        payload = _tb_domain("good.example.com", judgments=["Whitelist", "ICP"])
        with _patch_httpx(payload) as ctx:
            intel = _make_provider().query("domain", "good.example.com")
        self.assertIsNone(intel.threat_level)
        self.assertEqual(intel.judgments, ["clean"])
        self.assertEqual(intel.risk_score, 10)
        _assert_get_params(ctx, "good.example.com", "/v3/domain/query")

    def test_domain_unknown_defaults_low(self):
        """域名 无任何 judgments/samples: 兜底 low, [clean], risk_score=40."""
        payload = _tb_domain("unknown.example.com", judgments=[], samples=[])
        with _patch_httpx(payload):
            intel = _make_provider().query("domain", "unknown.example.com")
        self.assertEqual(intel.threat_level, "low")
        self.assertEqual(intel.judgments, ["clean"])
        self.assertEqual(intel.risk_score, 40)

    def test_domain_confidence_from_intelligence(self):
        """域名 confidence 取自 intelligences.threatbook_lab[0].confidence."""
        payload = _tb_domain(
            "lab.example.com", judgments=["Suspicious"],
            intelligences={"threatbook_lab": [{"confidence": 85}]},
        )
        with _patch_httpx(payload):
            intel = _make_provider().query("domain", "lab.example.com")
        self.assertEqual(intel.confidence, 85)

    def test_domain_confidence_default_zero(self):
        """域名 无 intelligences: confidence 缺省 0."""
        payload = _tb_domain("nolab.example.com", judgments=["Suspicious"])
        with _patch_httpx(payload):
            intel = _make_provider().query("domain", "nolab.example.com")
        self.assertEqual(intel.confidence, 0)


class TestThreatBookEndpointAndErrors(unittest.TestCase):
    """端点路径 / 错误分支独立确认."""

    def setUp(self):
        os.environ["QA_TB_NORM_KEY"] = "qa-fake-key"

    def tearDown(self):
        os.environ.pop("QA_TB_NORM_KEY", None)

    def test_endpoints_from_config_also_used(self):
        """配置 endpoints 与 ENDPOINT_MAP 一致（GET params 验证实际端点）."""
        provider = ThreatBookProvider({
            "name": "threatbook", "type": "threatbook",
            "base_url": "https://api.threatbook.cn",
            "api_key_ref": "$QA_TB_NORM_KEY",
            "endpoints": {"ip": "/v3/scene/ip_reputation",
                          "domain": "/v3/domain/query"},
            "rate_limit_qps": 2,
        })
        payload = _tb_ip("8.8.8.8", judgments=["Botnet"], severity="high",
                         confidence_level="high", is_malicious=True)
        with _patch_httpx(payload) as ctx:
            intel = provider.query("ip", "8.8.8.8")
        _assert_get_params(ctx, "8.8.8.8", "/v3/scene/ip_reputation")
        self.assertEqual(intel.threat_level, "high")

    def test_business_error_raises(self):
        """response_code=-2(Invalid Api method) 仍应上抛 ThreatIntelQueryError."""
        payload = {"response_code": -2, "verbose_msg": "Invalid Api method",
                   "data": {}}
        provider = _make_provider()
        with _patch_httpx(payload):
            with self.assertRaises(ThreatIntelQueryError):
                provider.query("ip", "8.8.8.8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
