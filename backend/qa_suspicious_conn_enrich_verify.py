#!/usr/bin/env python3
"""可疑外连「一键威胁情报检测」独立可跑校验脚本（不联网）。

用法:
    venv/Scripts/python.exe qa_suspicious_conn_enrich_verify.py

行为:
  - 使用独立临时库 data/qa_suspicious_conn_enrich.db（每次运行重建）。
  - mock EnrichmentService 的 provider（FakeProvider，不联网、不写真实 key）。
  - 插入混合数据：公网恶意 IP、私网 IP、非法地址、重复公网 IP。
  - 调用 AnalysisService.enrich_suspicious_connections(host_id) 验证：
      * 返回统计 {total, public, enriched, malicious, suspicious, skipped_private, errors}
      * 检测结果正确写回 suspicious_connections（threat_level / threat_score / threat_tags / enriched_at）
      * threat_intel 表留痕（ioc_id 为 NULL）
  - 全部断言通过则打印 PASS 并以退出码 0 结束；否则抛 AssertionError（退出码非 0）。

注意：测试用公网 IP 均为真实公网地址（非 RFC5737 文档保留段，
以免被 ipaddress 判定为私网而被过滤）。
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

QA_DB_PATH = str(BACKEND_DIR / "data" / "qa_suspicious_conn_enrich.db")

from app.database import get_connection, init_db  # noqa: E402
from app.models.analysis import SuspiciousConnection  # noqa: E402
from app.models.threat_intel import ThreatIntel  # noqa: E402
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
)


class FakeProvider(BaseThreatIntelProvider):
    """不联网的假 provider，固定返回恶意判定。"""

    def query(self, ioc_type, ioc_value):
        return BaseThreatIntelProvider.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {"judgments": ["malicious"], "risk_score": 95, "tags": ["qa"]},
        )


def make_host() -> int:
    """插入一个 case + host，返回 host_id（满足外键约束）。"""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa-case')")
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, 'qa-host', 'analyzed')",
            (cid,),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def main() -> int:
    # 1) 准备独立测试库
    db_path = Path(QA_DB_PATH)
    if db_path.exists():
        db_path.unlink()
    settings.DB_PATH = QA_DB_PATH
    init_db()  # 含 _alter_suspicious_connections_table 迁移

    # 2) 插入主机与混合可疑外连数据（各连接独立连接，避免嵌套写锁）
    host_id = make_host()
    SuspiciousConnection.batch_create(host_id, [
        {"protocol": "tcp", "local_address": "0.0.0.0", "local_port": 0,
         "remote_address": "8.8.8.8", "remote_port": 443,
         "state": "ESTABLISHED", "process_name": "svchost.exe", "pid": 100,
         "reason": "r", "rule_name": "r1", "severity": "medium"},
        {"protocol": "tcp", "local_address": "0.0.0.0", "local_port": 0,
         "remote_address": "8.8.8.8", "remote_port": 8080,  # 去重
         "state": "ESTABLISHED", "process_name": "svchost.exe", "pid": 100,
         "reason": "r", "rule_name": "r1", "severity": "medium"},
        {"protocol": "tcp", "local_address": "0.0.0.0", "local_port": 0,
         "remote_address": "23.45.67.89", "remote_port": 443,  # 另一公网 IP
         "state": "ESTABLISHED", "process_name": "x", "pid": 101,
         "reason": "r", "rule_name": "r1", "severity": "medium"},
        {"protocol": "tcp", "local_address": "0.0.0.0", "local_port": 0,
         "remote_address": "192.168.1.50", "remote_port": 445,  # 私网
         "state": "ESTABLISHED", "process_name": "y", "pid": 102,
         "reason": "r", "rule_name": "r1", "severity": "medium"},
        {"protocol": "tcp", "local_address": "0.0.0.0", "local_port": 0,
         "remote_address": "not-an-ip", "remote_port": 80,  # 非法地址
         "state": "ESTABLISHED", "process_name": "z", "pid": 103,
         "reason": "r", "rule_name": "r1", "severity": "medium"},
    ])

    # 3) mock provider，调用 service
    fake = FakeProvider({"name": "fakebook", "type": "fake", "base_url": "https://fake"})
    with mock.patch.object(EnrichmentService, "get_provider", return_value=fake):
        EnrichmentService._instance = None
        stats = AnalysisService.enrich_suspicious_connections(host_id)

    # 4) 校验统计
    print("=== enrich_suspicious_connections 返回统计 ===")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    assert stats["total"] == 5, f"total 应为 5，实际 {stats['total']}"
    assert stats["public"] == 2, f"public 应为 2（去重后），实际 {stats['public']}"
    assert stats["enriched"] == 2, f"enriched 应为 2，实际 {stats['enriched']}"
    assert stats["malicious"] == 2, f"malicious 应为 2，实际 {stats['malicious']}"
    assert stats["suspicious"] == 0, f"suspicious 应为 0，实际 {stats['suspicious']}"
    assert stats["skipped_private"] == 1, f"skipped_private 应为 1，实际 {stats['skipped_private']}"
    assert stats["errors"] == [], f"errors 应为空，实际 {stats['errors']}"

    # 5) 校验写回 suspicious_connections
    rows = SuspiciousConnection.list_by_host(host_id)
    by_ip = {r["remote_address"]: r for r in rows}
    assert by_ip["8.8.8.8"]["threat_level"] == "high", "8.8.8.8 应标记为 high"
    assert by_ip["8.8.8.8"]["threat_score"] == 95, "8.8.8.8 的 risk_score 应为 95"
    assert by_ip["23.45.67.89"]["threat_level"] == "high", "23.45.67.89 应标记为 high"
    assert json.loads(by_ip["8.8.8.8"]["threat_tags"]) == ["qa"], "threat_tags 应为 JSON ['qa']"
    assert by_ip["192.168.1.50"]["threat_level"] is None, "私网地址不应写回威胁情报"
    assert by_ip["not-an-ip"]["threat_level"] is None, "非法地址不应写回威胁情报"

    # 6) 校验 threat_intel 留痕（ioc_id 为 NULL）
    ti_high = ThreatIntel.list_by_value("8.8.8.8")
    ti_other = ThreatIntel.list_by_value("23.45.67.89")
    assert len(ti_high) == 1 and ti_high[0]["ioc_id"] is None, "threat_intel 应留痕且 ioc_id 为 NULL"
    assert len(ti_other) == 1 and ti_other[0]["ioc_id"] is None, "23.45.67.89 threat_intel 应留痕"

    print("\n[PASS] 一键威胁情报检测（mock）校验全部通过")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\n[FAIL] 校验未通过: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] 校验异常: {exc}")
        sys.exit(2)
