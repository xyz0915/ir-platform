"""独立验证：清案服务须将 rules 运行时统计归零（bug 修复验证）。

与本仓库既有 ``test_purge_isolated.py`` 分离，聚焦单一回归点：
purge_case 之后，态势感知大屏「规则命中」所用的 ``rules.hit_count`` 聚合
必须归零，且 ``last_hit_at`` / ``avg_risk_score`` 一并清理；
preview_case_purge 须返回合理的 ``rules_reset`` 预估值。

⚠️ 安全红线：全程使用临时隔离 SQLite 文件（tempfile + 重设 settings.DB_PATH
+ init_db），绝不指向 backend/data/ 下的真实 ir.db；且 purge 调用使用
export_snapshot=False，避免向真实 data 目录落盘快照文件。

运行方式（任选其一）：
    cd backend && python -m pytest tests/test_purge_rules_reset_verify.py -v
    cd backend && python tests/test_purge_rules_reset_verify.py
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import app.config as config_module  # noqa: E402
settings = config_module.settings  # noqa: E402
from app.database import get_connection, init_db  # noqa: E402
from app.services import purge_service  # noqa: E402


def _setup_temp_db(tmp_path: Path) -> Path:
    """把 settings.DB_PATH 指向临时文件并初始化 schema（不影响真实库）。"""
    db_path = tmp_path / "verify_ir_isolated.db"
    settings.DB_PATH = str(db_path)
    init_db()
    return db_path


def _seed(conn) -> None:
    """灌入 1 个案件 + 1 台主机 + 1 条告警，以及 2 条含命中统计的规则。

    规则统计刻意设为非 0（58 / 10，合计 68），模拟「清案前大屏残留数字」，
    用于验证清案后能否正确归零。
    """
    conn.execute(
        "INSERT INTO cases (id, name, case_number, status) VALUES (?, ?, ?, ?)",
        (1, "案件1", "CASE-0001", "open"),
    )
    conn.execute(
        "INSERT INTO hosts (id, case_id, hostname, ip_address) VALUES (?, ?, ?, ?)",
        (1, 1, "host-1", "10.0.0.1"),
    )
    # 案件直辖行：用于验证级联归零
    conn.execute(
        "INSERT INTO alerts (host_id, case_id, rule_name, title) VALUES (?, ?, ?, ?)",
        (1, 1, "r", "t"),
    )
    # 清空默认规则（若存在），插入 2 条带运行时命中统计的规则
    conn.execute("DELETE FROM rules")
    conn.execute(
        "INSERT INTO rules (name, hit_count, last_hit_at, avg_risk_score) VALUES (?, ?, ?, ?)",
        ("rule_a", 58, "2026-01-01T00:00:00Z", 0.9),
    )
    conn.execute(
        "INSERT INTO rules (name, hit_count, last_hit_at, avg_risk_score) VALUES (?, ?, ?, ?)",
        ("rule_b", 10, "2026-01-01T00:00:00Z", 0.5),
    )


def test_purge_resets_rules_stats_and_preview(tmp_path):
    """清案须将 rules 命中统计归零，且 preview 返回合理 rules_reset 预估。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed(conn)

    # ── 前置断言：清案前确有残留（模拟 bug 触发条件）──
    with get_connection() as conn:
        pre_sum = conn.execute(
            "SELECT COALESCE(SUM(hit_count), 0) FROM rules"
        ).fetchone()[0]
    assert pre_sum == 68, f"清案前 SUM(hit_count) 应为 68，实际 {pre_sum}"
    # dashboard.py:171-172 的口径
    with get_connection() as conn:
        dash_metric = conn.execute(
            "SELECT COALESCE(SUM(hit_count), 0) FROM rules"
        ).fetchone()[0]
    assert dash_metric == 68, "清案前态势大屏规则命中口径应为 68"

    # ── preview：应返回 rules_reset = 命中数 > 0 的规则条数（此处 2）──
    preview = purge_service.preview_case_purge(1)
    assert preview["case_id"] == 1
    assert "rules_reset" in preview, "preview 响应缺少 rules_reset 字段"
    assert preview["rules_reset"] == 2, (
        f"preview.rules_reset 应为 2（命中数>0 的规则数），实际 {preview['rules_reset']}"
    )
    # table_counts 内也应含 rules_reset，且与顶层一致（前端预览表据此渲染）
    assert "rules_reset" in preview["table_counts"], (
        "preview.table_counts 缺少 rules_reset 键，前端预览表无法渲染"
    )
    assert preview["table_counts"]["rules_reset"] == preview["rules_reset"]

    # ── 执行清案（export_snapshot=False：不向真实 data 目录落盘）──
    res = purge_service.purge_case(
        1, "1", {"id": 1, "username": "admin", "role": "admin"},
        export_snapshot=False,
    )
    assert res["purged_case_id"] == 1

    # 返回字段 rules_reset 应为 > 0（= UPDATE 影响行数 = rules 总行数）
    assert "rules_reset" in res["table_counts"], "清案返回 table_counts 缺少 rules_reset"
    assert res["table_counts"]["rules_reset"] > 0, (
        f"清案返回 rules_reset 应 > 0，实际 {res['table_counts']['rules_reset']}"
    )

    # ── 核心断言：清案后 rules 运行时统计全部归零 ──
    with get_connection() as conn:
        post_sum = conn.execute(
            "SELECT COALESCE(SUM(hit_count), 0) FROM rules"
        ).fetchone()[0]
        assert post_sum == 0, f"清案后 SUM(hit_count) 应为 0，实际 {post_sum}"

        # last_hit_at 全部清空
        not_null = conn.execute(
            "SELECT COUNT(*) FROM rules WHERE last_hit_at IS NOT NULL"
        ).fetchone()[0]
        assert not_null == 0, f"清案后 last_hit_at 应全为 NULL，仍有 {not_null} 条残留"

        # avg_risk_score 全部归零
        nonzero = conn.execute(
            "SELECT COUNT(*) FROM rules WHERE avg_risk_score != 0"
        ).fetchone()[0]
        assert nonzero == 0, f"清案后 avg_risk_score 应全为 0，仍有 {nonzero} 条非零"

        # rules 全局配置表本身不被删除（仅归零统计）
        total_rules = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        assert total_rules == 2, f"rules 配置不应被删除，应保留 2 条，实际 {total_rules}"

        # 其他案件级联表正确归零
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE case_id=1").fetchone()[0] == 0

        # 审计留痕存在（验证整体事务未因 rules 归零而异常）
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 1


