#!/usr/bin/env python3
"""外部威胁源（MISP / STIX / CSV）定时拉取与灌表脚本.

设计要点:
  - 独立 CLI，直接 import ``app.models.ioc.Ioc`` 写库，不依赖 HTTP 服务运行。
  - 三种解析器（CSV / MISP / STIX）均为纯函数，输出统一结构
    ``list[dict]``，每项 ``{ioc_type, ioc_value, source, description}``，
    便于单元测试且不触发任何网络请求。
  - 灌表统一走 ``Ioc.batch_create``（自带 (ioc_type, ioc_value) 去重写入）。
  - 调度支持 ``--once``（单次跑全部 enabled feed，配系统 cron 最稳）与
    ``--loop``（内置 time.sleep 轮询，零新增依赖，Ctrl+C 优雅退出）。
  - 单源失败不阻断其他源；MISP 加 ``Authorization`` 头并支持 ``$ENV_VAR`` 占位。

零新增第三方依赖：网络用项目已有的 ``httpx``，STIX/MISP 解析用内置 ``json`` + ``re``。
"""

import argparse
import csv
import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

# 允许脚本从任意目录运行（确保 backend 目录在 sys.path 中）
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _THIS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.models.ioc import Ioc  # noqa: E402

logger = logging.getLogger("ioc_feed_sync")

# IOC 允许的类型集合（与 ioc_type 枚举 {ip,domain,url,hash,cert} 一致）
ALLOWED_TYPES = {"ip", "domain", "url", "hash", "cert"}

# MISP attribute.type -> 系统 ioc_type
MISP_TYPE_MAP = {
    "ip-dst": "ip",
    "ip-src": "ip",
    "domain": "domain",
    "url": "url",
    "md5": "hash",
    "sha1": "hash",
    "sha256": "hash",
    "x509-certificate": "cert",
}

# STIX 2.x indicator pattern -> 系统 ioc_type（正则）
STIX_PATTERNS = [
    ("ip", re.compile(r"\[(?:ip-addr|ipv4-addr):value\s*=\s*['\"]([^'\"]+)['\"]\]")),
    ("domain", re.compile(r"\[domain-name:value\s*=\s*['\"]([^'\"]+)['\"]\]")),
    ("url", re.compile(r"\[url:value\s*=\s*['\"]([^'\"]+)['\"]\]")),
    (
        "hash",
        re.compile(
            r"\[file:hashes\.?(?:'SHA-256'|'SHA-1'|'MD5'|SHA-256|SHA-1|MD5)"
            r"\s*=\s*['\"]([^'\"]+)['\"]\]"
        ),
    ),
    ("cert", re.compile(r"\[x509-certificate:[^\]]*=\s*['\"]([^'\"]+)['\"]\]")),
]


def expand_env(value: Any) -> Any:
    """展开以 ``$`` 开头的环境变量占位符.

    Args:
        value: 待展开的值，仅当其为字符串且以 ``$`` 开头时展开。

    Returns:
        展开后的字符串；未设置对应环境变量时返回空字符串；非占位值原样返回。
    """
    if isinstance(value, str) and value.startswith("$"):
        var_name = value[1:]
        return os.environ.get(var_name, "")
    return value


