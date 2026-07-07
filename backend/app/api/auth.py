"""认证接口 — 登录、获取当前用户."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.services.auth_service import (
    authenticate_user,
    create_token,
    get_current_user,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    """登录请求模型."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应模型."""
    token: str
    user: dict


@router.post("/login")
def login(request: LoginRequest):
    """用户登录，返回 JWT Token."""
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_token(user)
    return {
        "code": 0,
        "data": {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user.get("role", "admin"),
            },
        },
        "message": "success",
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息."""
    return {
        "code": 0,
        "data": {
            "id": current_user["id"],
            "username": current_user["username"],
            "role": current_user.get("role", "admin"),
        },
        "message": "success",
    }
