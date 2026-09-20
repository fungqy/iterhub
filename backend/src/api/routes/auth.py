from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import (
    create_access_token,
    get_current_user_from_header,
)
from db.database import get_session, verify_password
from db.models import User
from util.ratelimit import login_limiter

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: int
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, body: LoginRequest):
    """用户登录(带失败计数防爆破)"""
    key = body.username.lower()

    allowed, retry_after = login_limiter.check(key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多,请 {retry_after} 秒后再试",
            headers={"Retry-After": str(retry_after)},
        )

    with get_session() as session:
        user = session.query(User).filter(User.username == body.username).first()
        if not user or not verify_password(body.password, str(user.password)):
            locked, _ = login_limiter.record_failure(key)
            if locked:
                raise HTTPException(
                    status_code=429,
                    detail="登录失败次数过多,账号已临时锁定 5 分钟",
                    headers={"Retry-After": "300"},
                )
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        login_limiter.record_success(key)

        # 创建 token
        token_data = {
            "sub": str(user.id),
            "username": user.username,
        }
        access_token = create_access_token(token_data)

        return LoginResponse(access_token=access_token, user=user.to_dict())


# ⚠ 自助注册接口已下线(安全基线收紧):账号只能由初始化/运维流程创建。
#   本系统没有角色模型 —— 任何登录用户都能读写全部项目配置,
#   因此「开放注册」实质等于「把全部数据开放给匿名者」。
#   若将来要重新开放,必须同时补:口令强度校验 + 服务端限流 + 角色划分。


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user_from_header),
):
    """获取当前用户信息"""
    with get_session() as session:
        user_id = int(current_user.get("sub"))  # type: ignore
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user.to_dict()

