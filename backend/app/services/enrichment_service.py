"""IOC 外联威胁情报查询（Enrichment / Outbound）服务层.

职责:
  - 定义 provider 抽象契约 ``BaseThreatIntelProvider`` 与微步实现 ``ThreatBookProvider``。
  - ``EnrichmentService`` 负责：
      * 选择 provider（默认首个 enabled；或按名称指定）
      * 运行时内存 TTL 去重（默认 10min）防重复打 API
      * 当日配额（自然日重置）控制
      * 落库 ``threat_intel``（保留全历史不去重）
      * 单 provider 串行 + 限流（rate_limit_qps）
      * ``enrich_ioc`` / ``enrich_batch`` / ``scan_pending_iocs``

约定:
  - 统一使用项目已安装的 ``httpx`` 同步 Client（与 ``ioc_feed_sync.py`` 一致）。
  - apikey 一律 ``$ENV_VAR`` 引用，运行期 ``expand_env`` 展开，不落明文。
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.models.threat_intel import ThreatIntel, ThreatIntelProviderConfig, EnrichSettings

logger = logging.getLogger(__name__)


# ── 异常定义 ────────────────────────────────────────────────────────
class ThreatIntelQueryError(Exception):
    """威胁情报查询失败（网络/业务错误/无可用 provider）."""


class UnsupportedIocTypeError(Exception):
    """该 IOC 类型不支持外联查询（仅 ip/domain 支持）."""


class QuotaExceededError(Exception):
    """当日配额已耗尽."""


def expand_env(value: Any) -> Any:
    """展开以 ``$`` 开头的环境变量占位符（复用 ioc_feed_sync 语义）.

    Args:
        value: 待展开的值，仅当其为字符串且以 ``$`` 开头时展开。

    Returns:
        展开后的字符串；未设置对应环境变量时返回空字符串；非占位值原样返回。
    """
    if isinstance(value, str) and value.startswith("$"):
        var_name = value[1:]
        return os.environ.get(var_name, "")
    return value


# ── 归一化结构 ──────────────────────────────────────────────────────
@dataclass
class NormalizedIntel:
    """provider 查询结果的归一化结构（跨 provider 统一）.

    Attributes:
        ioc_type: IOC 类型（ip/domain）。
        ioc_value: 指标值。
        provider: provider 名称。
        risk_score: 风险评分 0-100。
        judgments: 判定数组（malicious/suspicious/clean/unknown）。
        tags: 标签数组。
        confidence: 置信度 0-100。
        company: 关联团伙/组织列表。
        attck: ATT&CK 矩阵信息。
        threat_level: 派生冗余等级（high/medium/low/None）。
        raw_summary: 原始摘要文本。
        queried_at: 查询时间（默认当前）。
    """

    ioc_type: str = ""
    ioc_value: str = ""
    provider: str = ""
    risk_score: int = 0
    judgments: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    confidence: int = 0
    company: List[Any] = field(default_factory=list)
    attck: List[Any] = field(default_factory=list)
    threat_level: Optional[str] = None
    raw_summary: str = ""
    queried_at: str = field(default_factory=lambda: "")
    # 任务④ 多源聚合：参与本次判定的 provider 列表与共识判定
    providers: List[str] = field(default_factory=list)
    consensus: str = ""  # "" / "single_source" / "multi_source"

    @staticmethod
    def _level_from_judgments(judgments: List[str], risk_score: int) -> Optional[str]:
        """由 judgments 推导 threat_level；缺失时按 risk_score 兜底.

        - 含 malicious → high
        - 含 suspicious → medium
        - 否则按 risk_score: ≥80 malicious(high) / 60-79 suspicious(medium) / <60 clean(None)
        """
        jset = {str(j).lower() for j in (judgments or [])}
        if "malicious" in jset:
            return "high"
        if "suspicious" in jset:
            return "medium"
        try:
            rs = int(risk_score or 0)
        except (ValueError, TypeError):
            rs = 0
        if rs >= 80:
            return "high"
        if 60 <= rs <= 79:
            return "medium"
        return None

    def to_threat_intel_kwargs(self, ioc_id: Optional[int] = None) -> Dict[str, Any]:
        """转为 ``ThreatIntel.create`` 的关键字参数."""
        return {
            "ioc_id": ioc_id,
            "ioc_type": self.ioc_type,
            "ioc_value": self.ioc_value,
            "provider": self.provider,
            "risk_score": int(self.risk_score or 0),
            "judgments": list(self.judgments or []),
            "tags": list(self.tags or []),
            "confidence": int(self.confidence or 0),
            "attck": list(self.attck or []),
            "company": list(self.company or []),
            "threat_level": self.threat_level,
            "raw_summary": self.raw_summary,
            "providers": list(self.providers or []),
            "consensus": self.consensus or "",
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为普通 dict（供缓存/调试）."""
        return {
            "ioc_type": self.ioc_type,
            "ioc_value": self.ioc_value,
            "provider": self.provider,
            "risk_score": self.risk_score,
            "judgments": list(self.judgments or []),
            "tags": list(self.tags or []),
            "confidence": self.confidence,
            "company": list(self.company or []),
            "attck": list(self.attck or []),
            "threat_level": self.threat_level,
            "raw_summary": self.raw_summary,
            "providers": list(self.providers or []),
            "consensus": self.consensus or "",
        }


