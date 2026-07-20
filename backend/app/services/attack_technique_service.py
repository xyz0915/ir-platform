"""MITRE ATT&CK 覆盖库查询服务（v1.3.0 支柱④）.

提供技术点查表能力：未知技术点统一返回「待确认」，禁止 AI 杜撰。
数据来自静态内置快照 ``app/data/mitre_attack_coverage.json``（Enterprise 2024-06）。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)


class AttackTechniqueService:
    """ATT&CK 技术点查表服务（无状态、只读）."""

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_coverage() -> dict:
        """加载静态 ATT&CK 覆盖库（带缓存）.

        Returns:
            完整的覆盖库 dict（含 _meta 与 techniques）。
        """
        path = Path(settings.BACKEND_DIR) / "app" / "data" / "mitre_attack_coverage.json"
        if not path.exists():
            logger.warning("MITRE ATT&CK 覆盖库不存在: %s", path)
            return {"techniques": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("MITRE ATT&CK 覆盖库格式异常")
                return {"techniques": {}}
            data.setdefault("techniques", {})
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("MITRE ATT&CK 覆盖库加载失败: %s", exc)
            return {"techniques": {}}

    @classmethod
    def get_technique(cls, technique_id: str) -> dict:
        """查询单个技术点.

        Args:
            technique_id: 技术点 ID（如 ``T1059.001``）。

        Returns:
            ``{"id", "name", "tactic", "tactic_id", "known": bool}``；
            未知时 ``name="待确认"``、``known=False``。
        """
        tid = (technique_id or "").strip().upper()
        techniques = cls._load_coverage().get("techniques", {})
        info = techniques.get(tid)
        if info:
            return {
                "id": tid,
                "name": info.get("name", tid),
                "tactic": info.get("tactic", ""),
                "tactic_id": info.get("tactic_id", ""),
                "known": True,
            }
        return {
            "id": tid,
            "name": "待确认",
            "tactic": "",
            "tactic_id": "",
            "known": False,
        }

    @classmethod
    def resolve(cls, technique_ids: list[str]) -> list[dict]:
        """批量查询技术点，保留输入顺序并去重.

        Args:
            technique_ids: 技术点 ID 列表（可能含未知/脏数据）。

        Returns:
            技术点信息列表（每个元素见 ``get_technique``）。
            非法/空值会被跳过，但空串仍对应一个「待确认」占位以便前端展示。
        """
        result: list[dict] = []
        seen: set[str] = set()
        for tid in technique_ids or []:
            if tid is None:
                continue
            key = str(tid).strip().upper()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(cls.get_technique(key))
        return result

    @classmethod
    def invalidate_cache(cls) -> None:
        """使覆盖库缓存失效（测试或热更新时使用）."""
        cls._load_coverage.cache_clear()

    @classmethod
    def get_coverage_stats(cls) -> dict:
        """计算 ATT&CK 覆盖率聚合统计（T-P1-3）.

        从 rules 表统计 mitre_attack 列（去重），与 ATT&CK 知识库做差集，
        同时从 security_events 统计每 technique 的命中行数。

        Returns:
            覆盖率聚合字典:
            - coverage_pct: 覆盖率百分比
            - total_techniques: ATT&CK 总技术数
            - covered_techniques: 已覆盖的技术 ID 列表
            - uncovered_techniques: 未覆盖的技术 ID 列表
            - hit_counts: {technique_id: count} 每 technique 命中行数
            - top_10_alerts: 命中 Top 10 [{technique_id, name, count}]
            - false_positive_rate: 误报率（估算）
            - suppression_ratio: 抑制比率（估算）
        """
        # 1) 获取 ATT&CK 知识库总技术数
        coverage = cls._load_coverage()
        all_techniques = set(coverage.get("techniques", {}).keys())
        total_techniques = len(all_techniques)

        # 2) 从 rules 表统计已覆盖的 mitre_attack
        covered_techniques = set()
        rule_count = 0
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT mitre_attack FROM rules WHERE enabled=1 AND mitre_attack IS NOT NULL AND mitre_attack != ''"
                ).fetchall()
                for row in rows:
                    val = str(row["mitre_attack"]).strip()
                    if val:
                        # 支持逗号分隔的多个 technique ID
                        for tid in val.split(","):
                            tid = tid.strip().upper()
                            if tid:
                                covered_techniques.add(tid)
                # 总规则数
                rule_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM rules"
                ).fetchone()["cnt"]
        except Exception as exc:
            logger.warning("获取规则覆盖率统计失败: %s", exc)

        # 3) 计算覆盖率
        covered_list = sorted(covered_techniques & all_techniques)
        uncovered_list = sorted(all_techniques - covered_techniques)
        covered_count = len(covered_list)
        coverage_pct = round(covered_count / total_techniques * 100, 1) if total_techniques > 0 else 0.0

        # 4) 从 security_events 统计每 technique 命中行数
        hit_counts: dict[str, int] = {}
        try:
            with get_connection() as conn:
                # 从 security_events 的 matched_rules JSON 中提取 mitre_attack
                # matched_rules 字段存 MatchedRule JSON 数组，含 mitre_attack 字段
                rows = conn.execute(
                    "SELECT matched_rules FROM security_events WHERE matched_rules IS NOT NULL AND matched_rules != '[]'"
                ).fetchall()
                for row in rows:
                    try:
                        matched = json.loads(row["matched_rules"])
                        if isinstance(matched, list):
                            for mr in matched:
                                if isinstance(mr, dict):
                                    ma = mr.get("mitre_attack", "") or ""
                                    if ma:
                                        for tid in str(ma).split(","):
                                            tid = tid.strip().upper()
                                            if tid:
                                                hit_counts[tid] = hit_counts.get(tid, 0) + 1
                    except (json.JSONDecodeError, TypeError):
                        pass
        except Exception as exc:
            logger.warning("获取 security_events 命中统计失败: %s", exc)

        # 5) Top 10 命中
        sorted_hits = sorted(hit_counts.items(), key=lambda x: x[1], reverse=True)
        top_10_alerts = []
        for tid, cnt in sorted_hits[:10]:
            tech = coverage.get("techniques", {}).get(tid, {})
            top_10_alerts.append({
                "technique_id": tid,
                "name": tech.get("name", "待确认"),
                "tactic": tech.get("tactic", ""),
                "count": cnt,
            })

        # 6) 估算误报率和抑制比率
        false_positive_rate = 0.0
        suppression_ratio = 0.0
        try:
            with get_connection() as conn:
                fp_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM false_positive_patterns"
                ).fetchone()["cnt"]
                fp_total_hits = conn.execute(
                    "SELECT COALESCE(SUM(hit_count), 0) as total FROM false_positive_patterns"
                ).fetchone()["total"]
                total_alerts = conn.execute(
                    "SELECT COUNT(*) as cnt FROM alerts"
                ).fetchone()["cnt"]
                if total_alerts > 0:
                    false_positive_rate = round(fp_total_hits / (total_alerts + fp_total_hits) * 100, 1)
                sup_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM rule_suppression"
                ).fetchone()["cnt"]
                if rule_count > 0:
                    suppression_ratio = round(sup_count / rule_count * 100, 1)
        except Exception:
            pass

        return {
            "coverage_pct": coverage_pct,
            "total_techniques": total_techniques,
            "covered_count": covered_count,
            "covered_techniques": covered_list,
            "uncovered_techniques": uncovered_list[:20],  # 前 20 个未覆盖
            "hit_counts": hit_counts,
            "top_10_alerts": top_10_alerts,
            "total_rules": rule_count,
            "false_positive_rate": false_positive_rate,
            "suppression_ratio": suppression_ratio,
        }
