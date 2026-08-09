"""默认规则加载器（T-P1-5/T-P1-6；P2-3 可观测性增强）.

聚合读取 backend/app/rules/ 目录下所有 *.json 规则文件，逐条校验 schema，
返回合法规则列表。导入/重置时仅按 name upsert source='default' 的行。

校验失败的条目仅记录告警并跳过，避免单条错误阻塞整库初始化。

P2-3 增强
---------
原实现对每个跳过分支仅 ``logger.warning`` 后 ``continue``，返回值只有规则
列表，调用方无从得知"跳过了几条、为什么跳过"。一条规则因拼写错误被静默
丢弃可能数月无人发现。本次新增：

1. :func:`load_default_rules_with_report` —— 返回 ``(rules, LoadReport)``，
   报告含文件级与条目级的完整跳过明细。
2. :data:`DATA_FILES` —— 数据文件白名单。``revoked_ca.json`` 之类的纯数据
   文件本就不是规则数组，此前每次启动都产生一条"顶层不是数组"的假阳性
   warning，反而训练运维忽略此类告警、掩盖真正的规则丢失。白名单内的文件
   降级为 debug 且不计入跳过。
3. :func:`load_default_rules` 保持原签名与返回值不变（薄封装），既有调用方
   与测试零改动。
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from app.schemas.analysis import (
    RULE_TYPE_ENUM,
    SEVERITY_ENUM,
    validate_condition,
)

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).resolve().parent

# ── 数据文件白名单（P2-3）────────────────────────────────────────────
# 这些 JSON 位于 rules 目录但**不是**规则数组，而是被引擎行为模式引用的
# 数据源。它们被 glob 扫到属于预期，不应产生"顶层不是数组"告警。
#   - revoked_ca.json : 吊销/过期签名库，供 revoked_sig 行为模式使用
#   - c2_ports.json   : C2/代理端口单一事实来源（P2-1），供 _C2_PORTS 装载
DATA_FILES = frozenset({"revoked_ca.json", "c2_ports.json"})


@dataclass
class SkipRecord:
    """单条被跳过记录."""

    file: str
    index: int  # 条目在文件内的下标；文件级跳过时为 -1
    name: str  # 无法取得 name 时为 "<unknown>"
    reason: str

    def __str__(self) -> str:  # pragma: no cover - 仅用于日志可读性
        loc = self.file if self.index < 0 else f"{self.file}[{self.index}]"
        return f"{loc} ({self.name}): {self.reason}"


@dataclass
class LoadReport:
    """规则装载报告（P2-3 可观测性）."""

    total_files: int = 0  # 扫描到的 *.json 文件数
    rule_files: int = 0  # 判定为规则文件并成功解析的数量
    data_files: List[str] = field(default_factory=list)  # 命中白名单的数据文件
    total_entries: int = 0  # 规则文件内条目总数（含被跳过的）
    loaded: int = 0  # 成功装载数
    skipped: List[SkipRecord] = field(default_factory=list)
    orphans: List[str] = field(default_factory=list)  # 由调用方填充（DB 有 / JSON 无）

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def summary_line(self) -> str:
        """单行结构化摘要，便于 grep 与日志告警."""
        return (
            f"[RULE-LOAD] files={self.total_files}"
            f"(rule={self.rule_files},data={len(self.data_files)}) "
            f"entries={self.total_entries} loaded={self.loaded} "
            f"skipped={self.skipped_count} orphans={len(self.orphans)}"
        )

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "rule_files": self.rule_files,
            "data_files": list(self.data_files),
            "total_entries": self.total_entries,
            "loaded": self.loaded,
            "skipped": self.skipped_count,
            "skipped_detail": [
                {
                    "file": s.file,
                    "index": s.index,
                    "name": s.name,
                    "reason": s.reason,
                }
                for s in self.skipped
            ],
            "orphans": list(self.orphans),
        }


def load_default_rules_with_report() -> Tuple[List[dict], LoadReport]:
    """聚合读取 rules 目录下所有 JSON 规则文件并校验，同时产出装载报告.

    Returns:
        ``(rules, report)`` —— 合法规则字典列表（按文件名字典序、文件内顺序）
        与结构化装载报告。
    """
    rules: List[dict] = []
    report = LoadReport()

    json_files = sorted(RULES_DIR.glob("*.json"))
    report.total_files = len(json_files)

    for jf in json_files:
        # 数据文件白名单：预期内的非规则文件，不告警、不计入跳过
        if jf.name in DATA_FILES:
            report.data_files.append(jf.name)
            logger.debug("数据文件 %s（非规则数组），按白名单跳过解析", jf.name)
            continue

        try:
            raw_text = jf.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载规则文件失败 %s: %s", jf.name, exc)
            report.skipped.append(
                SkipRecord(jf.name, -1, "<file>", f"文件解析失败: {exc}")
            )
            continue

        if not isinstance(data, list):
            logger.warning("规则文件 %s 顶层不是数组，跳过", jf.name)
            report.skipped.append(
                SkipRecord(jf.name, -1, "<file>", "顶层不是数组")
            )
            continue

        report.rule_files += 1
        report.total_entries += len(data)

        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                logger.warning("规则文件 %s 第 %d 条不是对象，跳过", jf.name, idx)
                report.skipped.append(
                    SkipRecord(jf.name, idx, "<unknown>", "条目不是对象")
                )
                continue
            name = item.get("name")
            if not name or not isinstance(name, str):
                logger.warning("规则文件 %s 第 %d 条缺少合法 name，跳过", jf.name, idx)
                report.skipped.append(
                    SkipRecord(jf.name, idx, "<unknown>", "缺少合法 name")
                )
                continue
            rule_type = item.get("rule_type")
            if rule_type not in RULE_TYPE_ENUM:
                logger.warning(
                    "规则 %s 的 rule_type 非法: %s，跳过", name, rule_type
                )
                report.skipped.append(
                    SkipRecord(jf.name, idx, name, f"rule_type 非法: {rule_type!r}")
                )
                continue
            if item.get("severity") not in SEVERITY_ENUM:
                logger.warning(
                    "规则 %s 的 severity 非法: %s，跳过", name, item.get("severity")
                )
                report.skipped.append(
                    SkipRecord(
                        jf.name, idx, name,
                        f"severity 非法: {item.get('severity')!r}",
                    )
                )
                continue
            condition = item.get("condition")
            if not isinstance(condition, dict):
                logger.warning("规则 %s 的 condition 非对象，跳过", name)
                report.skipped.append(
                    SkipRecord(jf.name, idx, name, "condition 非对象")
                )
                continue
            # 行为模式白名单校验（拼错直接拒绝，避免静默 False 永不命中）
            try:
                validate_condition(rule_type, condition)
            except ValueError as exc:
                logger.warning("规则 %s 条件校验失败: %s，跳过", name, exc)
                report.skipped.append(
                    SkipRecord(jf.name, idx, name, f"条件校验失败: {exc}")
                )
                continue
            rules.append(item)

    report.loaded = len(rules)

    # 启动摘要：跳过为 0 时 INFO，否则升级 WARNING 并逐条列明原因
    if report.skipped_count:
        logger.warning("%s", report.summary_line())
        for rec in report.skipped:
            logger.warning("  [RULE-SKIP] %s", rec)
    else:
        logger.info("%s", report.summary_line())

    return rules, report


def load_default_rules() -> List[dict]:
    """聚合读取 rules 目录下所有 JSON 规则文件并校验.

    保持原有签名与返回值（P2-3 向后兼容薄封装）。需要装载明细的调用方请用
    :func:`load_default_rules_with_report`。

    Returns:
        合法规则字典列表（按文件名字典序、文件内顺序）。
    """
    rules, _report = load_default_rules_with_report()
    return rules
