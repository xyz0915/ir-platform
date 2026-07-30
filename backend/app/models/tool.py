"""应急工具数据模型."""
import json
import sqlite3
from datetime import datetime
from app.database import get_connection


class Tool:
    """工具主表 CRUD."""

    @staticmethod
    def create(
        name: str,
        description: str,
        category: str,
        author_id: int,
        version: str,
        tags: list,
        file_name: str,
        file_path: str,
        file_size: int,
        file_hash: str,
        doc_file_name: str = "",
        doc_file_path: str = "",
    ) -> int:
        """创建新工具并插入初始版本记录.

        Returns:
            int: 新创建的 tool_id.
        """
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO tools (name, description, category, author_id,
                   current_version, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, description, category, author_id, version,
                 json.dumps(tags, ensure_ascii=False)),
            )
            tool_id = cur.lastrowid
            conn.execute(
                """INSERT INTO tool_versions (tool_id, version, file_name, file_path,
                   file_size, file_hash, doc_file_name, doc_file_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tool_id, version, file_name, file_path, file_size, file_hash,
                 doc_file_name, doc_file_path),
            )
            return tool_id

    @staticmethod
    def get_by_id(tool_id: int) -> dict | None:
        """根据 ID 获取工具详情."""
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if row:
                d = dict(row)
                try:
                    d["tags"] = json.loads(d.get("tags", "[]"))
                except (json.JSONDecodeError, TypeError):
                    d["tags"] = []
                return d
            return None

    @staticmethod
    def search(
        keyword: str = "",
        category: str = "",
        sort_by: str = "updated_at",
        sort_dir: str = "DESC",
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """分页搜索工具列表.

        Args:
            keyword: 名称/描述模糊搜索.
            category: 分类精确筛选（"全部"表示不过滤）.
            sort_by: 排序字段（白名单控制）.
            sort_dir: ASC 或 DESC.
            offset: 分页偏移.
            limit: 每页数量.

        Returns:
            list[dict]: 工具字典列表.
        """
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            conditions: list[str] = ["status='active'"]
            params: list = []
            if keyword:
                conditions.append("(name LIKE ? OR description LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw])
            if category and category != "全部":
                conditions.append("category=?")
                params.append(category)
            # 安全排序防止 SQL 注入
            allowed_sort = {"updated_at", "created_at", "download_count", "name"}
            if sort_by not in allowed_sort:
                sort_by = "updated_at"
            sort_dir_upper = "DESC" if sort_dir.upper() != "ASC" else "ASC"
            sql = (
                f"SELECT * FROM tools WHERE {' AND '.join(conditions)} "
                f"ORDER BY {sort_by} {sort_dir_upper} LIMIT ? OFFSET ?"
            )
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags", "[]"))
                except (json.JSONDecodeError, TypeError):
                    d["tags"] = []
                result.append(d)
            return result

    @staticmethod
    def count(keyword: str = "", category: str = "") -> int:
        """统计符合条件的工具总数."""
        with get_connection() as conn:
            conditions: list[str] = ["status='active'"]
            params: list = []
            if keyword:
                conditions.append("(name LIKE ? OR description LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw])
            if category and category != "全部":
                conditions.append("category=?")
                params.append(category)
            row = conn.execute(
                f"SELECT COUNT(*) as c FROM tools WHERE {' AND '.join(conditions)}",
                params,
            ).fetchone()
            return row[0] if row else 0

    @staticmethod
    def update(tool_id: int, **kwargs) -> bool:
        """更新工具基本信息.

        仅允许更新白名单中的字段：name, description, category, tags, status.

        Returns:
            bool: 是否更新成功.
        """
        allowed = {"name", "description", "category", "tags", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [tool_id]
        with get_connection() as conn:
            conn.execute(f"UPDATE tools SET {set_clause} WHERE id=?", vals)
            return conn.total_changes > 0

    @staticmethod
    def delete(tool_id: int) -> bool:
        """硬删除工具（ON DELETE CASCADE 自动清理关联表）. """
        with get_connection() as conn:
            conn.execute("DELETE FROM tools WHERE id=?", (tool_id,))
            return conn.total_changes > 0

    @staticmethod
    def get_stats() -> dict:
        """获取统计概览.

        Returns:
            dict: {total_tools, total_downloads, today_new, category_count}.
        """
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM tools WHERE status='active'"
            ).fetchone()[0]
            downloads = conn.execute(
                "SELECT COALESCE(SUM(download_count),0) FROM tools"
            ).fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM tools WHERE date(created_at)=date('now','localtime')"
            ).fetchone()[0]
            cats = conn.execute(
                "SELECT COUNT(DISTINCT category) FROM tools WHERE status='active'"
            ).fetchone()[0]
            return {
                "total_tools": total,
                "total_downloads": downloads,
                "today_new": today,
                "category_count": cats,
            }

    @staticmethod
    def get_categories() -> list[dict]:
        """获取分类列表（含各分类计数）. """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM tools WHERE status='active' GROUP BY category ORDER BY count DESC"
            ).fetchall()
            return [{"category": r[0], "count": r[1]} for r in rows]


class ToolVersion:
    """工具版本 CRUD."""

    @staticmethod
    def get_by_tool_id(tool_id: int) -> list[dict]:
        """获取某工具的全部版本，按创建时间降序."""
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tool_versions WHERE tool_id=? ORDER BY created_at DESC",
                (tool_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(version_id: int) -> dict | None:
        """根据版本 ID 获取版本详情."""
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tool_versions WHERE id=?", (version_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_current_version(tool_id: int) -> dict | None:
        """获取某工具的当前（最新）版本."""
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tool_versions WHERE tool_id=? ORDER BY created_at DESC LIMIT 1",
                (tool_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(
        tool_id: int,
        version: str,
        file_name: str,
        file_path: str,
        file_size: int,
        file_hash: str,
        doc_file_name: str = "",
        doc_file_path: str = "",
        doc_file_type: str = "",
        change_log: str = "",
    ) -> int:
        """创建新版本记录并更新 tools 表的 current_version.

        Returns:
            int: 新版本 ID.
        """
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO tool_versions (tool_id, version, file_name, file_path,
                   file_size, file_hash, doc_file_name, doc_file_path, doc_file_type, change_log)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tool_id, version, file_name, file_path, file_size, file_hash,
                 doc_file_name, doc_file_path, doc_file_type, change_log),
            )
            conn.execute(
                "UPDATE tools SET current_version=?, updated_at=datetime('now','localtime') WHERE id=?",
                (version, tool_id),
            )
            return cur.lastrowid

    @staticmethod
    def delete_by_tool_id(tool_id: int) -> None:
        """删除某工具的所有版本记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM tool_versions WHERE tool_id=?", (tool_id,))


class ToolDownload:
    """下载日志 CRUD."""

    @staticmethod
    def log(
        tool_id: int,
        version_id: int,
        user_id: int | None = None,
        ip_address: str = "",
    ) -> None:
        """记录一次下载，同时递增 tools.download_count."""
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO tool_downloads (tool_id, version_id, user_id, ip_address) VALUES (?, ?, ?, ?)",
                (tool_id, version_id, user_id, ip_address),
            )
            conn.execute(
                "UPDATE tools SET download_count=download_count+1 WHERE id=?",
                (tool_id,),
            )

    @staticmethod
    def count_by_tool_id(tool_id: int) -> int:
        """统计某工具的下载次数."""
        with get_connection() as conn:
            r = conn.execute(
                "SELECT COUNT(*) FROM tool_downloads WHERE tool_id=?", (tool_id,)
            ).fetchone()
            return r[0] if r else 0
