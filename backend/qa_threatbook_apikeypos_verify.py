#!/usr/bin/env python3
"""独立回归验证脚本：ThreatBookProvider.apikey 传参位置 + normalize 逻辑.

不依赖真实微步 key / 不发起真实网络请求。
通过 monkeypatch 替换 httpx.Client，捕获 get 调用参数，断言：

  1) apikey 传参位置验证（对齐微步官方示例：GET + query params）
     - call_args 为 GET 调用（不再用 form body/data）
     - call_args.kwargs["params"] 同时含 "apikey" 与 "resource"，且值正确
     - 端点路径为 /v3/scene/ip_reputation（修复前为错误的 /v3/scene/ip）

  2) normalize 未破坏验证（适配微步真实返回结构，无 risk_score 字段）
     - mock 微步真实返回 severity=high/is_malicious=True 时，
       query 返回的 NormalizedIntel.threat_level == "high"
       且 judgments 含 "malicious"、risk_score == 90

运行方式：
    backend/venv/Scripts/python.exe backend/qa_threatbook_apikeypos_verify.py

退出码：全部通过 -> 0；任一断言失败 -> 1。打印 PASS/FAIL。
（注：monkeypatch.setenv 的 pytest 等价写法此处用 os.environ 直接设置并清理，
 功能与 monkeypatch.setenv 一致。）
"""

import os
import sys
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.enrichment_service import ThreatBookProvider  # noqa: E402

TEST_ENV_VAR = "QA_THREATBOOK_FAKE_KEY"
TEST_API_KEY = "fake-test-apikey-001"
TEST_IOC_TYPE = "ip"
TEST_IOC_VALUE = "8.8.8.8"


def _make_provider(api_key_ref=f"${TEST_ENV_VAR}"):
    cfg = {
        "name": "threatbook",
        "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": api_key_ref,
        "endpoints": {"ip": "/v3/scene/ip_reputation", "domain": "/v3/domain/query"},
        "rate_limit_qps": 2,
    }
    return ThreatBookProvider(cfg)


def _run_query(payload, api_key_ref=f"${TEST_ENV_VAR}"):
    """替换 httpx.Client，构造微步风格响应，调用 query，返回 (intel, call_args)."""
    provider = _make_provider(api_key_ref=api_key_ref)
    fake_resp = mock.MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = payload

    with mock.patch("app.services.enrichment_service.httpx.Client") as MC:
        ctx = MC.return_value.__enter__.return_value
        ctx.get.return_value = fake_resp
        intel = provider.query(TEST_IOC_TYPE, TEST_IOC_VALUE)
        call_args = ctx.get.call_args
    return intel, call_args


def verify_apikey_in_get_params():
    """断言 apikey+resource 在 GET query params，且端点路径正确（不再用 form body）。"""
    payload = {
        "response_code": 0,
        "data": {
            TEST_IOC_VALUE: {
                "is_malicious": False,
                "severity": "info",
                "confidence_level": "low",
                "judgments": ["Whitelist"],
                "tags_classes": [],
            }
        },
    }
    intel, call_args = _run_query(payload)

    args = call_args.args
    kwargs = call_args.kwargs

    # 1. 端点路径正确（修复前为错误的 /v3/scene/ip）
    assert any("/v3/scene/ip_reputation" in a for a in args), (
        f"GET URL 应为 /v3/scene/ip_reputation，实际 args={args}"
    )

    # 2. 不再使用 form body(data)
    assert "data" not in kwargs, "不应再使用 form body(data)"

    # 3. params 必须存在且含 apikey、resource，且值正确
    assert "params" in kwargs, "GET 调用缺少 params 查询参数"
    params = kwargs["params"]
    assert isinstance(params, dict), "params 应为 dict"
    assert "apikey" in params, "params 中缺少 apikey 键"
    assert params["apikey"] == TEST_API_KEY, (
        f"params.apikey 值错误: 期望 '{TEST_API_KEY}'，实际 '{params['apikey']}'"
    )
    assert "resource" in params, "params 中缺少 resource 键"
    assert params["resource"] == TEST_IOC_VALUE, (
        f"params.resource 值错误: 期望 '{TEST_IOC_VALUE}'，实际 '{params['resource']}'"
    )

    return True


def verify_normalize_malicious_high():
    """断言恶意样本（微步真实结构）归一化结果为 high 且 judgments 含 malicious。"""
    payload = {
        "response_code": 0,
        "data": {
            TEST_IOC_VALUE: {
                "is_malicious": True,
                "severity": "high",
                "confidence_level": "high",
                "judgments": ["Botnet", "C2"],
                "tags_classes": [],
            }
        },
    }
    intel, _ = _run_query(payload)

    assert intel.threat_level == "high", (
        f"threat_level 期望 'high'，实际 {intel.threat_level!r}（normalize 被破坏）"
    )
    assert "malicious" in intel.judgments, (
        f"judgments 应含 'malicious'，实际 {intel.judgments!r}（normalize 被破坏）"
    )
    assert intel.risk_score == 90, f"risk_score 期望 90，实际 {intel.risk_score}"
    return True


def main():
    # 设置测试用假环境变量（等价于 monkeypatch.setenv）
    old_val = os.environ.get(TEST_ENV_VAR)
    os.environ[TEST_ENV_VAR] = TEST_API_KEY

    results = []
    try:
        try:
            verify_apikey_in_get_params()
            results.append(("apikey 传参位置（GET params 含 apikey/resource）", True, ""))
        except AssertionError as exc:
            results.append(("apikey 传参位置", False, str(exc)))

        try:
            verify_normalize_malicious_high()
            results.append(("normalize 逻辑（malicious→high，适配真实结构）", True, ""))
        except AssertionError as exc:
            results.append(("normalize 逻辑", False, str(exc)))
    finally:
        # 清理环境变量
        if old_val is None:
            os.environ.pop(TEST_ENV_VAR, None)
        else:
            os.environ[TEST_ENV_VAR] = old_val

    print("=" * 60)
    print("ThreatBookProvider 独立回归验证（apikey GET params + normalize）")
    print("=" * 60)
    all_pass = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if not ok:
            all_pass = False
            print(f"        -> {detail}")
    print("=" * 60)
    print("OVERALL: " + ("PASS" if all_pass else "FAIL"))
    print("=" * 60)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
