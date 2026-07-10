#!/usr/bin/env python3
"""IOC 外联威胁情报（Enrichment）定时扫描脚本.

设计要点（复刻 ioc_feed_sync.py 的 --once/--loop/expand_env/单源失败隔离）:
  - 独立 CLI，直接 import ``app.services.enrichment_service`` 与
    ``app.models.threat_intel``，不依赖 HTTP 服务运行。
  - 扫描条件: enabled=1 且 type∈{ip,domain} 中，
    ``(ioc_id, provider)`` 维度上次查询已超过 ``recheck_days`` 天 或 从未查询者，
    且当日配额充足 → 自动 enrich。
  - ``AUTO_ENRICHMENT=False`` 时不执行任何动作（仅打印提示）。生产推荐 ``--once`` + 系统 cron。
  - 单 IOC 失败不阻断其他 IOC（单源失败隔离）。
  - 限流/配额与手动 API 共用 ``EnrichmentService`` 单例，保证当日配额一致。

零新增第三方依赖：网络用项目已有的 ``httpx``。
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 允许脚本从任意目录运行（确保 backend 目录在 sys.path 中）
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _THIS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.models.threat_intel import EnrichSettings  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    get_enrichment_service,
    QuotaExceededError,
    ThreatIntelQueryError,
)

logger = logging.getLogger("enrichment_scheduler")


def run_once() -> Dict[str, Any]:
    """单次扫描：跑全部待外联查询的 enabled ip/domain IOC（建议配合系统 cron）.

    Returns:
        扫描统计 ``{scanned, enriched, skipped, failed, auto_enrichment}``。
    """
    settings_dict = EnrichSettings.load()
    auto = bool(settings_dict.get("auto_enrichment", False))

    base_result: Dict[str, Any] = {
        "scanned": 0,
        "enriched": 0,
        "skipped": 0,
        "failed": 0,
        "auto_enrichment": auto,
    }

    if not auto:
        logger.info("AUTO_ENRICHMENT 未开启（auto_enrichment=False），跳过自动外联扫描")
        return base_result

    svc = get_enrichment_service()
    try:
        result = svc.scan_pending_iocs()
    except (QuotaExceededError, ThreatIntelQueryError) as exc:
        logger.error("外联扫描初始化失败，本轮跳过: %s", exc)
        return {**base_result, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("外联扫描异常，本轮跳过: %s", exc)
        return {**base_result, "error": str(exc)}

    logger.info(
        "外联扫描完成: total=%d enriched=%d skipped=%d failed=%d",
        result.get("total", 0),
        result.get("enriched", 0),
        result.get("skipped", 0),
        result.get("failed", 0),
    )
    return {**base_result, **result}


def run_loop() -> None:
    """内置循环调度：按 scheduler_interval 轮询（开发/演示用，Ctrl+C 退出）.

    零新增依赖；每轮调用 ``run_once``，循环间 sleep ``scheduler_interval`` 秒。
    """
    logger.info("进入循环调度（Ctrl+C 退出）")
    try:
        while True:
            settings_dict = EnrichSettings.load()
            interval = int(settings_dict.get("scheduler_interval", 3600))
            if not bool(settings_dict.get("auto_enrichment", False)):
                logger.info("AUTO_ENRICHMENT 未开启，循环调度空转（interval=%ds）", interval)
            else:
                run_once()
            time.sleep(max(1, interval))
    except KeyboardInterrupt:
        logger.info("收到 KeyboardInterrupt，优雅退出循环调度")


def main(argv: Optional[list] = None) -> int:
    """CLI 入口.

    Args:
        argv: 命令行参数（默认取 ``sys.argv[1:]``）。

    Returns:
        进程退出码（0 表示成功）。
    """
    parser = argparse.ArgumentParser(
        description="IOC 外联威胁情报（Enrichment）定时扫描脚本"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="单次扫描全部待查询的 IOC（建议配合系统 cron）",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="内置循环调度（按 scheduler_interval 轮询，Ctrl+C 退出）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 确保 threat_intel 表存在（不依赖 HTTP 服务运行）
    from app.database import init_db

    init_db()

    if args.loop and not args.once:
        run_loop()
    else:
        run_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
