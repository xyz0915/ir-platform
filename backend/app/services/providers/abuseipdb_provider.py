"""AbuseIPDB 威胁情报 provider 实现（任务④ 多源聚合）.

端点:
  - IP:  GET https://api.abuseipdb.com/api/v2/check?ipAddress={ip}&maxAgeInDays=90
         （域名查询 AbuseIPDB 不支持，仅 ip）
鉴权: Header ``Key: <api_key>`` + ``Accept: application/json``。
归一化: 取 data.abuseScore（0-100）与 totalReports 推导判定与风险。
"""

import json
import logging

import httpx

from app.services.enrichment_service import (
    BaseThreatIntelProvider,
    ThreatIntelQueryError,
    UnsupportedIocTypeError,
)


class AbuseIPDBProvider(BaseThreatIntelProvider):
    """AbuseIPDB 威胁情报 provider（仅支持 ip）."""

    BASE_URL = "https://api.abuseipdb.com/api/v2"

    def query(self, ioc_type: str, ioc_value: str) -> "object":
        """查询 AbuseIPDB 情报.

        Raises:
            UnsupportedIocTypeError: 非 ip 类型（域名不支持）。
            ThreatIntelQueryError: 鉴权缺失或网络/业务错误。
        """
        if ioc_type != "ip":
            raise UnsupportedIocTypeError(
                f"provider '{self.name}' 仅支持 ioc_type='ip'，收到 '{ioc_type}'"
            )

        api_key = self.expand_api_key()
        if not api_key:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 的 api_key 未配置或环境变量未设置"
            )

        url = f"{self.BASE_URL}/check"
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
                resp = client.get(
                    url,
                    params={"ipAddress": ioc_value, "maxAgeInDays": 90},
                    headers={"Key": api_key, "Accept": "application/json"},
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

        data = (payload or {}).get("data") or {}
        if not isinstance(data, dict):
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 返回结构异常（缺 data）"
            )

        abuse_score = int(data.get("abuseScore", 0) or 0)
        total_reports = int(data.get("totalReports", 0) or 0)
        is_whitelisted = bool(data.get("isWhitelisted"))

        if is_whitelisted:
            judgments = ["clean"]
            threat_level = None
            risk_score = 5
        elif abuse_score >= 80:
            judgments = ["malicious"]
            threat_level = "high"
            risk_score = 90
        elif abuse_score >= 50:
            judgments = ["suspicious"]
            threat_level = "medium"
            risk_score = 70
        else:
            judgments = ["clean"]
            threat_level = "low"
            risk_score = 20

        return self.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {
                "judgments": judgments,
                "risk_score": risk_score,
                "tags": [f"abuseScore:{abuse_score}", f"reports:{total_reports}"],
                "confidence": abuse_score,
            },
            raw_summary=(
                f"abuseScore={abuse_score}; totalReports={total_reports}; "
                f"whitelisted={is_whitelisted}"
            ),
        )

    def fetch_list(self, limit: int = 20) -> list[dict]:
        """获取 AbuseIPDB 黑名单 IOC 列表（Phase 2 — 任务8）.

        调用 /api/v2/blacklist 获取近期恶意 IP 列表。

        Args:
            limit: 最大返回条数（默认 20）。

        Returns:
            统一格式列表：
            [{"ioc_type": "ip", "ioc_value": "...",
              "description": "...", "severity": "high"/"medium"/"low",
              "source": "abuseipdb"}]
            API key 未配置或请求失败返回 []。
        """
        api_key = self.expand_api_key()
        if not api_key:
            logger = logging.getLogger(__name__)
            logger.warning("AbuseIPDB fetch_list: api_key 未配置，返回空列表")
            return []

        url = f"{self.BASE_URL}/blacklist"
        params = {
            "confidenceMinimum": 90,
            "limit": min(limit, 100),
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30.0), follow_redirects=True
            ) as client:
                resp = client.get(
                    url,
                    params=params,
                    headers={"Key": api_key, "Accept": "application/json"},
                )
                resp.raise_for_status()
                payload = resp.json()

            results: list[dict] = []
            data_list = (payload.get("data") or [])
            if not isinstance(data_list, list):
                return []

            for item in data_list[:limit]:
                if not isinstance(item, dict):
                    continue
                ip = item.get("ipAddress", "")
                score = int(item.get("abuseConfidenceScore", 0) or 0)
                count = int(item.get("totalReports", 0) or 0)

                sev = "high" if score >= 80 else "medium" if score >= 50 else "low"
                desc = f"AbuseIPDB: {ip} (score={score}, reports={count})"

                results.append({
                    "ioc_type": "ip",
                    "ioc_value": ip,
                    "description": desc,
                    "severity": sev,
                    "source": "abuseipdb",
                    "malicious_count": count if score >= 50 else 0,
                })
            return results
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.warning("AbuseIPDB fetch_list 失败: %s", exc)
            return []
