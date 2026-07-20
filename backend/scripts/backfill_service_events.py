"""回溯已有 service_operation 事件的 evidence 字段。

从导入 JSON 文件中读取原始服务数据，回填到 security_events 的 evidence 字段。
支持新旧两种 Agent 数据格式。
"""
import json
import logging
import sys
from pathlib import Path

# 确保能找到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_connection
from app.services.import_service import ImportService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def backfill():
    """回溯所有 service_operation 事件的 evidence 字段."""
    count = 0
    fail = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, host_id, evidence FROM security_events WHERE event_type='service_operation'"
        ).fetchall()

    for row in rows:
        event_id = row["id"]
        host_id = row["host_id"]
        old_ev = row["evidence"]

        # 如果已有 path 字段且有值，跳过
        if old_ev:
            try:
                ev = json.loads(old_ev) if isinstance(old_ev, str) else old_ev
                if ev.get("path"):
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

        # 读导入 JSON
        raw = ImportService.read_raw_json(host_id)
        if not raw:
            fail += 1
            continue

        # 从 services 匹配基本字段
        services = raw.get("services", [])
        svc = None
        for s in services:
            if s.get("name") == get_name_from_event(old_ev):
                svc = s
                break

        # 从 persistence.services 补 path（command 字段）
        persist_path = None
        persist_data = raw.get("persistence", {})
        if isinstance(persist_data, dict):
            persist_svcs = persist_data.get("services", [])
            if isinstance(persist_svcs, list):
                for ps in persist_svcs:
                    if isinstance(ps, dict) and ps.get("name") == get_name_from_event(old_ev):
                        persist_path = ps.get("command")
                        break
        if not svc:
            fail += 1
            continue

        # 构建新 evidence
        new_ev = {
            "name": svc.get("name"),
            "path": (svc.get("path") or svc.get("binary_path") or persist_path),  # 优先原始字段，再交叉补
            "display_name": svc.get("display_name"),
            "start_type": svc.get("start_type"),
            "status": svc.get("status"),
            "user": svc.get("user") or svc.get("account"),
            "description": svc.get("description"),
        }
        with get_connection() as conn:
            conn.execute(
                "UPDATE security_events SET evidence=? WHERE id=?",
                (json.dumps(new_ev, ensure_ascii=False), event_id),
            )
        count += 1

    logger.info("回溯完成: 成功 %d, 失败 %d", count, fail)


def get_name_from_event(old_ev: str) -> str:
    """从旧 evidence 中提取 name."""
    try:
        ev = json.loads(old_ev) if isinstance(old_ev, str) else old_ev
        return ev.get("name", "")
    except (json.JSONDecodeError, TypeError):
        return ""


if __name__ == "__main__":
    backfill()
