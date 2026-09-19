from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import (
    create_access_token,
    get_current_user_from_header,
)
from db.database import get_password_hash, get_session, verify_password
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


class RegisterRequest(BaseModel):
    username: str
    password: str


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



@router.post("/register", response_model=LoginResponse)
async def register(request: RegisterRequest):
    """用户注册(账号仅用于登录识别,不再承载任何业务数据归属)"""
    with get_session() as session:
        # 检查用户名是否已存在
        existing_user = (
            session.query(User).filter(User.username == request.username).first()
        )
        if existing_user:
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 创建新用户(用户只用于登录)
        new_user = User(
            username=request.username,
            password=get_password_hash(request.password),
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        # 创建 token
        token_data = {
            "sub": str(new_user.id),
            "username": new_user.username,
        }
        access_token = create_access_token(token_data)

        return LoginResponse(access_token=access_token, user=new_user.to_dict())



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

