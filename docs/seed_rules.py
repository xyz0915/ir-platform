#!/usr/bin/env python3
"""应急溯源规则种子脚本（幂等）— 需求 #2 落库交付物。

把 `docs/seed_rules.json` 中的 11 条规则写入 `rules` 表。
- 已存在同名（name 唯一键）则跳过（幂等，可重复运行）。
- 写库前用 `validate_condition` 做结构自检，非法规则直接报错不入库。
- 本批规则 source='default'：不修改 default_rules.json，
  因此 knowledge_retriever 的 rule_{i}_{name} RAG 索引契约不受影响；
  且 reset_default_rules() 不会删除它们（仅在 default_rules.json 中的规则才被 upsert）。

运行方式（在 backend/ 目录下）：
    python docs/seed_rules.py
    python docs/seed_rules.py --path docs/seed_rules.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 让脚本可在 backend/ 根目录直接运行，复用既有 app 包。
# 兼容两种目录布局：
#   - docs/ 位于 backend/ 之内（架构师原假设）
#   - docs/ 与 backend/ 平级（本仓库实际布局）
# 向上查找首个包含 app/ 子目录的目录作为 backend 根并加入 sys.path。
_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_backend(start: str) -> str:
    """向上查找包含 app/ 子目录的最近目录（作为 backend 根）.

    同时兼容两种布局：
      - backend/app 直接位于某个祖先目录（docs 在 backend 内时）
      - docs 与 backend 平级时，祖先目录下的 backend/app 才是目标
    """
    cur = start
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, "app")):
            return cur
        if os.path.isdir(os.path.join(cur, "backend", "app")):
            return os.path.join(cur, "backend")
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return start


_BACKEND = _find_backend(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.schemas.analysis import validate_condition  # 结构自检 (T-P1-7)
from app.models.rule import Rule  # Rule.create / get_by_id


def _rule_exists(name: str) -> bool:
    """按 name 唯一键判断规则是否已存在（幂等）。"""
    try:
        existing = Rule.list()  # SELECT * FROM rules
        return any(r.get("name") == name for r in existing)
    except Exception as exc:  # 缺表/未初始化时降级为「不存在」
        print(f"  [warn] 读取 rules 失败，视为不存在: {exc}")
        return False


def seed(path: str, dry_run: bool = False) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    created = skipped = failed = 0
    for r in rules:
        name = r.get("name", "")
        try:
            # 1) 结构自检（与 API 层一致）
            validate_condition(r["rule_type"], r["condition"])
        except Exception as exc:
            print(f"  [skip] {name}: 结构校验失败 -> {exc}")
            failed += 1
            continue

        if _rule_exists(name):
            print(f"  [skip] {name}: 已存在")
            skipped += 1
            continue

        if dry_run:
            print(f"  [dry ] {name}: 将通过校验，待写入")
            created += 1
            continue

        # 2) 写入 rules 表（Rule.create 将 condition 整体 json.dumps）
        Rule.create(
            name=name,
            category=r.get("category", ""),
            rule_type=r["rule_type"],
            condition=r["condition"],
            severity=r.get("severity", "medium"),
            description=r.get("description"),
            enabled=r.get("enabled", True),
            label=r.get("label"),
            source=r.get("source", "default"),
        )
        print(f"  [ok  ] {name}: 已写入 ({r['rule_type']}/{r.get('severity')})")
        created += 1

    return {"total": len(rules), "created": created, "skipped": skipped, "failed": failed}


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed traceability rules into rules table")
    ap.add_argument("--path", default=os.path.join(_HERE, "seed_rules.json"))
    ap.add_argument("--dry-run", action="store_true", help="只校验不写库")
    args = ap.parse_args()

    print(f"种子规则文件: {args.path}")
    result = seed(args.path, dry_run=args.dry_run)
    print(
        f"完成: total={result['total']} "
        f"created={result['created']} skipped={result['skipped']} failed={result['failed']}"
    )
    if result["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
