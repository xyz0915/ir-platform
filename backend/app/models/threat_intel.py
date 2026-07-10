"""威胁情报外联（Enrichment）数据模型与配置封装.

包含三部分:
  1. ``ThreatIntel``   — ``threat_intel`` 表 CRUD（静态方法，复用 ``get_connection``）。
  2. ``ThreatIntelProviderConfig`` — provider 连接配置 JSON 读写封装
     （路径 ``backend/scripts/threat_intel_providers.json``，apikey 以 ``$ENV_VAR`` 引用，不落明文）。
  3. ``EnrichSettings`` — 运行策略 JSON 读写封装
     （路径 ``backend/config/threat_intel_settings.json``）。

所有方法均为静态，与 ``Ioc`` 模型同一范式。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)

# 结构化字段（以 JSON 文本存储于 SQLite）
_JSON_FIELDS = ("judgments", "tags", "attck", "company")


class ThreatIntel:
    """威胁情报外联结果数据模型."""

    @staticmethod
    def _row_to_dict(row) -> dict:
        """将 sqlite3.Row 转为 dict，并把 JSON 字段反序列化."""
        result = dict(row)
        for field in _JSON_FIELDS:
            raw = result.get(field)
            if isinstance(raw, str) and raw:
                try:
                    result[field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    result[field] = []
            elif result.get(field) is None:
                result[field] = []
        # threat_level 可能为 None
        return result

    @staticmethod
    def create(
        ioc_id: Optional[int],
        ioc_type: str,
        ioc_value: str,
        provider: str,
        risk_score: int = 0,
        judgments: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        confidence: int = 0,
        attck: Optional[List[Any]] = None,
        company: Optional[List[Any]] = None,
        threat_level: Optional[str] = None,
        raw_summary: Optional[str] = None,
        queried_at: Optional[str] = None,
    ) -> dict:
        """创建一条威胁情报查询结果（保留全历史，不去重）.

        Args:
            ioc_id: 关联的 iocs 表主键（可为 None）。
            ioc_type: IOC 类型（ip/domain）。
            ioc_value: 指标值。
            provider: provider 名称（如 threatbook）。
            risk_score: 风险评分 0-100。
            judgments: 判定数组（malicious/suspicious/clean/unknown）。
            tags: 标签数组。
            confidence: 置信度。
            attck: ATT&CK 矩阵信息。
            company: 关联团伙/组织。
            threat_level: 派生冗余列（high/medium/low/None）。
            raw_summary: 原始摘要文本。
            queried_at: 查询时间（默认 datetime('now')）。

        Returns:
            插入后的记录 dict。
        """
        judgments = judgments or []
        tags = tags or []
        attck = attck or []
        company = company or []

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO threat_intel
                    (ioc_id, ioc_type, ioc_value, provider, risk_score,
                     judgments, tags, confidence, attck, company,
                     threat_level, queried_at, raw_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
                """,
                (
                    ioc_id,
                    ioc_type,
                    ioc_value,
                    provider,
                    int(risk_score or 0),
                    json.dumps(judgments, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False),
                    int(confidence or 0),
                    json.dumps(attck, ensure_ascii=False),
                    json.dumps(company, ensure_ascii=False),
                    threat_level,
                    queried_at,
                    raw_summary,
                ),
            )
            ti_id = cursor.lastrowid
        return ThreatIntel.get_by_id(ti_id)

    @staticmethod
    def get_by_id(ti_id: int) -> Optional[dict]:
        """根据主键获取一条威胁情报记录."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM threat_intel WHERE id = ?", (ti_id,)
            ).fetchone()
            if row:
                return ThreatIntel._row_to_dict(row)
            return None

    @staticmethod
    def list_by_ioc(ioc_id: int) -> List[dict]:
        """获取某 ioc 的全部威胁情报历史（按查询时间倒序）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM threat_intel WHERE ioc_id = ? ORDER BY queried_at DESC, id DESC",
                (ioc_id,),
            ).fetchall()
            return [ThreatIntel._row_to_dict(r) for r in rows]

    @staticmethod
    def list_by_value(ioc_value: str, provider: Optional[str] = None) -> List[dict]:
        """获取某指标值的全部威胁情报历史（可按 provider 过滤）."""
        with get_connection() as conn:
            if provider:
                rows = conn.execute(
                    "SELECT * FROM threat_intel WHERE ioc_value = ? AND provider = ? "
                    "ORDER BY queried_at DESC, id DESC",
                    (ioc_value, provider),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM threat_intel WHERE ioc_value = ? "
                    "ORDER BY queried_at DESC, id DESC",
                    (ioc_value,),
                ).fetchall()
            return [ThreatIntel._row_to_dict(r) for r in rows]

    @staticmethod
    def get_latest_by_value(ioc_value: str, provider: Optional[str] = None) -> Optional[dict]:
        """获取某指标值的最新一条威胁情报（用于回灌加载）."""
        results = ThreatIntel.list_by_value(ioc_value, provider=provider)
        return results[0] if results else None

    @staticmethod
    def get_latest_by_ioc_id(ioc_id: int, provider: Optional[str] = None) -> Optional[dict]:
        """获取某 ioc 的最新一条威胁情报（用于前端详情展示）."""
        results = ThreatIntel.list_by_ioc(ioc_id)
        if provider:
            for r in results:
                if r.get("provider") == provider:
                    return r
            return None
        return results[0] if results else None

    @staticmethod
    def get_pending_iocs(recheck_days: int, provider: str, limit: Optional[int] = None) -> List[dict]:
        """获取需要进行外联查询的 ioc 列表.

        筛选条件:
          - enabled = 1
          - ioc_type ∈ ('ip', 'domain')
          - 不存在该 (ioc_id, provider) 在 ``recheck_days`` 天内查询过的记录
            （即：从未查询 或 上次查询已超过 recheck_days 天）

        Args:
            recheck_days: 重新检查间隔（天）。
            provider: provider 名称，按 (ioc_id, provider) 维度去重判断。
            limit: 可选返回条数上限。

        Returns:
            待查询的 ioc dict 列表。
        """
        query = """
            SELECT i.* FROM iocs i
            WHERE i.enabled = 1
              AND i.ioc_type IN ('ip', 'domain')
              AND NOT EXISTS (
                  SELECT 1 FROM threat_intel t
                  WHERE t.ioc_id = i.id
                    AND t.provider = ?
                    AND julianday('now') - julianday(t.queried_at) <= ?
              )
            ORDER BY i.id ASC
        """
        params: List[Any] = [provider, int(recheck_days)]
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["enabled"] = bool(item.get("enabled"))
                results.append(item)
            return results


