"""行为基线模型（P1-5）— behavior_baselines 表 CRUD.

**定位**：把规则里的"全局固定阈值"替换为"相对该主机/用户自身历史的偏离程度"。
同一把尺子量一台正常开发机和一台内网跳板机，必然两头不讨好。

**本阶段范围**：仅提供存储与读取接口，**不接入任何规则判定**。
理由见 ``docs/rule-audit/p1/01-design.md`` §2.7——基线需要历史数据积累周期，
样本不足时启用自适应比固定阈值更不可控。P2/P3 再接入计算任务与规则切换。

**与 agent_baselines 的区别**（二者互补）：

- ``agent_baselines``：整机差分快照（known_items 全量 JSON），做集合比对。
- ``behavior_baselines``：按 (scope, metric, window) 的统计量，做数值偏离判定。

典型用法::

    BehaviorBaseline.upsert(
        scope_type="host", scope_key="12",
        metric="connection_count", window="1h",
        sample_count=30, mean=42.0, stddev=8.5, p95=61.0, max_value=88.0,
    )
    bl = BehaviorBaseline.get("host", "12", "connection_count", "1h")
    if BehaviorBaseline.is_reliable(bl):
        threshold = BehaviorBaseline.suggest_threshold(bl, sigma=3.0)
    else:
        threshold = rule_condition["value"]        # 回落到固定阈值
"""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)

# 样本数低于该值时基线不可信 —— 规则侧必须回落到固定阈值。
# 取 7 的含义：至少覆盖一个完整自然周，避免"周末低谷"被当作常态。
MIN_SAMPLES = 7

VALID_SCOPE_TYPES = ("host", "user", "global")


