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

    # 类型 → 端点后缀（拼接在 base_url 之后）
    ENDPOINT_MAP = {
        "ip": "/v3/scene/ip",
        "domain": "/v3/domain/adv",
    }

    def query(self, ioc_type: str, ioc_value: str) -> NormalizedIntel:
        """查询微步情报.

        端点:
          - IP      → ``POST {base_url}/v3/scene/ip``
          - 域名    → ``POST {base_url}/v3/domain/adv``

        请求: 查询参数 ``apikey``（由 api_key_ref 展开）；表单字段 ``resource=<indicator>``。
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
                resp = client.post(
                    url,
                    params={"apikey": api_key},
                    data={"resource": ioc_value},
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
        # 优先按指标值取，其次取 data 中唯一值
        verdict = data.get(ioc_value)
        if verdict is None and isinstance(data, dict) and len(data) == 1:
            verdict = next(iter(data.values()))
        if not isinstance(verdict, dict):
            verdict = {}

        return BaseThreatIntelProvider.build_normalized(
            ioc_type=ioc_type,
            ioc_value=ioc_value,
            provider=self.name,
            verdict=verdict,
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

    def get_cached(self, ioc_value: str, provider: str, ioc_type: str) -> Optional[NormalizedIntel]:
        """获取内存去重缓存；若命中 TTL 内则返回，否则 None."""
        key = self._dedup_key(ioc_value, provider, ioc_type)
        with self._dedup_lock:
            entry = self._dedup.get(key)
            if entry is None:
                return None
            ts, intel = entry
            if time.time() - ts > self._dedup_ttl:
                self._dedup.pop(key, None)
                return None
            return intel

    def set_cached(self, ioc_value: str, provider: str, ioc_type: str, intel: NormalizedIntel) -> None:
        """写入内存去重缓存."""
        key = self._dedup_key(ioc_value, provider, ioc_type)
        with self._dedup_lock:
            self._dedup[key] = (time.time(), intel)

    def clear_dedup(self) -> None:
        """清空内存去重缓存（测试/调试用）."""
        with self._dedup_lock:
            self._dedup.clear()

    # ── 核心：单条 enrich ───────────────────────────────────────────
    def enrich_ioc(
        self,
        ioc_id: Optional[int],
        ioc_type: str,
        ioc_value: str,
        provider_name: Optional[str] = None,
    ) -> dict:
        """查询并落库单条 IOC 的威胁情报.

        Args:
            ioc_id: 关联的 iocs 主键（可为 None）。
            ioc_type: IOC 类型（仅支持 ip/domain）。
            ioc_value: 指标值。
            provider_name: 指定 provider 名称（可选）。

        Returns:
            落库的 ``threat_intel`` 记录 dict（或命中内存去重时返回最新已存记录）。

        Raises:
            UnsupportedIocTypeError: 非 ip/domain。
            QuotaExceededError: 当日配额耗尽。
            ThreatIntelQueryError: 无可用 provider / 查询失败。
        """
        # 1) 类型校验
        if ioc_type not in settings.ENRICH_SUPPORTED_TYPES:
            raise UnsupportedIocTypeError(
                f"不支持的 IOC 类型: '{ioc_type}'，仅支持 {settings.ENRICH_SUPPORTED_TYPES}"
            )

        # 2) 选择 provider
        provider = self.get_provider(provider_name)
        if provider is None:
            raise ThreatIntelQueryError("无可用（已启用）的威胁情报 provider")
        pname = provider.name

        # 3) 内存去重（命中则不重复打 API、不重复落库）
        cached = self.get_cached(ioc_value, pname, ioc_type)
        if cached is not None:
            logger.debug("命中内存去重，跳过 API: %s/%s", ioc_value, pname)
            existing = ThreatIntel.get_latest_by_value(ioc_value, pname)
            if existing:
                return existing
            return cached.to_dict()

        # 4) 配额
        if not self.try_acquire_quota():
            logger.warning("当日配额已耗尽（%d），拒绝查询 %s", self._daily_quota, ioc_value)
            raise QuotaExceededError(
                f"当日查询配额已耗尽（{self._daily_quota}），请明日再试或在设置中调大 daily_quota"
            )

        # 5) 单 provider 串行 + 限流
        self._throttle(pname)

        # 6) 查询
        intel = provider.query(ioc_type, ioc_value)

        # 7) 落库（保留全历史不去重）
        record = ThreatIntel.create(**intel.to_threat_intel_kwargs(ioc_id=ioc_id))

        # 8) 写入内存去重
        self.set_cached(ioc_value, pname, ioc_type, intel)
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

    # ── 调度扫描 ───────────────────────────────────────────────────
    def scan_pending_iocs(
        self,
        recheck_days: Optional[int] = None,
        provider_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """扫描并 enrich 所有到期/从未查询的 ioc.

        Args:
            recheck_days: 重新检查间隔（天）；缺省取运行策略。
            provider_name: 指定 provider；缺省选首个 enabled。
            limit: 本轮最多处理条数。

        Returns:
            ``enrich_batch`` 的结果 dict。
        """
        if recheck_days is None:
            recheck_days = int(self._settings.get("recheck_days", settings.DEFAULT_RECHECK_DAYS))

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
