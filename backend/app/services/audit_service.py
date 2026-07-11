"""审计日志服务 — AI 调用记录查询与管理."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from app.models.ai_audit_log import AiAuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """AI 调用审计日志服务.

    封装审计日志的写入与查询，提供分页、筛选、统计功能.
    """

    @staticmethod
    def log_call(
        host_id: Optional[int] = None,
        host_name: str = "",
        profile_id: Optional[int] = None,
        profile_name: str = "",
        model_name: str = "",
        status: str = "success",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        masked_mode: int = 0,
        prompt: str = "",
        response: str = "",
        error_message: Optional[str] = None,
        ip_address: str = "",
        user_id: Optional[int] = None,
    ) -> dict:
        """记录一次 AI 调用审计日志.

        Args:
            host_id: 主机 ID.
            host_name: 主机名.
            profile_id: AI 配置 Profile ID.
            profile_name: Profile 名称.
            model_name: 模型名称.
            status: 调用状态（success/failed/cancelled）.
            prompt_tokens: 输入 token 数.
            completion_tokens: 输出 token 数.
            total_tokens: 总 token 数.
            latency_ms: 调用延迟（毫秒）.
            masked_mode: 是否脱敏模式.
            prompt: 用户提示词（完整原文）.
            response: AI 响应内容（完整原文）.
            error_message: 错误信息.
            ip_address: 调用方 IP.
            user_id: 用户 ID.

        Returns:
            创建的审计日志记录字典.
        """
        logger.info(
            "AuditService.log_call: ENTER host=%d, model=%s, status=%s, tokens=(%d,%d,%d), latency=%dms, masked=%d",
            host_id or 0,
            model_name,
            status,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            latency_ms,
            masked_mode,
        )
        result = AiAuditLog.create(
            host_id=host_id,
            host_name=host_name,
            profile_id=profile_id,
            profile_name=profile_name,
            model_name=model_name,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            masked_mode=masked_mode,
            prompt=prompt,
            response=response,
            error_message=error_message,
            ip_address=ip_address,
            user_id=user_id,
        )
        logger.info(
            "AuditService.log_call: DONE id=%s, host=%d, model=%s",
            result.get("id") if result else "NONE",
            host_id or 0,
            model_name,
        )
        return result

    @staticmethod
    def query_logs(
        page: int = 1,
        page_size: int = 20,
        host_id: Optional[int] = None,
        status: Optional[str] = None,
        days: int = 30,
    ) -> dict:
        """分页查询审计日志.

        Args:
            page: 页码（从 1 开始）.
            page_size: 每页条数.
            host_id: 按主机 ID 筛选.
            status: 按状态筛选.
            days: 查询最近 N 天的日志.

        Returns:
            {"items": [...], "total": int, "page": int, "page_size": int}
        """
        start_date: Optional[str] = None
        if days > 0:
            start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        return AiAuditLog.list_all(
            page=page,
            page_size=page_size,
            host_id=host_id,
            status=status,
            start_date=start_date,
        )

    @staticmethod
    def get_detail(log_id: int) -> dict:
        """获取单条审计日志详情.

        Args:
            log_id: 审计日志 ID.

        Returns:
            审计日志字典.

        Raises:
            ValueError: 日志不存在.
        """
        log = AiAuditLog.get_by_id(log_id)
        if not log:
            raise ValueError(f"审计日志 {log_id} 不存在")
        return log

    @staticmethod
    def get_token_stats(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        profile_id: Optional[int] = None,
    ) -> dict:
        """获取 Token 使用统计.

        Returns:
            统计结果字典.
        """
        return AiAuditLog.get_token_stats(
            start_date=start_date,
            end_date=end_date,
            profile_id=profile_id,
        )

    @staticmethod
    def get_token_summary(group_by: str = "daily") -> list[dict]:
        """获取 Token 使用汇总.

        Args:
            group_by: 汇总维度（daily/model/profile）.

        Returns:
            汇总数据列表.
        """
        return AiAuditLog.get_token_summary(group_by=group_by)
