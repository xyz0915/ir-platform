"""案件业务逻辑服务."""

import logging
from typing import Optional

from app.models.case import Case

logger = logging.getLogger(__name__)


class CaseService:
    """案件业务逻辑层."""

    @staticmethod
    def create_case(name: str, case_number: Optional[str] = None,
                    description: Optional[str] = None) -> dict:
        """创建案件.

        Raises:
            ValueError: 案件编号重复时抛出.
        """
        if case_number:
            from app.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM cases WHERE case_number = ?", (case_number,)
                ).fetchone()
                if row:
                    raise ValueError(f"案件编号 '{case_number}' 已存在")
        return Case.create(name=name, case_number=case_number, description=description)

    @staticmethod
    def get_case(case_id: int) -> Optional[dict]:
        """获取案件详情."""
        return Case.get_by_id(case_id)

    @staticmethod
    def list_cases(page: int = 1, size: int = 20, search: str = "") -> dict:
        """获取案件列表."""
        return Case.list(page=page, size=size, search=search)

    @staticmethod
    def update_case(case_id: int, name: Optional[str] = None,
                    description: Optional[str] = None,
                    status: Optional[str] = None) -> Optional[dict]:
        """更新案件."""
        return Case.update(case_id, name=name, description=description, status=status)

    @staticmethod
    def delete_case(case_id: int) -> bool:
        """删除案件."""
        return Case.delete(case_id)