class ThreatIntelProviderConfig:
    """provider 连接配置 JSON 读写封装.

    文件路径: ``backend/scripts/threat_intel_providers.json``
    apikey 仅以 ``$ENV_VAR`` 占位引用，序列化对外接口时剔除该字段。
    """

    @staticmethod
    def _path() -> str:
        return str(settings.THREAT_INTEL_PROVIDERS_PATH)

    @staticmethod
    def load() -> List[Dict[str, Any]]:
        """读取全部 provider 配置（缺文件时返回空列表）."""
        import os

        path = ThreatIntelProviderConfig._path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                logger.warning("provider 配置文件根节点应为数组，已忽略")
                return []
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取 provider 配置失败: %s", exc)
            return []

    @staticmethod
    def get(name: str) -> Optional[Dict[str, Any]]:
        """按名称获取单个 provider 配置."""
        for p in ThreatIntelProviderConfig.load():
            if p.get("name") == name:
                return p
        return None

    @staticmethod
    def _validate(provider: Dict[str, Any]) -> Dict[str, Any]:
        """规整 provider 配置字段，补全默认值并剔除未知顶层键之外的风险."""
        name = (provider.get("name") or "").strip()
        if not name:
            raise ValueError("provider 缺少 name")
        ioc_type = (provider.get("type") or "threatbook").strip()
        base_url = (provider.get("base_url") or "").strip()
        if not base_url:
            raise ValueError(f"provider '{name}' 缺少 base_url")
        return {
            "name": name,
            "type": ioc_type,
            "base_url": base_url,
            "api_key_ref": provider.get("api_key_ref", ""),
            "enabled": bool(provider.get("enabled", True)),
            "rate_limit_qps": int(provider.get("rate_limit_qps", settings.DEFAULT_RATE_LIMIT_QPS)),
            "endpoints": provider.get("endpoints") or {},
        }

    @staticmethod
    def upsert(provider: Dict[str, Any]) -> Dict[str, Any]:
        """新增或更新一个 provider（按 name 唯一）.

        Args:
            provider: provider 配置 dict（可含 api_key_ref 占位）。

        Returns:
            已规整并落盘的 provider dict。
        """
        import os

        cleaned = ThreatIntelProviderConfig._validate(provider)
        name = cleaned["name"]

        current = ThreatIntelProviderConfig.load()
        replaced = False
        for idx, p in enumerate(current):
            if p.get("name") == name:
                current[idx] = cleaned
                replaced = True
                break
        if not replaced:
            current.append(cleaned)

        path = ThreatIntelProviderConfig._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        logger.info("provider '%s' 已%s", name, "更新" if replaced else "新增")
        return cleaned

    @staticmethod
    def delete(name: str) -> bool:
        """删除一个 provider（按 name）."""
        import os

        current = ThreatIntelProviderConfig.load()
        new_list = [p for p in current if p.get("name") != name]
        if len(new_list) == len(current):
            return False
        path = ThreatIntelProviderConfig._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(new_list, fh, ensure_ascii=False, indent=2)
        logger.info("provider '%s' 已删除", name)
        return True


