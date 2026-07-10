"""Agent 差分采集工具（任务③）.

提供 baseline 读写与「当前采集 vs baseline」的差异计算。
--save-baseline 落盘当前 raw_results；--diff 仅输出相对 baseline 的 added/changed。
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def save_baseline(raw_results: dict, path: str) -> None:
    """将当前采集结果（raw_results）作为 baseline 落盘.

    Args:
        raw_results: 各采集器结果字典 {collector_name: result}.
        path: 输出文件路径.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw_results, f, ensure_ascii=False, indent=2)
    logger.info("Baseline saved to: %s", p)


def load_baseline(path: str) -> Optional[dict]:
    """读取 baseline 文件，返回 raw_results 字典；失败返回 None.

    Args:
        path: baseline 文件路径.

    Returns:
        raw_results 字典，或 None（文件不存在/解析失败）.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("Baseline 文件不存在: %s", p)
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Baseline 文件格式非法（非对象）: %s", p)
            return None
        return data
    except Exception as exc:
        logger.warning("读取 baseline 失败: %s — %s", p, exc)
        return None


def _diff_lists(base: list, cur: list) -> dict:
    """比较两个列表，返回 added / removed（按成员相等判定）."""
    base_set = set(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in base)
    cur_set = set(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in cur)
    added = [json.loads(s) for s in (cur_set - base_set)]
    removed = [json.loads(s) for s in (base_set - cur_set)]
    return {"added": added, "removed": removed, "changed": len(added) + len(removed) > 0}


def _diff_dicts(base: dict, cur: dict) -> dict:
    """比较两个字典（浅比较），返回 added / removed / changed 字段."""
    base_keys = set(base.keys())
    cur_keys = set(cur.keys())
    added = {k: cur[k] for k in (cur_keys - base_keys)}
    removed = {k: base[k] for k in (base_keys - cur_keys)}
    changed = {
        k: {"old": base[k], "new": cur[k]}
        for k in (base_keys & cur_keys)
        if base[k] != cur[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def compute_diff(baseline: dict, current: dict) -> dict:
    """计算 current 相对 baseline 的差异.

    Args:
        baseline: baseline 的 raw_results 字典.
        current: 当前采集的 raw_results 字典.

    Returns:
        {collector_name: {"added":..., "removed":..., "changed":...}, ...}
        仅包含存在差异的采集器。
    """
    diff_result: dict = {}
    for name, cur_val in current.items():
        base_val = baseline.get(name)
        if base_val is None:
            # baseline 中无此项 → 全部视为新增
            entry = {"added": cur_val, "removed": [], "changed": True}
        elif isinstance(cur_val, list) and isinstance(base_val, list):
            entry = _diff_lists(base_val, cur_val)
        elif isinstance(cur_val, dict) and isinstance(base_val, dict):
            entry = _diff_dicts(base_val, cur_val)
        else:
            entry = {"added": [], "removed": [], "changed": cur_val != base_val}
        if entry.get("added") or entry.get("removed") or entry.get("changed"):
            diff_result[name] = entry
    return diff_result
