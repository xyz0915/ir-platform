#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA 独立验证脚本：IOC 外联威胁情报（Enrichment / Outbound）模块

实跑而非读码验证前任工程师的改动。特点：
  - 隔离临时库（data/qa_ioc_enrich_verify.db），不触碰生产/其他测试库。
  - 全程不联网：用 unittest.mock 替换 httpx.Client，返回构造好的微步风格响应。
  - 直接驱动真实的 ThreatBookProvider / EnrichmentService / RuleEngine / HTTP 接口。

覆盖点：
  A. ThreatBook normalize：judgments 优先 + risk_score 兜底（high / medium / None）。
  B. 落库：enrich_ioc 写一条且字段齐全；清除去重缓存后再次 enrich 同 ioc 保留历史（2 条）。
  C. 配额：daily_quota=1 时第二条被拒（QuotaExceededError），provider.query 仅调用 1 次。
  D. TTL 去重：短时间内同 (value,provider,type) 第二次不重复打 API（query 仅 1 次，落库 1 条）。
  E. 引擎回灌：DB 直写 malicious 情报 + list 规则 → 命中且 severity 升 high、reason 含【威胁情报平台判黑】；
     suspicious → 仅标注【威胁情报平台可疑】且 severity 不变；
     开关 ENABLE_THREAT_INTEL_ENRICHMENT=False 时与无情报完全一致（不升、不标注）。
  F. 非 ip/domain：url / hash / cert 调 enrich API → 400。
  G. providers 接口不泄露 api_key_ref：直读视图函数 + 经 GET /providers 端点断言无明文 key。
  H. API enrich(ip) 成功：code=0 且 threat_level 落库，历史接口可查。