def test_purge_resets_rules_when_no_rules_hit(tmp_path):
    """边界：若所有规则 hit_count 本就为 0，清案不应报错且 SUM 仍为 0。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO cases (id, name, case_number, status) VALUES (?, ?, ?, ?)",
            (1, "案件1", "CASE-0001", "open"),
        )
        conn.execute(
            "INSERT INTO hosts (id, case_id, hostname, ip_address) VALUES (?, ?, ?, ?)",
            (1, 1, "host-1", "10.0.0.1"),
        )
        conn.execute("DELETE FROM rules")
        conn.execute("INSERT INTO rules (name) VALUES (?)", ("rule_idle",))

    preview = purge_service.preview_case_purge(1)
    assert preview["rules_reset"] == 0, "无命中规则时 preview.rules_reset 应为 0"

    res = purge_service.purge_case(
        1, "1", {"id": 1, "username": "admin", "role": "admin"},
        export_snapshot=False,
    )
    assert res["table_counts"]["rules_reset"] == 1  # UPDATE 仍影响 1 行
    with get_connection() as conn:
        assert conn.execute("SELECT COALESCE(SUM(hit_count),0) FROM rules").fetchone()[0] == 0


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in funcs:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"PASS  {fn.__name__}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                import traceback
                print(f"FAIL  {fn.__name__}: {e}")
                traceback.print_exc()
    print(f"\n{passed}/{len(funcs)} passed")
