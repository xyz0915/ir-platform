"""AlienVault OTX 威胁情报 provider 实现（任务④ 多源聚合）.

端点:
  - IP:     GET https://otx.alienvault.com/api/v1/indicators/IPv4/{ip}/general
  - 域名:   GET https://otx.alienvault.com/api/v1/indicators/domain/{domain}/general
鉴权: Header ``X-OTX-API-KEY: <api_key>``。
归一化: 取 pulse_info.count（关联脉冲数）与脉冲标签推导判定与风险。
"""

import json
import logging

import httpx

from app.services.enrichment_service import (
    BaseThreatIntelProvider,
    ThreatIntelQueryError,
    UnsupportedIocTypeError,
)


class AlienVaultOTXProvider(BaseThreatIntelProvider):
    """AlienVault OTX 威胁情报 provider."""

    BASE_URL = "https://otx.alienvault.com/api/v1/indicators"

    def query(self, ioc_type: str, ioc_value: str) -> "object":
        """查询 AlienVault OTX 情报.

        Raises:
            UnsupportedIocTypeError: 不支持的 ioc_type。
            ThreatIntelQueryError: 鉴权缺失或网络/业务错误。
        """
        if ioc_type == "ip":
            endpoint = f"{self.BASE_URL}/IPv4/{ioc_value}/general"
        elif ioc_type == "domain":
            endpoint = f"{self.BASE_URL}/domain/{ioc_value}/general"
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
                    headers={"X-OTX-API-KEY": api_key},
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

        if not isinstance(payload, dict):
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 返回结构异常"
            )

        pulse_info = payload.get("pulse_info") or {}
        pulse_count = int(pulse_info.get("count", 0) or 0)
        pulses = pulse_info.get("pulses") or []
        tags = self._collect_tags(pulses)

        if pulse_count >= 3:
            judgments = ["malicious"]
            threat_level = "high"
            risk_score = 90
        elif pulse_count >= 1:
            judgments = ["suspicious"]
            threat_level = "medium"
            risk_score = 70
        else:
            judgments = ["clean"]
            threat_level = "low"
            risk_score = 20

        # 置信度随脉冲数提升（封顶 100）
        confidence = min(100, 40 + pulse_count * 15)

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
            raw_summary=f"pulse_count={pulse_count}; confidence={confidence}",
        )

    @staticmethod
    def _collect_tags(pulses: list) -> list:
        """从关联脉冲中提取标签与严重度（去重，封顶 20）."""
        tags: list = []
        for pulse in pulses:
            if not isinstance(pulse, dict):
                continue
            for t in (pulse.get("tags") or []):
                if isinstance(t, str) and t not in tags:
                    tags.append(t)
            sev = pulse.get("severity")
            if sev and f"severity:{sev}" not in tags:
                tags.append(f"severity:{sev}")
            name = pulse.get("name")
            if name and f"pulse:{name}" not in tags:
                tags.append(f"pulse:{name}")
        return tags[:20]

    def fetch_list(self, limit: int = 20) -> list[dict]:
        """获取 AlienVault OTX 订阅脉冲 IOC 列表（Phase 2 — 任务8）.

        调用 /api/v1/pulses/subscribed 获取近期订阅脉冲中的 IOC。

        Args:
            limit: 最大返回条数（默认 20）。

        Returns:
            统一格式列表：
            [{"ioc_type": "ip"/"domain"/"hash", "ioc_value": "...",
              "description": "...", "severity": "high"/"medium"/"low",
              "source": "alienvault_otx"}]
            API key 未配置或请求失败返回 []。
        """
        api_key = self.expand_api_key()
        if not api_key:
            logger = logging.getLogger(__name__)
            logger.warning("AlienVault OTX fetch_list: api_key 未配置，返回空列表")
            return []

        url = "https://otx.alienvault.com/api/v1/pulses/subscribed"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30.0), follow_redirects=True
            ) as client:
                resp = client.get(
                    url,
                    headers={"X-OTX-API-KEY": api_key},
                    params={"limit": min(limit, 50), "sort": "-modified"},
                )
                resp.raise_for_status()
                payload = resp.json()

            results: list[dict] = []
            pulses = (payload.get("results") or [])
            if not isinstance(pulses, list):
                return []

            for pulse in pulses[:limit]:
                if not isinstance(pulse, dict):
                    continue
                pulse_name = pulse.get("name", "")
                pulse_severity = pulse.get("severity", "medium")
                indicators = pulse.get("indicators") or []
                malicious_count = 0

                for ind in indicators[:5]:
                    if not isinstance(ind, dict):
                        continue
                    ioc_type = ind.get("type", "")
                    ioc_value = ind.get("indicator", "")
                    if not ioc_type or not ioc_value:
                        continue

                    # 标准化 ioc_type
                    type_map = {
                        "IPv4": "ip", "IPv6": "ip",
                        "domain": "domain", "hostname": "domain",
                        "FileHash-SHA256": "hash", "FileHash-MD5": "hash",
                        "FileHash-SHA1": "hash",
                    }
                    normalized_type = type_map.get(ioc_type, ioc_type.lower())

                    desc = f"OTX: {pulse_name} — {ind.get('title', ioc_value)}"
                    if pulse_severity in ("high", "medium"):
                        malicious_count += 1

                    results.append({
                        "ioc_type": normalized_type,
                        "ioc_value": ioc_value,
                        "description": desc,
                        "severity": pulse_severity if pulse_severity in ("high", "medium", "low") else "medium",
                        "source": "alienvault_otx",
                        "malicious_count": malicious_count,
                    })

            return results[:limit]
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.warning("AlienVault OTX fetch_list 失败: %s", exc)
            return []
