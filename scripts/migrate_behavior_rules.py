"""迁移脚本：将行为分析引擎种子规则插入 rules 表（engine_type='behavior_engine'）。

幂等：
- 首次执行：插入 4 条种子规则
- 重复执行：按 name 去重检查，已存在则跳过

Phase 4 清理硬编码后，此脚本用于初始化新数据库。
"""
import json
import logging
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEED_FILE = SCRIPT_DIR.parent / "docs" / "seed_rules_behavior.json"


def migrate():
    from app.database import get_connection

    # 读取种子规则
    if not SEED_FILE.exists():
        logger.error("种子规则文件不存在: %s", SEED_FILE)
        return False

    with open(SEED_FILE, encoding="utf-8") as f:
        seed_rules = json.load(f)

    with get_connection() as conn:
        inserted = 0
        skipped = 0

        for rule in seed_rules:
            name = rule.get("name")
            if not name:
                continue

            # 检查是否已存在（按 name 去重）
            existing = conn.execute(
                "SELECT id FROM rules WHERE name=? AND engine_type='behavior_engine'",
                (name,),
            ).fetchone()

            if existing:
                logger.info("规则已存在，跳过: %s (id=%s)", name, existing["id"])
                skipped += 1
                continue

            # 插入种子规则
            now = __import__("datetime").datetime.now().isoformat()
            conn.execute(
                """INSERT INTO rules 
                (name, description, category, rule_type, condition, severity, enabled, label, source, engine_type, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    name,
                    rule.get("description", ""),
                    rule.get("category", ""),
                    rule.get("rule_type", "behavior"),
                    json.dumps(rule.get("condition", {})),
                    rule.get("severity", "medium"),
                    1 if rule.get("enabled", True) else 0,
                    rule.get("label", ""),
                    rule.get("source", "default"),
                    rule.get("engine_type", "behavior_engine"),
                    now,
                    now,
                ),
            )
            inserted += 1
            logger.info("插入规则: %s", name)

        conn.commit()

    logger.info("迁移完成: 插入 %d 条, 跳过 %d 条（已存在）", inserted, skipped)
    return True


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