def load_feeds(config_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """读取 feed 配置文件并展开其中的环境变量占位符.

    Args:
        config_path: feed 配置文件（JSON）路径。

    Returns:
        feed 列表，每个元素为 dict（api_key 中的 ``$ENV_VAR`` 已展开）。
    """
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as fh:
        feeds = json.load(fh)

    for feed in feeds:
        api_key = feed.get("api_key")
        if isinstance(api_key, str) and api_key.startswith("$"):
            feed["api_key"] = expand_env(api_key)
    return feeds


def parse_csv(
    text: str,
    type_map: Optional[Dict[str, str]] = None,
    source: str = "csv-feed",
) -> List[Dict[str, str]]:
    """解析 CSV 文本为统一 IOC 结构.

    支持两种列命名：``type``/``value`` 或 ``ioc_type``/``ioc_value``。
    当存在 ``type`` 列时，可用 ``type_map`` 将列值映射到系统 ``ioc_type``；
    若 ``type_map`` 中无对应项则原样使用。空行、缺值行、无法判定合法
    ``ioc_type`` 的行均跳过。

    Args:
        text: CSV 文本内容。
        type_map: 可选，CSV 类型列值到系统 ioc_type 的映射。
        source: 来源标识（用于溯源，标注 feed 名）。

    Returns:
        统一结构 ``list[dict]``，每项 ``{ioc_type, ioc_value, source, description}``。
    """
    type_map = type_map or {}
    items: List[Dict[str, str]] = []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return items

    # 大小写不敏感地定位列名
    field_lookup = {name.lower(): name for name in reader.fieldnames}

    value_col = None
    for candidate in ("ioc_value", "value"):
        if candidate in field_lookup:
            value_col = field_lookup[candidate]
            break

    type_col = None
    for candidate in ("ioc_type", "type"):
        if candidate in field_lookup:
            type_col = field_lookup[candidate]
            break

    desc_col = field_lookup.get("description")

    # 没有取值列则无法解析任何 IOC
    if value_col is None:
        return items

    for row in reader:
        raw_value = (row.get(value_col) or "").strip()
        if not raw_value:
            continue  # 空值跳过

        if type_col is not None:
            raw_type = (row.get(type_col) or "").strip()
        else:
            raw_type = ""

        if raw_type:
            ioc_type = type_map.get(raw_type, raw_type)
        else:
            ioc_type = ""

        if ioc_type not in ALLOWED_TYPES:
            continue  # 缺列 / 非法类型跳过

        description = (row.get(desc_col) or "").strip() if desc_col else ""
        items.append(
            {
                "ioc_type": ioc_type,
                "ioc_value": raw_value,
                "source": source,
                "description": description,
            }
        )
    return items


def parse_misp(json_obj: Dict[str, Any], source: str) -> List[Dict[str, str]]:
    """解析 MISP restSearch 响应 JSON 为统一 IOC 结构.

    解析 ``response["Event"][].Attribute[]``，按 ``type`` 映射到系统 ioc_type，
    只取 ``value`` 非空项。``source`` 标注 feed 名便于溯源。

    Args:
        json_obj: MISP 响应 JSON（已解析 dict）。
        source: 来源标识（feed 名）。

    Returns:
        统一结构 ``list[dict]``。
    """
    items: List[Dict[str, str]] = []
    events = json_obj.get("Event", []) or []
    for event in events:
        attributes = event.get("Attribute", []) or []
        for attr in attributes:
            raw_type = attr.get("type", "")
            value = attr.get("value", "")
            if not value:
                continue  # 空值跳过
            ioc_type = MISP_TYPE_MAP.get(raw_type)
            if not ioc_type:
                continue  # 不支持的类型跳过
            description = attr.get("comment") or attr.get("category") or ""
            items.append(
                {
                    "ioc_type": ioc_type,
                    "ioc_value": str(value).strip(),
                    "source": source,
                    "description": description,
                }
            )
    return items


def parse_stix(json_obj: Dict[str, Any], source: str) -> List[Dict[str, str]]:
    """解析 STIX 2.x bundle JSON 为统一 IOC 结构（内置 json + 正则，不引 stix2）.

    解析 ``bundle["objects"]`` 中 ``type == "indicator"`` 的 ``pattern``，
    用正则提取值并映射：``ip-addr``/``ipv4-addr``→``ip``、``domain-name``→``domain``、
    ``url``→``url``、``file:hashes.'SHA-256'``/``file:hashes.SHA-256``→``hash``、
    ``x509-certificate``→``cert``。

    Args:
        json_obj: STIX bundle JSON（已解析 dict）。
        source: 来源标识（feed 名）。

    Returns:
        统一结构 ``list[dict]``。
    """
    items: List[Dict[str, str]] = []
    objects = json_obj.get("objects", []) or []
    for obj in objects:
        if obj.get("type") != "indicator":
            continue
        pattern = obj.get("pattern", "") or ""
        description = obj.get("name") or obj.get("description") or ""
        for ioc_type, regex in STIX_PATTERNS:
            match = regex.search(pattern)
            if match:
                items.append(
                    {
                        "ioc_type": ioc_type,
                        "ioc_value": match.group(1).strip(),
                        "source": source,
                        "description": description,
                    }
                )
                break  # 单个 indicator 只取首个可识别的 IOC
    return items


def fetch_feed_text(feed: Dict[str, Any], timeout: float = 30.0) -> str:
    """用 httpx 拉取 feed URL 文本，返回响应体字符串.

    MISP feed 自动附加 ``Authorization: <api_key>`` 头（``$ENV_VAR`` 已预先展开）。
    超时与 HTTP 错误会向上抛出，由调用方决定降级策略。

    Args:
        feed: 单个 feed 配置 dict（需含 ``url``，可选 ``api_key``）。
        timeout: 请求超时（秒）。

    Returns:
        HTTP 响应体文本。

    Raises:
        ValueError: feed 缺少 url。
        httpx.HTTPError: 网络/HTTP 错误。
    """
    url = feed.get("url")
    if not url:
        raise ValueError(f"feed {feed.get('name')} 缺少 url")

    headers: Dict[str, str] = {}
    api_key = feed.get("api_key")
    if api_key:
        api_key = expand_env(api_key)
        if api_key:
            headers["Authorization"] = api_key

    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout), follow_redirects=True
        ) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as exc:
        logger.error("拉取 feed %s 失败: %s", feed.get("name"), exc)
        raise


