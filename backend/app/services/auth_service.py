"""认证服务 — JWT 生成与验证、密码哈希、依赖注入."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    """对密码进行哈希处理.

    Args:
        password: 明文密码.

    Returns:
        哈希后的密码字符串.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否匹配.

    Args:
        plain_password: 明文密码.
        hashed_password: 哈希密码.

    Returns:
        是否匹配.
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_token(user: dict) -> str:
    """生成 JWT Token.

    Args:
        user: 用户信息字典，包含 id, username, role.

    Returns:
        JWT Token 字符串.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.TOKEN_EXPIRE_HOURS)
    payload = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user.get("role", "admin"),
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT Token.

    Args:
        token: JWT Token 字符串.

    Returns:
        解码后的 payload 字典，验证失败返回 None.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as exc:
        logger.warning("Token verification failed: %s", exc)
        return None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """验证用户名密码.

    Args:
        username: 用户名.
        password: 明文密码.

    Returns:
        用户字典（验证成功）或 None（验证失败）.
    """
    user = User.get_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI 依赖注入：从 Token 获取当前用户.

    Args:
        token: JWT Token（从 Authorization Header 提取）.

    Returns:
        用户字典.

    Raises:
        HTTPException: Token 无效或用户不存在时抛出 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    user_id = payload.get("user_id")
    if user_id is None:
        raise credentials_exception
    user = User.get_by_id(user_id)
    if user is None:
        raise credentials_exception
    return user
