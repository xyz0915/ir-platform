"""规则→知识批量导入脚本（Phase 1 — 任务5）.

读取 rules/loader.py 的 ``load_default_rules()`` 获取全部规则（约 135 条），
按字段映射转换为知识条目，调用 ``POST /api/knowledge/import`` 批量导入。

用法:
    cd backend
    # 预览模式（不提交）
    venv/Scripts/python scripts/import_rules_to_knowledge.py --dry-run
    # 实际导入
    venv/Scripts/python scripts/import_rules_to_knowledge.py

字段映射:
    name        → title
    description → description
    category    → category
    severity    → severity
    _meta.mitre_attack → mitre_attack
    label       → pattern
    固定        → source = "rule_import"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# 确保 backend/ 在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"
IMPORT_URL = f"{API_BASE}/api/knowledge/import"
AUTH_URL = f"{API_BASE}/api/auth/login"

# 默认管理员凭据
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin123"


def login(username: str = DEFAULT_USER, password: str = DEFAULT_PASSWORD) -> str:
    """登录获取 JWT token."""
    with httpx.Client() as client:
        resp = client.post(AUTH_URL, json={"username": username, "password": password})
        resp.raise_for_status()
        body = resp.json()
        token = body.get("data", {}).get("token")
        if not token:
            raise RuntimeError(f"登录失败: {body}")
        return token


def load_rules() -> list[dict]:
    """调用 loader.load_default_rules() 获取全部规则."""
    from app.rules.loader import load_default_rules

    rules = load_default_rules()
    logger.info("Loaded %d rules from all rules/*.json files", len(rules))
    return rules


def map_rule_to_import_item(rule: dict) -> dict[str, Any]:
    """将单条规则映射为知识导入条目.

    字段映射：
        name→title, description→description, category→category,
        severity→severity, _meta.mitre_attack→mitre_attack,
        label→pattern, 固定 source="rule_import"
    """
    name = (rule.get("name") or "").strip()
    description = (rule.get("description") or "").strip()
    category = rule.get("category", "process")
    severity = rule.get("severity", "medium")

    # 提取 MITRE ATT&CK 信息
    mitre_attack = None
    meta = rule.get("_meta", {})
    if isinstance(meta, dict):
        mitre_attack = meta.get("mitre_attack")

    # 提取 pattern/label
    pattern = None
    condition = rule.get("condition", {})
    if isinstance(condition, dict):
        # 尝试从 condition 提取 label/pattern
        pattern = condition.get("label") or condition.get("pattern")

    return {
        "title": name,
        "description": description,
        "category": category,
        "severity": severity,
        "mitre_attack": mitre_attack,
        "pattern": pattern,
        "source": "rule_import",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="规则→知识批量导入脚本",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只打印映射结果，不提交到 API",
    )
    parser.add_argument(
        "--api-base",
        default=API_BASE,
        help=f"API 基础 URL（默认 {API_BASE}）",
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USER,
        help=f"管理员用户名（默认 {DEFAULT_USER}）",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"管理员密码（默认 {DEFAULT_PASSWORD}）",
    )
    args = parser.parse_args()

    # 加载规则
    rules = load_rules()
    if not rules:
        logger.error("未加载到任何规则，退出")
        sys.exit(1)

    # 映射
    items: list[dict[str, Any]] = []
    skipped_empty: int = 0
    for rule in rules:
        item = map_rule_to_import_item(rule)
        if not item["title"] or not item["description"]:
            skipped_empty += 1
            logger.debug("跳过空字段规则: %s", rule.get("name", "?"))
            continue
        items.append(item)

    logger.info(
        "映射完成: %d/%d 规则可导入（跳过 %d 条空字段）",
        len(items), len(rules), skipped_empty,
    )

    # 预览模式
    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN — 共 {len(items)} 条规则将被导入（预览前 10 条）")
        print(f"{'='*60}")
        for i, item in enumerate(items[:10]):
            print(f"\n  [{i+1}] {item['title']}")
            print(f"     category: {item['category']}")
            print(f"     severity: {item['severity']}")
            print(f"     mitre_attack: {item.get('mitre_attack') or 'N/A'}")
            print(f"     pattern: {item.get('pattern') or 'N/A'}")
            desc_preview = item["description"][:80]
            print(f"     description: {desc_preview}...")
        if len(items) > 10:
            print(f"\n  ... 还有 {len(items) - 10} 条")
        print(f"\n{'='*60}")
        print("未提交任何数据（--dry-run 模式）。")
        print("确认无误后运行: venv/Scripts/python scripts/import_rules_to_knowledge.py")
        return

    # 实际导入
    logger.info("登录中...")
    try:
        token = login(args.username, args.password)
        logger.info("登录成功")
    except Exception as exc:
        logger.error("登录失败: %s", exc)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    imported_total = 0
    skipped_total = 0
    auto_approved = 0

    # 分批导入（每批最多 50 条）
    batch_size = 50
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        payload = {"items": batch}
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
                resp = client.post(
                    IMPORT_URL.replace(args.api_base, args.api_base),
                    json=payload,
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.error(
                        "批量导入失败 (HTTP %d): %s",
                        resp.status_code, resp.text[:200],
                    )
                    continue
                body = resp.json()
                data = body.get("data", {})
                imported = data.get("imported", 0)
                skipped = data.get("skipped", 0)
                approved = data.get("auto_approved", 0)
                total += len(batch)
                imported_total += imported
                skipped_total += skipped
                auto_approved += approved
                logger.info(
                    "批次 %d-%d: imported=%d, skipped=%d, auto_approved=%d",
                    batch_start + 1,
                    min(batch_start + batch_size, len(items)),
                    imported, skipped, approved,
                )
        except Exception as exc:
            logger.error("批量导入失败: %s", exc)

    logger.info(
        "导入完成: total=%d, imported=%d, skipped=%d, auto_approved=%d",
        len(items), imported_total, skipped_total, auto_approved,
    )


if __name__ == "__main__":
    main()
