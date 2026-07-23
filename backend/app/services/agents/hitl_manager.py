"""HITL 审批管理器 — 处理人在回路暂停/恢复。

HITLManager 是一个单例，负责统一管理 HITL 审批请求的生命周期：
- request_approval: 创建 pending 审批记录。
- approve: 批量批准某 run 的所有 pending 记录。
- reject: 批量拒绝某 run 的所有 pending 记录。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HITLManager:
    """HITL 审批管理器 — 请求/批准/拒绝审批。"""

    _instance = None

    def __new__(cls) -> "HITLManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def request_approval(self, run_id: str, agent_name: str,
                         context: dict, user: dict) -> bool:
        """请求人工审批。创建 hitl_approvals 记录（status=pending）。

        Args:
            run_id: 运行 ID。
            agent_name: 请求审批的 Agent 名称。
            context: 上下文（可包含 action、target_json 等）。
            user: 请求用户信息。

        Returns:
            bool: 是否成功创建审批请求。
        """
        from app.models.hitl_approval import HitlApproval
        try:
            HitlApproval.create(
                run_id=run_id,
                action=context.get("action", agent_name),
                requested_by=user.get("id"),
                target_json=context.get("target_json"),
                reason=context.get("reason"),
            )
            logger.info("HITL approval requested: run_id=%s, agent=%s", run_id, agent_name)
            return True
        except Exception as exc:
            logger.error("HITL approval request failed: %s", exc)
            return False

    def approve(self, run_id: str, user: dict) -> bool:
        """批准审批。标记某 run 下所有 pending 记录为 approved。

        Args:
            run_id: 运行 ID。
            user: 审批用户信息。

        Returns:
            bool: 是否成功批准。
        """
        from app.models.hitl_approval import HitlApproval
        try:
            approvals = HitlApproval.list_by_run(run_id)
            count = 0
            for ap in approvals:
                if ap.get("status") == HitlApproval.STATUS_PENDING:
                    HitlApproval.update_status(
                        ap["id"],
                        status=HitlApproval.STATUS_APPROVED,
                        decided_by=user.get("id"),
                    )
                    count += 1
            logger.info("HITL approvals approved: run_id=%s, count=%d", run_id, count)
            return True
        except Exception as exc:
            logger.error("HITL approve failed: %s", exc)
            return False

    def reject(self, run_id: str, user: dict, reason: Optional[str] = None) -> bool:
        """拒绝审批。标记某 run 下所有 pending 记录为 rejected。

        Args:
            run_id: 运行 ID。
            user: 审批用户信息。
            reason: 拒绝原因。

        Returns:
            bool: 是否成功拒绝。
        """
        from app.models.hitl_approval import HitlApproval
        try:
            approvals = HitlApproval.list_by_run(run_id)
            count = 0
            for ap in approvals:
                if ap.get("status") == HitlApproval.STATUS_PENDING:
                    HitlApproval.update_status(
                        ap["id"],
                        status=HitlApproval.STATUS_REJECTED,
                        decided_by=user.get("id"),
                        reason=reason,
                    )
                    count += 1
            logger.info("HITL approvals rejected: run_id=%s, count=%d", run_id, count)
            return True
        except Exception as exc:
            logger.error("HITL reject failed: %s", exc)
            return False


# 模块级单例
hitl_manager = HITLManager()