class EnrichSettings:
    """运行策略 JSON 读写封装.

    文件路径: ``backend/config/threat_intel_settings.json``
    字段与 ``app.config.settings`` 的兜底默认值保持一致。
    """

    DEFAULTS: Dict[str, Any] = {
        "enable_enrichment_feedback": settings.DEFAULT_ENABLE_ENRICHMENT_FEEDBACK,
        "auto_enrichment": settings.AUTO_ENRICHMENT,
        "daily_quota": settings.DEFAULT_DAILY_QUOTA,
        "recheck_days": settings.DEFAULT_RECHECK_DAYS,
        "scheduler_interval": settings.DEFAULT_SCHEDULER_INTERVAL,
        "rate_limit_qps": settings.DEFAULT_RATE_LIMIT_QPS,
    }

    # 允许通过接口更新的字段白名单
    MUTABLE_KEYS = (
        "enable_enrichment_feedback",
        "auto_enrichment",
        "daily_quota",
        "recheck_days",
        "scheduler_interval",
        "rate_limit_qps",
    )

    @staticmethod
    def _path() -> str:
        return str(settings.THREAT_INTEL_SETTINGS_PATH)

    @staticmethod
    def load() -> Dict[str, Any]:
        """读取运行策略，与默认值合并（缺字段用默认填充）."""
        import os

        merged = dict(EnrichSettings.DEFAULTS)
        path = EnrichSettings._path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in EnrichSettings.MUTABLE_KEYS:
                            merged[k] = v
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("读取运行策略失败，回退默认值: %s", exc)
        return merged

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """获取单个策略值."""
        return EnrichSettings.load().get(key, default)

    @staticmethod
    def update(values: Dict[str, Any]) -> Dict[str, Any]:
        """更新运行策略（仅允许白名单字段）并落盘.

        Args:
            values: 待更新的字段字典。

        Returns:
            合并默认值后的完整策略 dict。
        """
        import os

        merged = EnrichSettings.load()
        for k, v in (values or {}).items():
            if k in EnrichSettings.MUTABLE_KEYS:
                merged[k] = v

        # 类型兜底
        try:
            merged["daily_quota"] = int(merged.get("daily_quota", settings.DEFAULT_DAILY_QUOTA))
        except (ValueError, TypeError):
            merged["daily_quota"] = settings.DEFAULT_DAILY_QUOTA
        try:
            merged["recheck_days"] = int(merged.get("recheck_days", settings.DEFAULT_RECHECK_DAYS))
        except (ValueError, TypeError):
            merged["recheck_days"] = settings.DEFAULT_RECHECK_DAYS
        try:
            merged["scheduler_interval"] = int(merged.get("scheduler_interval", settings.DEFAULT_SCHEDULER_INTERVAL))
        except (ValueError, TypeError):
            merged["scheduler_interval"] = settings.DEFAULT_SCHEDULER_INTERVAL
        try:
            merged["rate_limit_qps"] = int(merged.get("rate_limit_qps", settings.DEFAULT_RATE_LIMIT_QPS))
        except (ValueError, TypeError):
            merged["rate_limit_qps"] = settings.DEFAULT_RATE_LIMIT_QPS
        merged["enable_enrichment_feedback"] = bool(merged.get("enable_enrichment_feedback", True))
        merged["auto_enrichment"] = bool(merged.get("auto_enrichment", False))

        path = EnrichSettings._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        logger.info("运行策略已更新: %s", {k: merged[k] for k in EnrichSettings.MUTABLE_KEYS})
        return merged