运行：backend/venv/Scripts/python.exe qa_ioc_enrich_verify.py
退出码：0=全通过，1=存在失败项。
"""

import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 必须在导入任何 app 模块前设置独立测试库 ──────────────────────────
from app.config import settings  # noqa: E402

QA_DB_PATH = str(BACKEND_DIR / "data" / "qa_ioc_enrich_verify.db")
_db_file = Path(QA_DB_PATH)
if _db_file.exists():
    _db_file.unlink()
settings.DB_PATH = QA_DB_PATH

# 提供 api_key 环境变量，供 ThreatBookProvider.expand_api_key 展开
# （mock 下不会真正联网，仅用于通过「api_key 未配置」的校验分支）
os.environ["THREATBOOK_KEY"] = "qa_mock_api_key_12345"

from app.database import init_db  # noqa: E402
init_db()

from app.models.ioc import Ioc  # noqa: E402
from app.models.threat_intel import ThreatIntel, ThreatIntelProviderConfig  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    ThreatBookProvider,
    QuotaExceededError,
)
from app.rules.rule_engine import RuleEngine  # noqa: E402
from app.api.threat_intel import _to_provider_config_view  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


# ── 真实 ThreatBookProvider + 调用计数 ─────────────────────────────
class CountingThreatBookProvider(ThreatBookProvider):
    """复用真实 ThreatBookProvider.query，仅额外记录调用次数（联网由 httpx mock 拦截）。"""

    def __init__(self, config):
        super().__init__(config)
        self.query_calls = []

    def query(self, ioc_type, ioc_value):
        self.query_calls.append((ioc_type, ioc_value))
        return super().query(ioc_type, ioc_value)


def _make_provider():
    return CountingThreatBookProvider({
        "name": "threatbook",
        "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": "$THREATBOOK_KEY",
        "endpoints": {"ip": "/v3/scene/ip", "domain": "/v3/domain/adv"},
        "rate_limit_qps": 1000,  # 测试内避免限流 sleep
    })


@contextmanager
def _patch_threatbook_httpx(payload):
    """替换 app.services.enrichment_service.httpx.Client，返回构造好的微步风格响应。"""
    with mock.patch("app.services.enrichment_service.httpx.Client") as MC:
        ctx = MC.return_value.__enter__.return_value
        fake_resp = mock.MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = payload
        ctx.post.return_value = fake_resp
        yield ctx


def _threatbook_payload(ioc_value, judgments=None, risk_score=0, **extra):
    data = {
        ioc_value: {
            "risk_score": risk_score,
            "judgments": judgments or [],
            "tags": extra.get("tags", ["qa-tag"]),
            "confidence": extra.get("confidence", 90),
            "company": extra.get("company", ["apt-qa"]),
            "attck": extra.get("attck", [{"tactic": "C2", "technique": "T1071"}]),
        }
    }
    return {"response_code": 0, "data": data}


# ── 结果收集 ─────────────────────────────────────────────────────
RESULTS = []


def _record(name, passed, detail):
    RESULTS.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"       {detail}")


def _fresh_service():
    EnrichmentService._instance = None
    return EnrichmentService()


def _clear_tables():
    from app.database import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM threat_intel")
        conn.execute("DELETE FROM iocs")


def _rel(x):
    return "None" if x is None else x


# ── A. normalize ─────────────────────────────────────────────────
def check_normalize():
    cases = [
        ("A1", "1.2.3.4", ["malicious"], 92, "high"),
        ("A2", "evil.example.com", ["suspicious"], 65, "medium"),
        ("A3", "5.5.5.5", [], 90, "high"),     # risk 兜底 malicious(high)
        ("A4", "6.6.6.6", [], 70, "medium"),   # risk 兜底 suspicious(medium)
        ("A5", "7.7.7.7", [], 30, None),       # risk 兜底 clean(None, 不回灌)
    ]
    detail = []
    all_ok = True
    for cid, val, judg, score, expect in cases:
        provider = _make_provider()
        payload = _threatbook_payload(val, judgments=judg, risk_score=score)
        with _patch_threatbook_httpx(payload):
            intel = provider.query("ip", val)
        ok = (intel.threat_level == expect)
        all_ok = all_ok and ok
        detail.append(
            f"{cid}:judg={judg},rs={score}→level={intel.threat_level}(期望{_rel(expect)})"
        )
    _record("A.ThreatBook normalize(judgments优先/risk兜底)", all_ok, "; ".join(detail))


# ── B. 落库 + 历史保留 ─────────────────────────────────────────
def check_persist_and_history():
    provider = _make_provider()
    payload = _threatbook_payload("9.9.9.9", judgments=["malicious"], risk_score=92)
    _clear_tables()
    with mock.patch.object(EnrichmentService, "get_provider", return_value=provider):
        svc = _fresh_service()
        ioc = Ioc.create(ioc_type="ip", ioc_value="9.9.9.9", source="user")
        with _patch_threatbook_httpx(payload):
            rec = svc.enrich_ioc(ioc["id"], "ip", "9.9.9.9")
        fields_ok = (
            rec["ioc_value"] == "9.9.9.9"
            and rec["provider"] == "threatbook"
            and rec["risk_score"] == 92
            and rec["judgments"] == ["malicious"]
            and rec["threat_level"] == "high"
            and rec["tags"] == ["qa-tag"]
            and rec["confidence"] == 90
            and rec["company"] == ["apt-qa"]
            and rec["attck"] == [{"tactic": "C2", "technique": "T1071"}]
        )
        count1 = len(ThreatIntel.list_by_ioc(ioc["id"]))

        # 清除去重缓存后再次 enrich 同 ioc → 保留历史（2 条）
        svc.clear_dedup()
        with _patch_threatbook_httpx(payload):
            svc.enrich_ioc(ioc["id"], "ip", "9.9.9.9")
        count2 = len(ThreatIntel.list_by_ioc(ioc["id"]))

    ok = fields_ok and count1 == 1 and count2 == 2
    _record("B.落库字段齐全 + 同ioc保留历史(2条)", ok,
            f"首条字段齐全={fields_ok}; 首条后记录数={count1}(期望1); "
            f"去重缓存清除后再查后记录数={count2}(期望2)")


# ── C. 配额 ─────────────────────────────────────────────────────
def check_quota():
    provider = _make_provider()
    svc = _fresh_service()
    svc._daily_quota = 1  # 强制配额=1
    _clear_tables()
    first_ok = False
    second_rejected = False
    with mock.patch.object(EnrichmentService, "get_provider", return_value=provider):
        with _patch_threatbook_httpx(
            _threatbook_payload("1.1.1.1", judgments=["malicious"], risk_score=90)
        ):
            try:
                svc.enrich_ioc(None, "ip", "1.1.1.1")
                first_ok = True
            except Exception as exc:  # noqa: BLE001
                first_ok = False
        with _patch_threatbook_httpx(
            _threatbook_payload("2.2.2.2", judgments=["malicious"], risk_score=90)
        ):
            try:
                svc.enrich_ioc(None, "ip", "2.2.2.2")
            except QuotaExceededError:
                second_rejected = True
    ok = first_ok and second_rejected and len(provider.query_calls) == 1
    _record("C.配额生效(第二条被拒, query仅1次)", ok,
            f"首条成功={first_ok}; 第二条QuotaExceeded被拒={second_rejected}; "
            f"query调用次数={len(provider.query_calls)}(期望1)")


# ── D. TTL 去重 ─────────────────────────────────────────────────
def check_ttl_dedup():
    provider = _make_provider()
    svc = _fresh_service()
    _clear_tables()
    with mock.patch.object(EnrichmentService, "get_provider", return_value=provider):
        payload = _threatbook_payload("8.8.8.8", judgments=["malicious"], risk_score=90)
        with _patch_threatbook_httpx(payload):
            svc.enrich_ioc(None, "ip", "8.8.8.8")
            svc.enrich_ioc(None, "ip", "8.8.8.8")  # 短期重复，应命中内存去重
    count = len(provider.query_calls)
    stored = len(ThreatIntel.list_by_value("8.8.8.8"))
    ok = count == 1 and stored == 1
    _record("D.TTL去重(重复enrich仅1次query, 1条记录)", ok,
            f"query调用次数={count}(期望1); 落库记录数={stored}(期望1)")


# ── E. 引擎回灌 ────────────────────────────────────────────────
def check_engine_feedback():
    _clear_tables()
    ip = "203.0.113.50"
    ThreatIntel.create(
        ioc_id=None, ioc_type="ip", ioc_value=ip, provider="threatbook",
        risk_score=90, judgments=["malicious"], threat_level="high",
    )
    rule = {
        "name": "qa_ti_fb", "rule_type": "list", "severity": "medium",
        "condition": {"field": "remote_address", "values": [ip], "match_mode": "exact"},
    }
    matches = RuleEngine.evaluate([{"remote_address": ip}], [rule])
    ok_mal = (
        len(matches) == 1
        and matches[0]["severity"] == "high"
        and "【威胁情报平台判黑】" in matches[0]["reason"]
    )

    # suspicious：severity 不变，reason 含【威胁情报平台可疑】
    ip2 = "203.0.113.51"
    ThreatIntel.create(
        ioc_id=None, ioc_type="ip", ioc_value=ip2, provider="threatbook",
        risk_score=70, judgments=["suspicious"], threat_level="medium",
    )
    rule2 = {
        "name": "qa_ti_fb2", "rule_type": "list", "severity": "medium",
        "condition": {"field": "remote_address", "values": [ip2], "match_mode": "exact"},
    }
    m2 = RuleEngine.evaluate([{"remote_address": ip2}], [rule2])
    ok_susp = (
        len(m2) == 1
        and m2[0]["severity"] == "medium"
        and "【威胁情报平台可疑】" in m2[0]["reason"]
        and "【威胁情报平台判黑】" not in m2[0]["reason"]
    )

    # 开关关闭：与无情报一致（不升、不标注）
    _clear_tables()
    ThreatIntel.create(
        ioc_id=None, ioc_type="ip", ioc_value=ip, provider="threatbook",
        risk_score=90, judgments=["malicious"], threat_level="high",
    )
    settings.ENABLE_THREAT_INTEL_ENRICHMENT = False
    try:
        m3 = RuleEngine.evaluate([{"remote_address": ip}], [rule])
    finally:
        settings.ENABLE_THREAT_INTEL_ENRICHMENT = True
    ok_off = (
        len(m3) == 1
        and m3[0]["severity"] == "medium"
        and "威胁情报平台" not in m3[0]["reason"]
    )

    ok = ok_mal and ok_susp and ok_off
    _record("E.引擎回灌(malicious→high+判黑; suspicious→可疑; 开关关零影响)", ok,
            f"malicious升级={ok_mal}; suspicious标注={ok_susp}; 开关关零影响={ok_off}")


# ── F. 非 ip/domain → 400 ──────────────────────────────────────
def check_non_supported_400(client, headers):
    values = {
        "url": "http://evil.example.com/loader",
        "hash": "44d88612fea8a8f36de82e1278abb02f",
        "cert": "CN=evil-qa,OU=redteam",
    }
    detail = []
    all_ok = True
    for itype in ("url", "hash", "cert"):
        create = client.post(
            "/api/iocs", headers=headers,
            json={"ioc_type": itype, "ioc_value": values[itype], "enabled": True},
        )
        ioc_id = create.json()["data"]["id"]
        resp = client.post(f"/api/iocs/{ioc_id}/enrich", headers=headers, json={})
        code = resp.json().get("code")
        ok = code == 400
        all_ok = all_ok and ok
        detail.append(f"{itype}→code={code}(期望400)")
    _record("F.非ip/domain enrich API→400", all_ok, "; ".join(detail))


# ── G. providers 不泄露 api_key_ref ────────────────────────────
def check_providers_no_leak(client, headers):
    # G1: 直读视图函数
    provider_cfg = {
        "name": "threatbook", "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": "SUPER_SECRET_KEY_VALUE",
        "enabled": True, "rate_limit_qps": 2, "endpoints": {},
    }
    view = _to_provider_config_view(provider_cfg)
    view_dict = view.model_dump()  # ProviderConfig 是 pydantic 对象，需转 dict
    g1_ok = ("api_key_ref" not in view_dict) and (
        "SUPER_SECRET_KEY_VALUE" not in json.dumps(view_dict, ensure_ascii=False)
    )

    # G2: 经 GET /providers 端点（mock load 返回含明文的配置）
    fake_loaded = [{
        "name": "threatbook", "type": "threatbook",
        "base_url": "https://api.threatbook.cn",
        "api_key_ref": "$THREATBOOK_KEY_PLAIN_SECRET",
        "enabled": True, "rate_limit_qps": 2, "endpoints": {},
    }]
    with mock.patch.object(ThreatIntelProviderConfig, "load", return_value=fake_loaded):
        resp = client.get("/api/threat-intel/providers", headers=headers)
    body = resp.json()
    g2_ok = (resp.status_code == 200 and body.get("code") == 0)
    leak = False
    for p in body.get("data", []):
        if "api_key_ref" in p:
            leak = True
        if "THREATBOOK_KEY_PLAIN_SECRET" in json.dumps(p, ensure_ascii=False):
            leak = True
    g2_ok = g2_ok and (not leak) and len(body.get("data", [])) >= 1

    ok = g1_ok and g2_ok
    _record("G.providers接口不泄露api_key_ref", ok,
            f"视图函数剔除key={g1_ok}; 端点返回无明文key={g2_ok}")


# ── H. API enrich(ip) 成功 ─────────────────────────────────────
def check_api_enrich_success(client, headers):
    provider = _make_provider()
    _clear_tables()
    EnrichmentService._instance = None
    with mock.patch.object(EnrichmentService, "get_provider", return_value=provider):
        create = client.post(
            "/api/iocs", headers=headers,
            json={"ioc_type": "ip", "ioc_value": "7.7.7.7", "enabled": True},
        )
        ioc_id = create.json()["data"]["id"]
        with _patch_threatbook_httpx(
            _threatbook_payload("7.7.7.7", judgments=["malicious"], risk_score=92)
        ):
            resp = client.post(f"/api/iocs/{ioc_id}/enrich", headers=headers, json={})
    body = resp.json()
    ok = (body.get("code") == 0 and body.get("data", {}).get("threat_level") == "high")
    hist = client.get(f"/api/iocs/{ioc_id}/threat-intel", headers=headers)
    ok = ok and hist.json().get("code") == 0 and len(hist.json().get("data", [])) == 1
    _record("H.API enrich(ip)成功落库+历史接口", ok,
            f"enrich code={body.get('code')}, threat_level={body.get('data', {}).get('threat_level')}; "
            f"历史条数={len(hist.json().get('data', []))}")


def main():
    print("=" * 72)
    print("QA 独立验证：IOC 外联威胁情报（Enrichment）模块")
    print(f"隔离测试库: {QA_DB_PATH}")
    print("=" * 72)

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json().get("data", {}).get("token")
    headers = {"Authorization": f"Bearer {token}"}
    if not token:
        _record("0.登录获取token", False, f"login={login.status_code} {login.text[:200]}")
        _print_summary_and_exit()

    try:
        check_normalize()
        check_persist_and_history()
        check_quota()
        check_ttl_dedup()
        check_engine_feedback()
        check_non_supported_400(client, headers)
        check_providers_no_leak(client, headers)
        check_api_enrich_success(client, headers)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 验证脚本执行异常: {exc}")
        traceback.print_exc()
        RESULTS.append(("EXCEPTION", False, str(exc)))

    _print_summary_and_exit()


def _print_summary_and_exit():
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print("-" * 72)
    print(f"总结: 共 {total} 项，通过 {passed}，失败 {failed}")
    print("-" * 72)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
