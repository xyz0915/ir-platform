"""Agent 专属 token 认证依赖（agent token 认证机制）.

设计（deliverables/software-company/agent-token-fix/design.md §3.2 D2）：
- 各 agent 侧接口统一走 ``get_current_agent`` 依赖校验 Bearer token；
- token 存储为 ``sha256(f"{token}:{SECRET_KEY}")`` 的 hex 串（见 agents.token_hash），
  校验时同样计算哈希后 ``WHERE token_hash = ?`` 查库；
- ``assert_host_binding`` 强制 token 归属 host_id 与路径 host_id 一致，防跨主机复用。

状态码约定：401（未提供/无效 token）；403（host_id 绑定不匹配）。
"""

import hashlib
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.models.agent_model import AgentModel

logger = logging.getLogger(__name__)

# auto_error=False：无 Authorization 头时不自动抛 401，交给下方统一处理
_bearer = HTTPBearer(auto_error=False)

_INVALID_TOKEN_DETAIL = "Invalid agent token"


def hash_agent_token(token: str) -> str:
    """计算 agent token 的存储/校验哈希.

    Args:
        token: 明文 agent token（形如 ``atk_xxx``）.

    Returns:
        ``sha256(f"{token}:{SECRET_KEY}")`` 的 64 位 hex 串.
    """
    return hashlib.sha256(f"{token}:{settings.SECRET_KEY}".encode("utf-8")).hexdigest()


async def get_current_agent(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """FastAPI 依赖：从 Authorization: Bearer <token> 解析并校验 agent token.

    Returns:
        ``{"host_id": int, "agent_id": str}``.

    Raises:
        HTTPException: 401 — 无 Bearer / token 无效.
    """
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_hash = hash_agent_token(credentials.credentials)
    agent = AgentModel.get_by_token_hash(token_hash)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"host_id": agent["host_id"], "agent_id": agent["agent_id"]}


def assert_host_binding(agent: dict, host_id: int) -> None:
    """校验 agent token 所属 host_id 与路径 host_id 一致，防 token 跨主机复用.

    Args:
        agent: ``get_current_agent`` 返回的 dict.
        host_id: 路径参数 host_id.

    Raises:
        HTTPException: 403 — host_id 不匹配.
    """
    if int(agent["host_id"]) != int(host_id):
        logger.warning(
            "agent token host 绑定不匹配: token_host_id=%s path_host_id=%s",
            agent.get("host_id"),
            host_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="agent token host 与路径 host_id 不匹配",
        )
