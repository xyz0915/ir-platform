"""默认规则加载器（T-P1-5/P1-6）.

聚合读取 backend/app/rules/ 目录下所有 *.json 规则文件，逐条校验 schema，
返回合法规则列表。导入/重置时仅按 name upsert source='default' 的行。

校验失败的条目仅记录告警并跳过，避免单条错误阻塞整库初始化。
"""

import json
import logging
from pathlib import Path
from typing import List

from app.schemas.analysis import (
    RULE_TYPE_ENUM,
    SEVERITY_ENUM,
    validate_condition,
)

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).resolve().parent


def load_default_rules() -> List[dict]:
    """聚合读取 rules 目录下所有 JSON 规则文件并校验.

    Returns:
        合法规则字典列表（按文件名字典序、文件内顺序）。
    """
    rules: List[dict] = []
    json_files = sorted(RULES_DIR.glob("*.json"))
    for jf in json_files:
        try:
            raw_text = jf.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载规则文件失败 %s: %s", jf.name, exc)
            continue
        if not isinstance(data, list):
            logger.warning("规则文件 %s 顶层不是数组，跳过", jf.name)
            continue
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                logger.warning("规则文件 %s 第 %d 条不是对象，跳过", jf.name, idx)
                continue
            name = item.get("name")
            if not name or not isinstance(name, str):
                logger.warning("规则文件 %s 第 %d 条缺少合法 name，跳过", jf.name, idx)
                continue
            rule_type = item.get("rule_type")
            if rule_type not in RULE_TYPE_ENUM:
                logger.warning(
                    "规则 %s 的 rule_type 非法: %s，跳过", name, rule_type
                )
                continue
            if item.get("severity") not in SEVERITY_ENUM:
                logger.warning(
                    "规则 %s 的 severity 非法: %s，跳过", name, item.get("severity")
                )
                continue
            condition = item.get("condition")
            if not isinstance(condition, dict):
                logger.warning("规则 %s 的 condition 非对象，跳过", name)
                continue
            # 行为模式白名单校验（拼错直接拒绝，避免静默 False 永不命中）
            try:
                validate_condition(rule_type, condition)
            except ValueError as exc:
                logger.warning("规则 %s 条件校验失败: %s，跳过", name, exc)
                continue
            rules.append(item)
    return rules
