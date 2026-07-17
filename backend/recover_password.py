"""一次性账号恢复脚本 — 重置被 werkzeug(pbkdf2) 污染的密码哈希为 bcrypt。

背景：
  系统管理里改密码/建用户曾误用 werkzeug 的 generate_password_hash（默认 pbkdf2:sha256），
  而登录校验使用 bcrypt，导致用户改完密码后无法登录。

  本脚本把 users 表中所有“非 bcrypt（$2 开头）”的 password_hash 重置为
  TEMP_PASSWORD 的 bcrypt 哈希，使受影响用户能立即用临时密码登录，
  随后可在 UI 自行改回正式密码。

使用后可直接删除本文件，不影响业务代码。
"""

import os
import sqlite3
import sys

# 允许从 backend/ 目录直接运行，导入 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.auth_service import pwd_context  # 与登录校验一致的 bcrypt 方案

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ir_platform.db")
TEMP_PASSWORD = "Recover@2026"


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    reset_users: list[str] = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, username, password_hash FROM users").fetchall()

        for row in rows:
            current_hash = row["password_hash"] or ""
            # bcrypt 哈希以 $2 开头（$2b$ / $2a$ / $2y$）
            if not current_hash.startswith("$2"):
                new_hash = pwd_context.hash(TEMP_PASSWORD)
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_hash, row["id"]),
                )
                reset_users.append(row["username"])

        conn.commit()

    if reset_users:
        print("[OK] 以下用户密码已被重置为临时密码 'Recover@2026'（bcrypt 哈希）：")
        for name in reset_users:
            print(f"  - {name}")
        print(f"\n共重置 {len(reset_users)} 个用户。请登录后尽快在 UI 修改密码。")
    else:
        print("[OK] 没有发现非 bcrypt 的密码哈希，所有用户已是 bcrypt 方案，无需重置。")


if __name__ == "__main__":
    main()