# ── Provider 抽象契约 ───────────────────────────────────────────────
class BaseThreatIntelProvider:
    """威胁情报 provider 抽象基类.

    子类必须实现 ``query``，契约::

        def query(self, ioc_type: str, ioc_value: str) -> NormalizedIntel: ...

    所有网络请求应使用项目已安装的 ``httpx`` 同步 Client。
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """由 provider 配置 dict 初始化.

        Args:
            config: 包含 name/type/base_url/api_key_ref/endpoints/rate_limit_qps 等。
        """
        self.name: str = config.get("name", "")
        self.provider_type: str = config.get("type", "")
        self.base_url: str = (config.get("base_url") or "").rstrip("/")
        self.api_key_ref: str = config.get("api_key_ref", "")
        self.endpoints: Dict[str, str] = config.get("endpoints") or {}
        self.rate_limit_qps: int = int(
            config.get("rate_limit_qps", settings.DEFAULT_RATE_LIMIT_QPS)
        )

    def expand_api_key(self) -> str:
        """展开 api_key_ref 占位符，返回实际 api key（可能为空字符串）."""
        return str(expand_env(self.api_key_ref))

    def query(self, ioc_type: str, ioc_value: str) -> NormalizedIntel:
        """查询单个 IOC 的威胁情报，返回归一化结果.

        Raises:
            NotImplementedError: 子类未实现。
            UnsupportedIocTypeError: 该 provider 不支持此 ioc_type。
            ThreatIntelQueryError: 查询失败（网络/业务错误）。
        """
        raise NotImplementedError("子类必须实现 query()")

    @staticmethod
    def build_normalized(
        ioc_type: str,
        ioc_value: str,
        provider: str,
        verdict: Dict[str, Any],
        raw_summary: Optional[str] = None,
    ) -> NormalizedIntel:
        """根据 provider 返回的 verdict dict 构造归一化结果（judgments 优先）.

        Args:
            ioc_type: IOC 类型。
            ioc_value: 指标值。
            provider: provider 名称。
            verdict: provider 返回的该指标详情 dict。
            raw_summary: 可选原始摘要；缺省由 verdict 自动拼接。

        Returns:
            NormalizedIntel。
        """
        judgments = verdict.get("judgments") or []
        if not isinstance(judgments, list):
            judgments = [str(judgments)]
        risk_score = int(verdict.get("risk_score", 0) or 0)
        tags = verdict.get("tags") or []
        confidence = int(verdict.get("confidence", 0) or 0)
        company = verdict.get("company") or []
        attck = verdict.get("attck") or []
        threat_level = NormalizedIntel._level_from_judgments(judgments, risk_score)

        if raw_summary is None:
            raw_summary = (
                f"risk_score={risk_score}; judgments={json.dumps(judgments, ensure_ascii=False)}; "
                f"tags={json.dumps(tags, ensure_ascii=False)}"
            )

        return NormalizedIntel(
            ioc_type=ioc_type,
            ioc_value=ioc_value,
            provider=provider,
            risk_score=risk_score,
            judgments=judgments,
            tags=tags if isinstance(tags, list) else [tags],
            confidence=confidence,
            company=company if isinstance(company, list) else [company],
            attck=attck if isinstance(attck, list) else [attck],
            threat_level=threat_level,
            raw_summary=raw_summary,
        )


class ThreatBookProvider(BaseThreatIntelProvider):
    """微步在线（ThreatBook）威胁情报 provider 实现."""

    # 类型 → 端点后缀（拼接在 base_url 之后）。
    # 官方文档确认（路径错误会返回 response_code=-2 Invalid Api method）：
    #   - IP 情报:   /v3/scene/ip_reputation
    #   - 域名情报:  /v3/domain/query
    # 两者均支持 GET/POST，参数均为 apikey + resource。
    ENDPOINT_MAP = {
        "ip": "/v3/scene/ip_reputation",
        "domain": "/v3/domain/query",
    }

    # 威胁类型分类（用于内部判定 high / medium / clean）
    _MALICIOUS_TYPES = {
        "C2", "Malware", "Phishing", "Botnet", "Exploit", "Trojan",
        "Ransomware", "Ransom", "Backdoor", "Miner", "Proxy", "TOR", "VPN",
        "Scanner", "Zombie", "Brute Force", "Spam", "Worm", "Rootkit",
    }
    _SUSPICIOUS_TYPES = {
        "Suspicious", "Dynamic IP", "DDNS", "Fast Flux", "Parking",
    }
    _WHITELIST_TYPES = {"Whitelist", "Info", "ICP", "CDN"}

    # severity / confidence_level → risk_score / confidence 映射
    _SEVERITY_RISK = {"critical": 100, "high": 90, "medium": 70, "low": 40, "info": 20}
    _CONF_RISK = {"high": 90, "medium": 70, "low": 40}
    _CONF_INT = {"high": 100, "medium": 70, "low": 40}

    def query(self, ioc_type: str, ioc_value: str) -> NormalizedIntel:
        """查询微步情报.

        端点（官方文档确认）：
          - IP      → ``GET {base_url}/v3/scene/ip_reputation``
          - 域名    → ``GET {base_url}/v3/domain/query``

        请求: query params ``apikey``（由 api_key_ref 展开）与 ``resource=<indicator>``。
        返回结构: ``{ "response_code": 0, "data": { "<indicator>": {...} } }``。

        Raises:
            UnsupportedIocTypeError: provider 不支持该 ioc_type。
            ThreatIntelQueryError: response_code != 0 或网络异常。
        """
        endpoint = self.ENDPOINT_MAP.get(ioc_type) or self.endpoints.get(ioc_type)
        if not endpoint:
            raise UnsupportedIocTypeError(
                f"provider '{self.name}' 不支持 ioc_type='{ioc_type}'"
            )

        url = f"{self.base_url}{endpoint}"
        api_key = self.expand_api_key()
        if not api_key:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 的 api_key 未配置或环境变量未设置"
            )

        try:
            with httpx.Client(
                timeout=httpx.Timeout(30.0), follow_redirects=True
            ) as client:
                resp = client.get(
                    url,
                    params={"apikey": api_key, "resource": ioc_value},
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

        response_code = payload.get("response_code", -1)
        if response_code != 0:
            raise ThreatIntelQueryError(
                f"provider '{self.name}' 业务错误 response_code={response_code}: "
                f"{payload.get('verbose_msg') or payload.get('message') or ''}"
            )

        data = payload.get("data") or {}
        # 优先按指标值取，其次取 data 中唯一值（兼容边界返回）
        verdict = data.get(ioc_value)
        if verdict is None and isinstance(data, dict) and len(data) == 1:
            verdict = next(iter(data.values()))
        if not isinstance(verdict, dict):
            verdict = {}

        return self._normalize(ioc_type, ioc_value, verdict)

    @staticmethod
    def _dedup(seq: List[Any]) -> List[Any]:
        """保序去重."""
        seen: List[Any] = []
        for item in seq:
            if item not in seen:
                seen.append(item)
        return seen

    def _normalize(
        self, ioc_type: str, ioc_value: str, data: Dict[str, Any]
    ) -> NormalizedIntel:
        """将微步真实返回结构归一化为 NormalizedIntel。

        保持 ``NormalizedIntel`` 字段契约不变，仅修正填充逻辑以适配微步真实结构
        （微步返回**没有** ``risk_score`` / ``attck`` / ``company`` 字段）。

        Args:
            ioc_type: ip / domain。
            ioc_value: 指标值。
            data: ``payload["data"][ioc_value]`` 的该指标详情 dict。

        Returns:
            NormalizedIntel。
        """
        if ioc_type == "ip":
            return self._normalize_ip(ioc_value, data)
        return self._normalize_domain(ioc_value, data)

    def _normalize_ip(
        self, ioc_value: str, data: Dict[str, Any]
    ) -> NormalizedIntel:
        """IP 情报归一化（/v3/scene/ip_reputation）。"""
        is_malicious = data.get("is_malicious")
        severity = data.get("severity")  # critical/high/medium/low/info
        confidence_level = data.get("confidence_level")
        tb_judgments = data.get("judgments") or []
        if not isinstance(tb_judgments, list):
            tb_judgments = [str(tb_judgments)]

        tags = self._dedup(
            list(tb_judgments)
            + [
                t
                for cls in (data.get("tags_classes") or [])
                for t in (cls.get("tags") or [])
            ]
        )

        # 派生 threat_level（用于引擎回灌）
        if severity in ("critical", "high") or is_malicious is True:
            threat_level = "high"
        elif severity == "medium" or confidence_level == "medium":
            threat_level = "medium"
        elif is_malicious is False or severity in ("low", "info"):
            threat_level = "low"
        else:
            threat_level = "low"

        # clean 特判：仅含白名单类且非恶意 → 不回灌
        is_only_whitelist = bool(tb_judgments) and all(
            j in self._WHITELIST_TYPES for j in tb_judgments
        )
        if is_only_whitelist and is_malicious is not True:
            threat_level = None
            judgments = ["clean"]
        elif threat_level == "high":
            judgments = ["malicious"]
        elif threat_level == "medium":
            judgments = ["suspicious"]
        else:
            judgments = ["clean"]

        # 派生 risk_score / confidence（缺省 0）
        if severity in self._SEVERITY_RISK:
            risk_score = self._SEVERITY_RISK[severity]
        elif confidence_level in self._CONF_RISK:
            risk_score = self._CONF_RISK[confidence_level]
        else:
            risk_score = 0
        confidence = self._CONF_INT.get(confidence_level, 0)

        return self._build_intel(
            ioc_type="ip",
            ioc_value=ioc_value,
            risk_score=risk_score,
            judgments=judgments,
            tags=tags,
            confidence=confidence,
            threat_level=threat_level,
        )

    def _normalize_domain(
        self, ioc_value: str, data: Dict[str, Any]
    ) -> NormalizedIntel:
        """域名情报归一化（/v3/domain/query）。"""
        tb_judgments = data.get("judgments") or []
        if not isinstance(tb_judgments, list):
            tb_judgments = [str(tb_judgments)]

        sample_levels = [
            s.get("threat_level")
            for s in (data.get("samples") or [])
            if isinstance(s, dict) and s.get("threat_level")
        ]

        tags = self._dedup(
            list(tb_judgments)
            + [
                t
                for cls in (data.get("tags_classes") or [])
                for t in (cls.get("tags") or [])
            ]
        )

        # 派生 threat_level（用于引擎回灌）
        if (
            any(j in self._MALICIOUS_TYPES for j in tb_judgments)
            or "malicious" in sample_levels
        ):
            threat_level = "high"
        elif (
            any(j in self._SUSPICIOUS_TYPES for j in tb_judgments)
            or "suspicious" in sample_levels
        ):
            threat_level = "medium"
        elif (
            bool(tb_judgments)
            and all(j in self._WHITELIST_TYPES for j in tb_judgments)
            and not any(j in self._MALICIOUS_TYPES for j in tb_judgments)
        ):
            threat_level = None  # 全白名单 → 不回灌
        else:
            threat_level = "low"

        if threat_level is None:
            judgments = ["clean"]
        elif threat_level == "high":
            judgments = ["malicious"]
        elif threat_level == "medium":
            judgments = ["suspicious"]
        else:
            judgments = ["clean"]

        # 派生 risk_score：high→90, medium→70, low→40, clean→10
        risk_map = {"high": 90, "medium": 70, "low": 40, None: 10}
        risk_score = risk_map.get(threat_level, 40)

        # confidence 取自 intelligences.threatbook_lab[0].confidence
        intelligences = data.get("intelligences") or {}
        lab_list = intelligences.get("threatbook_lab") or [{}]
        first = lab_list[0] if isinstance(lab_list, list) and lab_list else {}
        try:
            confidence = int(first.get("confidence", 0) or 0)
        except (ValueError, TypeError):
            confidence = 0

        return self._build_intel(
            ioc_type="domain",
            ioc_value=ioc_value,
            risk_score=risk_score,
            judgments=judgments,
            tags=tags,
            confidence=confidence,
            threat_level=threat_level,
        )

    def _build_intel(
        self,
        ioc_type: str,
        ioc_value: str,
        risk_score: int,
        judgments: List[str],
        tags: List[str],
        confidence: int,
        threat_level: Optional[str],
    ) -> NormalizedIntel:
        """统一构造 NormalizedIntel（attck=[]、company=None）。"""
        raw_summary = (
            f"threat_level={threat_level}; "
            f"judgments={json.dumps(judgments, ensure_ascii=False)}; "
            f"tags={json.dumps(tags, ensure_ascii=False)}; "
            f"risk_score={risk_score}"
        )
        return NormalizedIntel(
            ioc_type=ioc_type,
            ioc_value=ioc_value,
            provider=self.name,
            risk_score=int(risk_score or 0),
            judgments=judgments,
            tags=tags,
            confidence=int(confidence or 0),
            company=None,
            attck=[],
            threat_level=threat_level,
            raw_summary=raw_summary,
        )


# ── Provider 工厂 ───────────────────────────────────────────────────
_PROVIDER_REGISTRY = {
    "threatbook": ThreatBookProvider,
}


def create_provider(config: Dict[str, Any]) -> BaseThreatIntelProvider:
    """根据配置 dict 构造对应的 provider 实例.

    Raises:
        ThreatIntelQueryError: 未知 provider type。
    """
    ptype = (config.get("type") or "").lower()
    cls = _PROVIDER_REGISTRY.get(ptype)
    if cls is None:
        raise ThreatIntelQueryError(f"未知 provider type: '{ptype}'")
    return cls(config)


# ── 服务层 ──────────────────────────────────────────────────────────
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(a: str, b: str) -> str:
    """取两个严重级别中较高的一个."""
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


# ── 任务④ 多源聚合与分级缓存辅助 ────────────────────────────────
_THREAT_LEVEL_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _aggregate_normalized(
    ioc_type: str,
    ioc_value: str,
    per_source: List[NormalizedIntel],
    provider_names: List[str],
) -> NormalizedIntel:
    """将多源 NormalizedIntel 聚合为单条结果（任务④ 共识判定）.

    - 共识：≥2 源判黑（judgments 含 malicious）→ ``multi_source``；否则 ``single_source``。
    - confidence：取各源最大值（决策⑥）。
    - risk_score / threat_level：取各源最高值。

    Args:
        ioc_type / ioc_value: IOC 标识。
        per_source: 各源返回的归一化结果（非空）。
        provider_names: 参与聚合的 provider 名称列表（用于 provider 聚合 key）。

    Returns:
        聚合后的 NormalizedIntel（provider 为排序后的聚合 key）。
    """
    malicious_count = sum(
        1 for p in per_source if "malicious" in {str(j).lower() for j in (p.judgments or [])}
    )
    consensus = "multi_source" if malicious_count >= 2 else "single_source"

    risk_score = max((int(p.risk_score or 0) for p in per_source), default=0)
    confidence = max((int(p.confidence or 0) for p in per_source), default=0)
    threat_level = None
    for p in per_source:
        if p.threat_level:
            threat_level = _max_severity(threat_level or "low", p.threat_level)

    # judgments / tags 取并集（去重，保序）
    judgments: List[str] = []
    tags: List[str] = []
    for p in per_source:
        for j in (p.judgments or []):
            if j not in judgments:
                judgments.append(j)
        for t in (p.tags or []):
            if t not in tags:
                tags.append(t)
    if not judgments:
        judgments = ["unknown"]

    provider_key = "+".join(sorted(provider_names))
    raw_summary = (
        f"consensus={consensus}; sources={len(per_source)}; "
        f"malicious_sources={malicious_count}; "
        f"risk_score={risk_score}; confidence={confidence}"
    )
    return NormalizedIntel(
        ioc_type=ioc_type,
        ioc_value=ioc_value,
        provider=provider_key,
        risk_score=risk_score,
        judgments=judgments,
        tags=tags,
        confidence=confidence,
        company=[],
        attck=[],
        threat_level=threat_level,
        raw_summary=raw_summary,
        providers=list(provider_names),
        consensus=consensus,
    )


class EnrichmentService:
    """外联威胁情报查询服务（单例共享当日配额）."""

    def __init__(self) -> None:
        self._settings = EnrichSettings.load()
        self._daily_quota = int(self._settings.get("daily_quota", settings.DEFAULT_DAILY_QUOTA))
        self._rate_limit_qps = int(self._settings.get("rate_limit_qps", settings.DEFAULT_RATE_LIMIT_QPS))
        self._dedup_ttl = settings.THREAT_INTEL_DEDUP_TTL

        # 当日配额状态
        self._quota_lock = threading.Lock()
        self._quota_used = 0
        self._quota_date = self._today()

        # 内存去重缓存: (ioc_value_lower, provider, ioc_type) -> (timestamp, NormalizedIntel)
        self._dedup_lock = threading.Lock()
        self._dedup: Dict[tuple, tuple] = {}

        # 单 provider 串行 + 限流
        self._provider_locks: Dict[str, threading.Lock] = {}
        self._provider_last_call: Dict[str, float] = {}
        self._throttle_lock = threading.Lock()

    # ── 单例 ────────────────────────────────────────────────────────
    _instance: Optional["EnrichmentService"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "EnrichmentService":
        """获取共享单例（保证 scheduler 与手动 API 共用当日配额）."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 工具 ────────────────────────────────────────────────────────
    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    # ── provider 选择 ───────────────────────────────────────────────
    def get_provider(self, name: Optional[str] = None) -> Optional[BaseThreatIntelProvider]:
        """选择 provider.

        - 指定 name：按名称查找已启用 provider。
        - 未指定：返回首个 enabled 的 provider。
        """
        providers = ThreatIntelProviderConfig.load()
        enabled = [p for p in providers if p.get("enabled", True)]
        if not enabled:
            return None
        if name:
            for p in enabled:
                if p.get("name") == name:
                    return create_provider(p)
            # 指定名称但找不到 → 返回 None
            return None
        # 默认首个
        return create_provider(enabled[0])

    # ── 配额 ────────────────────────────────────────────────────────
    def _reset_quota_if_new_day(self) -> None:
        today = self._today()
        if today != self._quota_date:
            self._quota_used = 0
            self._quota_date = today

    def remaining_quota(self) -> int:
        """返回当日剩余配额."""
        with self._quota_lock:
            self._reset_quota_if_new_day()
            return max(0, self._daily_quota - self._quota_used)

    def try_acquire_quota(self) -> bool:
        """原子地尝试占用一次配额.

        Returns:
            True 表示成功占用（已递增计数）；False 表示配额耗尽。
        """
        with self._quota_lock:
            self._reset_quota_if_new_day()
            if self._quota_used >= self._daily_quota:
                return False
            self._quota_used += 1
            return True

    # ── 限流（单 provider 串行）─────────────────────────────────────
    def _throttle(self, provider_name: str) -> None:
        """单 provider 串行 + 按 rate_limit_qps 限流."""
        with self._throttle_lock:
            lock = self._provider_locks.get(provider_name)
            if lock is None:
                lock = threading.Lock()
                self._provider_locks[provider_name] = lock
        with lock:
            min_interval = 1.0 / max(1, self._rate_limit_qps)
            last = self._provider_last_call.get(provider_name, 0.0)
            elapsed = time.time() - last
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._provider_last_call[provider_name] = time.time()

    # ── 内存去重 ────────────────────────────────────────────────────
    def _dedup_key(self, ioc_value: str, provider: str, ioc_type: str) -> tuple:
        return (str(ioc_value).lower(), provider, ioc_type)

    def get_cached(
        self, ioc_value: str, provider: str, ioc_type: str, ttl: Optional[int] = None
    ) -> Optional[NormalizedIntel]:
        """获取内存去重缓存；若命中 TTL 内则返回，否则 None.

        Args:
            ttl: 缓存有效期（秒）；缺省使用 ``_dedup_ttl``。多源聚合场景按分级传入。
        """
        key = self._dedup_key(ioc_value, provider, ioc_type)
        if ttl is None:
            ttl = self._dedup_ttl
        with self._dedup_lock:
            entry = self._dedup.get(key)
            if entry is None:
                return None
            ts, intel = entry
            if time.time() - ts > ttl:
                self._dedup.pop(key, None)
                return None
            return intel

    def set_cached(
        self,
        ioc_value: str,
        provider: str,
        ioc_type: str,
        intel: NormalizedIntel,
        ttl: Optional[int] = None,
    ) -> None:
        """写入内存去重缓存.

        Args:
            ttl: 缓存有效期（秒）；缺省使用 ``_dedup_ttl``。多源聚合场景按分级传入。
        """
        key = self._dedup_key(ioc_value, provider, ioc_type)
        if ttl is None:
            ttl = self._dedup_ttl
        with self._dedup_lock:
            self._dedup[key] = (time.time(), intel)

    def clear_dedup(self) -> None:
        """清空内存去重缓存（测试/调试用）."""
        with self._dedup_lock:
            self._dedup.clear()

    # ── 分级缓存 TTL（任务④ 决策⑦）───────────────────────────────
    def _graded_recheck_days(
        self, threat_level: Optional[str], judgments: List[str], recheck_days: int
    ) -> int:
        """按判定分级决定有效重新检查间隔（天）.

        - 恶意（high）→ ``cache_ttl_malicious_hours`` 换算为天（优先）。
        - 干净（low / 仅 clean）→ ``cache_ttl_clean_days``。
        - 未知 / 可疑 → 回退 ``recheck_days``。
        """
        if threat_level == "high":
            return max(1, settings.DEFAULT_CACHE_TTL_MALICIOUS_HOURS // 24)
        jset = {str(j).lower() for j in (judgments or [])}
        if threat_level in (None, "low") and ("malicious" not in jset):
            return int(self._settings.get(
                "cache_ttl_clean_days", settings.DEFAULT_CACHE_TTL_CLEAN_DAYS
            ))
        # 可疑 / 未知 → recheck_days 兜底（决策⑦）
        return int(recheck_days)

    def _graded_ttl_seconds(self, intel: NormalizedIntel) -> int:
        """按判定分级返回内存缓存有效期（秒）."""
        if intel.threat_level == "high":
            return settings.DEFAULT_CACHE_TTL_MALICIOUS_HOURS * 3600
        if intel.threat_level in (None, "low"):
            return settings.DEFAULT_CACHE_TTL_CLEAN_DAYS * 86400
        return settings.DEFAULT_CACHE_TTL_UNKNOWN_DAYS * 86400

    @staticmethod
    def _record_age_days(record: Dict[str, Any]) -> float:
        """返回记录距离当前的天数（解析失败视为极旧）."""
        queried = record.get("queried_at")
        if not queried:
            return 9999.0
        try:
            dt = datetime.strptime(queried, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return 9999.0
        return (datetime.now() - dt).total_seconds() / 86400.0

    def _is_stale(self, record: Dict[str, Any], multi: bool) -> bool:
        """判断某历史记录是否已超出有效缓存期（需重查）.

        - 单源（legacy）：保持「查过即缓存」语义，永不视为过期。
        - 多源：按分级 TTL 判定。
        """
        if not multi:
            return False
        recheck_days = int(self._settings.get("recheck_days", settings.DEFAULT_RECHECK_DAYS))
        graded = self._graded_recheck_days(
            record.get("threat_level"), record.get("judgments") or [], recheck_days
        )
        return self._record_age_days(record) > graded

    def _get_pending_iocs_graded(
        self, recheck_days: int, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """多源场景：按分级 TTL 逐条判定待查 ioc（任务④ 决策⑦）.

        与单源 ``get_pending_iocs`` 不同，多源按「各源聚合后的判定分级」决定缓存期，
        优先于统一的 recheck_days。
        """
        candidates = ThreatIntel.get_all_enrichable_iocs(limit=None)
        result: List[Dict[str, Any]] = []
        for ioc in candidates:
            latest = ThreatIntel.get_latest_by_ioc_id(ioc["id"])
            if latest is None:
                result.append(ioc)
                continue
            graded = self._graded_recheck_days(
                latest.get("threat_level"),
                latest.get("judgments") or [],
                recheck_days,
            )
            if self._record_age_days(latest) > graded:
                result.append(ioc)
        if limit:
            result = result[: int(limit)]
        return result

    # ── 核心：单条 enrich ───────────────────────────────────────────
    def enrich_ioc(
        self,
        ioc_id: Optional[int],
        ioc_type: str,
        ioc_value: str,
        provider_name: Optional[str] = None,
        force_refresh: bool = False,
    ) -> dict:
        """查询并落库单条 IOC 的威胁情报（任务④ 支持多源聚合）.

        行为:
          - ``provider_name`` 指定 → 仅查该 provider（单源 legacy 语义）。
          - 未指定且存在 ≥2 个已启用 provider → 逐源串行查询并聚合（共识判定）。
          - 未指定且仅 0~1 个已启用 provider → 单源语义（兼容既有测试与配置）。

        Args:
            ioc_id: 关联的 iocs 主键（可为 None）。
            ioc_type: IOC 类型（仅支持 ip/domain）。
            ioc_value: 指标值。
            provider_name: 指定 provider 名称（可选）。
            force_refresh: 跳过内存去重与分级缓存，强制重新查询（决策⑦）。

        Returns:
            落库的 ``threat_intel`` 记录 dict（或命中缓存时返回最新已存记录）。

        Raises:
            UnsupportedIocTypeError: 非 ip/domain。
            QuotaExceededError: 当日配额耗尽。
            ThreatIntelQueryError: 无可用 provider / 所有源查询失败。
        """
        # 1) 类型校验
        if ioc_type not in settings.ENRICH_SUPPORTED_TYPES:
            raise UnsupportedIocTypeError(
                f"不支持的 IOC 类型: '{ioc_type}'，仅支持 {settings.ENRICH_SUPPORTED_TYPES}"
            )

        # 2) 解析目标 provider（多源 / 单源）
        #    约定：单源路径复用 get_provider（兼容既有测试对 get_provider 的 patch）；
        #          仅当存在 ≥2 个已启用 provider 且未指定 provider_name 时才走多源聚合。
        enabled_configs = [
            c for c in ThreatIntelProviderConfig.load() if c.get("enabled", True)
        ]
        if provider_name:
            # 指定 provider：沿用 get_provider 语义（可被测试 patch）
            provider = self.get_provider(provider_name)
            if provider is None:
                raise ThreatIntelQueryError(
                    f"未找到已启用的 provider: {provider_name}"
                )
            providers = [provider]
            provider_names = [provider.name]
            multi = False
            provider_key = provider.name
        elif len(enabled_configs) >= 2:
            # 多源：逐源实例化（不依赖 get_provider，避免单源 patch 干扰）
            providers = [create_provider(c) for c in enabled_configs]
            provider_names = [p.name for p in providers]
            multi = True
            provider_key = "+".join(sorted(provider_names))
        else:
            # 单源：复用 get_provider（兼容既有行为 / 测试 patch）
            provider = self.get_provider(None)
            if provider is None:
                raise ThreatIntelQueryError("无可用（已启用）的威胁情报 provider")
            providers = [provider]
            provider_names = [provider.name]
            multi = False
            provider_key = provider.name

        # 4) 缓存（内存去重 + 分级 DB 缓存）；force_refresh 跳过
        if not force_refresh:
            cached = self.get_cached(ioc_value, provider_key, ioc_type)
            if cached is not None:
                logger.debug("命中内存去重，跳过 API: %s/%s", ioc_value, provider_key)
                existing = ThreatIntel.get_latest_by_value(ioc_value, provider_key)
                if existing and not self._is_stale(existing, multi):
                    return existing
                return cached.to_dict()
            existing = ThreatIntel.get_latest_by_value(ioc_value, provider_key)
            if existing and not self._is_stale(existing, multi):
                return existing

        # 5) 逐源串行查询 + 限流 + 每源配额（多源 fallback）
        #    首个源前先占配额：配额耗尽直接抛 QuotaExceededError（与历史行为一致）；
        #    多源后续源再逐次占配额，中途耗尽则停止其余源（已查源仍聚合）。
        if not self.try_acquire_quota():
            logger.warning("当日配额已耗尽（%d），拒绝查询 %s", self._daily_quota, ioc_value)
            raise QuotaExceededError(
                f"当日查询配额已耗尽（{self._daily_quota}），请明日再试或在设置中调大 daily_quota"
            )
        per_source: List[NormalizedIntel] = []
        for idx, p in enumerate(providers):
            if idx > 0:
                if not self.try_acquire_quota():
                    logger.warning("当日配额已耗尽，停止多源查询 %s", ioc_value)
                    break
            self._throttle(p.name)
            try:
                intel = p.query(ioc_type, ioc_value)
                per_source.append(intel)
            except Exception as exc:  # noqa: BLE001 — 单源失败不阻断其它源
                logger.warning("provider %s 查询 %s 失败: %s", p.name, ioc_value, exc)
                continue

        if not per_source:
            raise ThreatIntelQueryError(f"所有 provider 查询 {ioc_value} 均失败")

        # 6) 聚合（多源 → 共识；单源 → 直出）
        if multi and len(per_source) >= 1:
            intel = _aggregate_normalized(ioc_type, ioc_value, per_source, provider_names)
        else:
            intel = per_source[0]
            intel.provider = provider_names[0]  # 单源使用真实 provider 名
            intel.consensus = "single_source"  # 单源共识（决策⑥）

        # 7) 落库（保留全历史不去重）
        record = ThreatIntel.create(
            **intel.to_threat_intel_kwargs(ioc_id=ioc_id)
        )

        # 8) 写入内存去重（分级 TTL）
        ttl = self._graded_ttl_seconds(intel) if multi else self._dedup_ttl
        self.set_cached(ioc_value, provider_key, ioc_type, intel, ttl=ttl)
        return record

    # ── 批量 enrich ─────────────────────────────────────────────────
    def enrich_batch(
        self,
        items: List[Dict[str, Any]],
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量 enrich.

        Args:
            items: 列表，每项 ``{ioc_id, ioc_type, ioc_value}``。
            provider_name: 指定 provider 名称（可选）。

        Returns:
            ``{total, enriched, skipped, failed, details}``。
            配额耗尽时，剩余项标记为 skipped（reason=quota），并停止本轮 API 调用。
        """
        total = len(items)
        enriched = 0
        skipped = 0
        failed = 0
        details: List[Dict[str, Any]] = []
        quota_hit = False

        for it in items:
            ioc_id = it.get("ioc_id")
            ioc_type = it.get("ioc_type")
            ioc_value = it.get("ioc_value")
            ident = {"ioc_id": ioc_id, "ioc_type": ioc_type, "ioc_value": ioc_value}

            if quota_hit:
                skipped += 1
                details.append({**ident, "status": "skipped", "reason": "quota_exceeded"})
                continue

            try:
                rec = self.enrich_ioc(ioc_id, ioc_type, ioc_value, provider_name)
                enriched += 1
                details.append({
                    **ident,
                    "status": "enriched",
                    "threat_level": rec.get("threat_level"),
                    "risk_score": rec.get("risk_score"),
                })
            except UnsupportedIocTypeError as exc:
                skipped += 1
                details.append({**ident, "status": "skipped", "reason": str(exc)})
            except QuotaExceededError as exc:
                quota_hit = True
                skipped += 1
                details.append({**ident, "status": "skipped", "reason": "quota_exceeded"})
            except Exception as exc:  # noqa: BLE001 — 单条失败不影响整体
                failed += 1
                details.append({**ident, "status": "failed", "reason": str(exc)})

        return {
            "total": total,
            "enriched": enriched,
            "skipped": skipped,
            "failed": failed,
            "details": details,
        }

    # ── 第三方 IOC 列表聚合（Phase 2 — 任务9）───────────────────

    def fetch_all_ioc_lists(self, limit: int = 20) -> list[dict]:
        """并行调用三个 provider 的 ``fetch_list()``，去重后汇聚返回.

        每个 provider 的 ``fetch_list()`` 在 API key 未配置或请求失败时返回 []，
        不会抛异常。

        Args:
            limit: 每个 provider 的最大返回条数。

        Returns:
            去重后的 IOC 列表（按 ioc_value 去重）。
        """
        import concurrent.futures

        all_results: list[dict] = []
        provider_names = ["virustotal", "abuseipdb", "alienvault_otx"]

        def _fetch_one(name: str) -> list[dict]:
            try:
                p = self.get_provider(name)
                if p is None:
                    logger.warning("fetch_all_ioc_lists: provider '%s' 不可用", name)
                    return []
                if not hasattr(p, "fetch_list"):
                    logger.warning(
                        "fetch_all_ioc_lists: provider '%s' 不支持 fetch_list", name
                    )
                    return []
                return p.fetch_list(limit=limit)
            except Exception as exc:
                logger.warning("fetch_all_ioc_lists: provider '%s' 失败: %s", name, exc)
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_fetch_one, name): name
                for name in provider_names
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as exc:
                    name = futures[future]
                    logger.warning(
                        "fetch_all_ioc_lists: provider '%s' 线程异常: %s", name, exc
                    )

        # 按 ioc_value 去重（保留首次出现）
        seen: set[str] = set()
        deduped: list[dict] = []
        for item in all_results:
            val = (item.get("ioc_value") or "").lower()
            if val and val not in seen:
                seen.add(val)
                deduped.append(item)

        logger.info(
            "fetch_all_ioc_lists: total=%d, deduped=%d",
            len(all_results), len(deduped),
        )
        return deduped

    # ── 调度扫描 ───────────────────────────────────────────────────
    def scan_pending_iocs(
        self,
        recheck_days: Optional[int] = None,
        provider_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """扫描并 enrich 所有到期/从未查询的 ioc.

        多源场景（≥2 已启用 provider 且未指定 provider_name）按「分级 TTL」判定待查；
        单源场景沿用既有 ``get_pending_iocs`` 的精确 (ioc_id, provider) 维度。

        Args:
            recheck_days: 重新检查间隔（天）；缺省取运行策略。
            provider_name: 指定 provider；缺省自动判断是否多源。
            limit: 本轮最多处理条数。

        Returns:
            ``enrich_batch`` 的结果 dict。
        """
        if recheck_days is None:
            recheck_days = int(self._settings.get("recheck_days", settings.DEFAULT_RECHECK_DAYS))

        enabled_configs = [
            c for c in ThreatIntelProviderConfig.load() if c.get("enabled", True)
        ]
        multi = provider_name is None and len(enabled_configs) >= 2

        if multi:
            pending = self._get_pending_iocs_graded(recheck_days, limit)
            items = [
                {"ioc_id": i["id"], "ioc_type": i["ioc_type"], "ioc_value": i["ioc_value"]}
                for i in pending
            ]
            logger.info("扫描到 %d 条待外联查询的 IOC（多源聚合模式）", len(items))
            # 不传 provider_name → enrich_ioc 自动走多源聚合
            return self.enrich_batch(items)
        else:
            provider = self.get_provider(provider_name)
            if provider is None:
                raise ThreatIntelQueryError("无可用（已启用）的威胁情报 provider")
            pname = provider.name
            pending = ThreatIntel.get_pending_iocs(recheck_days, pname, limit)
            items = [
                {"ioc_id": i["id"], "ioc_type": i["ioc_type"], "ioc_value": i["ioc_value"]}
                for i in pending
            ]
            logger.info("扫描到 %d 条待外联查询的 IOC（provider=%s）", len(items), pname)
            return self.enrich_batch(items, provider_name=pname)


# 对外便捷函数：获取共享单例
def get_enrichment_service() -> EnrichmentService:
    """返回共享的 EnrichmentService 单例（API 与 scheduler 共用当日配额）."""
    return EnrichmentService.instance()


# ── 注册多源 provider 子类（任务④）──────────────────────────────
# 在模块加载末尾导入 providers 包，触发 register_providers 将
# VirusTotal / AbuseIPDB / AlienVaultOTX 注册进 _PROVIDER_REGISTRY。
try:
    import app.services.providers  # noqa: F401  — 导入即注册
except Exception as _reg_err:  # noqa: BLE001
    logger.warning("注册多源 threat intel provider 失败: %s", _reg_err)
