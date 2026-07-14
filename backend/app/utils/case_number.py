"""案件编号自动生成工具."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_case_number(conn) -> str:
    """自动生成唯一案件编号：CASE-{YYYYMMDD}-{NNNN}

    当日序号从 0001 起，跨天重置。
    必须在已有事务的 connection 内调用。
    """
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"CASE-{today}-"
    row = conn.execute(
        "SELECT case_number FROM cases WHERE case_number LIKE ? ORDER BY case_number DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if row:
        last_seq = int(row["case_number"].split("-")[-1])
        seq = last_seq + 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"