def sync_feed(feed: Dict[str, Any]) -> Tuple[int, int]:
    """拉取并解析单个 feed，灌入 iocs 表.

    Args:
        feed: 单个 feed 配置 dict。

    Returns:
        ``(inserted, parsed)``：新插入条数、解析出的 IOC 条数。

    Raises:
        任何拉取/解析/写库异常都会向上抛出（由 run_once/run_loop 捕获降级）。
    """
    fmt = feed.get("format")
    source = feed.get("name", "unknown")
    text = fetch_feed_text(feed)

    if fmt == "csv":
        items = parse_csv(text, feed.get("type_map"), source)
    elif fmt == "misp":
        items = parse_misp(json.loads(text), source)
    elif fmt == "stix":
        items = parse_stix(json.loads(text), source)
    else:
        raise ValueError(f"未知 feed 格式: {fmt!r} (feed={source})")

    inserted = Ioc.batch_create(items)
    return inserted, len(items)


def run_once(feeds: List[Dict[str, Any]]) -> int:
    """单次运行：跑全部 ``enabled=true`` 的 feed（建议配合系统 cron）.

    Args:
        feeds: feed 列表。

    Returns:
        本次新插入的 IOC 总条数。
    """
    total_inserted = 0
    for feed in feeds:
        if not feed.get("enabled", True):
            logger.info("跳过未启用的 feed: %s", feed.get("name"))
            continue
        try:
            inserted, parsed = sync_feed(feed)
            total_inserted += inserted
            logger.info(
                "feed %s: 解析 %d 条，新插入 %d 条",
                feed.get("name"),
                parsed,
                inserted,
            )
        except Exception as exc:  # noqa: BLE001 — 单源失败不阻断其他源
            logger.error("feed %s 同步失败，已跳过: %s", feed.get("name"), exc)
    return total_inserted


def run_loop(feeds: List[Dict[str, Any]]) -> None:
    """内置循环调度：按各 feed 的 ``interval`` 用 ``time.sleep`` 轮询.

    零新增依赖；支持 Ctrl+C 优雅退出。每个 feed 独立记录上次成功/尝试时间，
    到点才同步；持续失败也不会忙等（失败后同样推进该 feed 的时间戳）。

    Args:
        feeds: feed 列表。
    """
    enabled_feeds = [f for f in feeds if f.get("enabled", True)]
    if not enabled_feeds:
        logger.warning("没有启用的 feed，循环调度退出")
        return

    last_run = {f["name"]: 0.0 for f in enabled_feeds}
    logger.info("进入循环调度（%d 个启用 feed），Ctrl+C 退出", len(enabled_feeds))
    try:
        while True:
            now = time.time()
            for feed in enabled_feeds:
                interval = feed.get("interval", 3600)
                if now - last_run[feed["name"]] >= interval:
                    try:
                        inserted, parsed = sync_feed(feed)
                        logger.info(
                            "feed %s: 解析 %d 条，新插入 %d 条",
                            feed["name"],
                            parsed,
                            inserted,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "feed %s 同步失败，已跳过: %s", feed["name"], exc
                        )
                    finally:
                        # 无论成功失败都推进时间戳，避免持续失败导致忙等
                        last_run[feed["name"]] = time.time()

            # 计算到下一个 feed 到点的最短等待时间（封顶 60s 轮询粒度）
            min_wait = min(
                max(
                    0.0,
                    f.get("interval", 3600) - (time.time() - last_run[f["name"]]),
                )
                for f in enabled_feeds
            )
            time.sleep(min(min_wait, 60.0))
    except KeyboardInterrupt:
        logger.info("收到 KeyboardInterrupt，优雅退出循环调度")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 入口.

    Args:
        argv: 命令行参数（默认取 ``sys.argv[1:]``）。

    Returns:
        进程退出码（0 表示成功）。
    """
    parser = argparse.ArgumentParser(
        description="外部威胁源（MISP/STIX/CSV）IOC 定时拉取与灌表脚本"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="单次运行全部启用的 feed（建议配合系统 cron）",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="内置循环调度（按各 feed interval 轮询，Ctrl+C 退出）",
    )
    parser.add_argument(
        "--config",
        default=str(_THIS_DIR / "ioc_feeds.json"),
        help="feed 配置文件路径（默认 scripts/ioc_feeds.json）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 确保 iocs 表存在（不依赖 HTTP 服务运行）
    from app.database import init_db

    init_db()

    feeds = load_feeds(args.config)
    if not feeds:
        logger.warning("feed 列表为空，退出")
        return 0

    if args.loop and not args.once:
        run_loop(feeds)
    else:
        total = run_once(feeds)
        logger.info("单次同步完成，共新插入 %d 条 IOC", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
