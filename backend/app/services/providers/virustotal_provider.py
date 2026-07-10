"""VirusTotal 威胁情报 provider 实现（任务④ 多源聚合）.

端点（v3，官方文档）:
  - IP:     GET https://www.virustotal.com/api/v3/ip_addresses/{ip}
  - 域名:   GET https://www.virustotal.com/api/v3/domains/{domain}
鉴权: Header ``x-apikey: <api_key>``。
归一化: 取 last_analysis_stats.{malicious,suspicious,harmless} 推导判定与风险。
"""

import json

import httpx

from app.services.enrichment_service import (
    BaseThreatIntelProvider,
    ThreatIntelQueryError,
    UnsupportedIocTypeError,
)


class VirusTotalProvider(BaseThreatIntelProvider):
    """VirusTotal（v3）威胁情报 provider."""

    BASE_URL = "https://www.virustotal.com/api/v3"

    def query(self, ioc_type: str, ioc_value: str) -> "object":
        """查询 VirusTotal 情报.

        Raises:
            UnsupportedIocTypeError: 不支持的 ioc_type。
            ThreatIntelQueryError: 鉴权缺失或网络/业务错误。
        """
        if ioc_type == "ip":
            endpoint = f"{self.BASE_URL}/ip_addresses/{ioc_value}"
        elif ioc_type == "domain":
            endpoint = f"{self.BASE_URL}/domains/{ioc_value}"
        else:
            raise UnsupportedIocTypeError(
                f"provider '{self.name}' 不支持 ioc_type='{ioc_type}'"
            )

        api_key = self.expand_api_key()
        if not api_key:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 的 api_key 未配置或环境变量未设置"
            )

        try:
            with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
                resp = client.get(
                    endpoint,
                    headers={"x-apikey": api_key},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 查询 {ioc_value} 网络异常: {exc}"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 返回非 JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict) or "data" not in payload:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 返回结构异常（缺 data）"
            )

        attrs = (payload.get("data") or {}).get("attributes") or {}
        stats = attrs.get("last_analysis_stats") or {}
        malicious = int(stats.get("malicious", 0) or 0)
        suspicious = int(stats.get("suspicious", 0) or 0)
        harmless = int(stats.get("harmless", 0) or 0)
        undetected = int(stats.get("undetected", 0) or 0)
        total = max(1, malicious + suspicious + harmless + undetected)

        if malicious > 0:
            judgments = ["malicious"]
            threat_level = "high"
            risk_score = 90
        elif suspicious > 0:
            judgments = ["suspicious"]
            threat_level = "medium"
            risk_score = 70
        elif harmless > 0:
            judgments = ["clean"]
            threat_level = "low"
            risk_score = 20
        else:
            judgments = ["unknown"]
            threat_level = None
            risk_score = 0

        confidence = int(round(malicious / total * 100))
        tags = self._collect_tags(attrs)

        return self.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {
                "judgments": judgments,
                "risk_score": risk_score,
                "tags": tags,
                "confidence": confidence,
            },
            raw_summary=(
                f"malicious={malicious}; suspicious={suspicious}; "
                f"harmless={harmless}; confidence={confidence}"
            ),
        )

    @staticmethod
    def _collect_tags(attrs: dict) -> list:
        """收集常见标签（categories / tags / popular_threat_classification）."""
        tags: list = []
        cats = attrs.get("categories") or {}
        if isinstance(cats, dict):
            tags.extend(sorted(set(cats.values())))
        for t in (attrs.get("tags") or []):
            if isinstance(t, str):
                tags.append(t)
        cls = (attrs.get("popular_threat_classification") or {}).get("suggested_threat_label")
        if cls and cls not in tags:
            tags.append(cls)
        return tags[:20]