class BehaviorBaseline:
    """行为基线模型（按 scope × metric × window 存储统计量）."""

    # ── 写入 ──────────────────────────────────────────────────────────

    @staticmethod
    def upsert(
        scope_type: str,
        scope_key: str,
        metric: str,
        window: str = "1d",
        sample_count: int = 0,
        mean: Optional[float] = None,
        stddev: Optional[float] = None,
        p95: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> dict:
        """插入或更新一条基线记录（按唯一键幂等）.

        Args:
            scope_type: 作用域类型，host / user / global.
            scope_key: 作用域键；host_id 或用户名，global 时约定为 ``*``.
            metric: 指标名，如 connection_count.
            window: 统计窗口，如 1h / 1d.
            sample_count: 样本数，低于 MIN_SAMPLES 时基线不可信.
            mean: 均值.
            stddev: 标准差.
            p95: 95 分位数.
            max_value: 最大值.

        Returns:
            写入后的记录字典.

        Raises:
            ValueError: scope_type 非法或 metric 为空.
        """
        if scope_type not in VALID_SCOPE_TYPES:
            raise ValueError(
                f"Invalid scope_type: {scope_type!r}, expected one of {VALID_SCOPE_TYPES}"
            )
        if not metric:
            raise ValueError("metric must not be empty")
        if scope_type == "global":
            scope_key = "*"
        if not scope_key:
            raise ValueError("scope_key must not be empty for non-global scope")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO behavior_baselines
                    (scope_type, scope_key, metric, window,
                     sample_count, mean, stddev, p95, max_value, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(scope_type, scope_key, metric, window)
                DO UPDATE SET
                    sample_count = excluded.sample_count,
                    mean         = excluded.mean,
                    stddev       = excluded.stddev,
                    p95          = excluded.p95,
                    max_value    = excluded.max_value,
                    updated_at   = datetime('now')
                """,
                (
                    scope_type,
                    str(scope_key),
                    metric,
                    window,
                    int(sample_count),
                    mean,
                    stddev,
                    p95,
                    max_value,
                ),
            )
        result = BehaviorBaseline.get(scope_type, scope_key, metric, window)
        return result or {}

    # ── 读取 ──────────────────────────────────────────────────────────

    @staticmethod
    def get(
        scope_type: str,
        scope_key: str,
        metric: str,
        window: str = "1d",
    ) -> Optional[dict]:
        """按唯一键获取一条基线记录，不存在返回 None."""
        if scope_type == "global":
            scope_key = "*"
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM behavior_baselines
                WHERE scope_type = ? AND scope_key = ? AND metric = ? AND window = ?
                """,
                (scope_type, str(scope_key), metric, window),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_scope(scope_type: str, scope_key: str) -> list[dict]:
        """列出某作用域下的全部基线（按 metric, window 排序）."""
        if scope_type == "global":
            scope_key = "*"
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM behavior_baselines
                WHERE scope_type = ? AND scope_key = ?
                ORDER BY metric, window
                """,
                (scope_type, str(scope_key)),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def list_by_metric(metric: str, window: Optional[str] = None) -> list[dict]:
        """列出某指标在各作用域下的基线（运维观测用）."""
        sql = "SELECT * FROM behavior_baselines WHERE metric = ?"
        params: list[Any] = [metric]
        if window:
            sql += " AND window = ?"
            params.append(window)
        sql += " ORDER BY scope_type, scope_key"
        with get_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    # ── 判定辅助 ──────────────────────────────────────────────────────

    @staticmethod
    def is_reliable(baseline: Optional[dict], min_samples: int = MIN_SAMPLES) -> bool:
        """判断基线是否可信.

        不可信的情形一律返回 False，调用方**必须**回落到规则的固定阈值：

        - 基线不存在；
        - 样本数不足 ``min_samples``；
        - 均值缺失（说明统计任务未真正跑过）。

        Args:
            baseline: ``get()`` 的返回值，允许为 None.
            min_samples: 可信所需的最小样本数.

        Returns:
            可信返回 True.
        """
        if not baseline:
            return False
        if int(baseline.get("sample_count") or 0) < min_samples:
            return False
        if baseline.get("mean") is None:
            return False
        return True

    @staticmethod
    def suggest_threshold(
        baseline: Optional[dict],
        sigma: float = 3.0,
        fallback: Optional[float] = None,
    ) -> Optional[float]:
        """由基线推导建议阈值 ``mean + sigma * stddev``.

        基线不可信时返回 ``fallback``（通常是规则里的固定 value），
        保证"没有基线就退回原行为"，不会因为缺数据而放宽或收紧判定。

        stddev 缺失或为 0 时退化为 ``max(mean, p95)``——
        零方差意味着样本高度一致，此时用观测上界比用均值更稳妥。

        Args:
            baseline: 基线记录.
            sigma: 标准差倍数.
            fallback: 基线不可信时的回落值.

        Returns:
            建议阈值；不可用时返回 fallback.
        """
        if not BehaviorBaseline.is_reliable(baseline):
            return fallback
        assert baseline is not None  # is_reliable 已保证
        mean = float(baseline.get("mean") or 0.0)
        stddev = baseline.get("stddev")
        if stddev is None or float(stddev) <= 0:
            candidates = [mean]
            if baseline.get("p95") is not None:
                candidates.append(float(baseline["p95"]))
            if baseline.get("max_value") is not None:
                candidates.append(float(baseline["max_value"]))
            return max(candidates)
        return mean + float(sigma) * float(stddev)

    # ── 维护 ──────────────────────────────────────────────────────────

    @staticmethod
    def delete(
        scope_type: str,
        scope_key: str,
        metric: str,
        window: str = "1d",
    ) -> int:
        """删除一条基线记录，返回受影响行数."""
        if scope_type == "global":
            scope_key = "*"
        with get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM behavior_baselines
                WHERE scope_type = ? AND scope_key = ? AND metric = ? AND window = ?
                """,
                (scope_type, str(scope_key), metric, window),
            )
            return cursor.rowcount

    @staticmethod
    def count() -> int:
        """基线总条数（可观测用）."""
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM behavior_baselines").fetchone()
            return int(row["c"]) if row else 0
