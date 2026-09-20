import logging
import os
import secrets
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import Header, HTTPException, Query
from jose import JWTError, jwt

load_dotenv()

logger = logging.getLogger("Auth")

# 严禁使用的占位符默认值;一旦发现直接拒绝启动
_JWT_SECRET_PLACEHOLDER = "your-secret-key-change-in-production"


def _resolve_jwt_secret() -> str:
    """解析 JWT 签名密钥。

    策略:
    1. 显式设置 JWT_SECRET_KEY 时,使用其值;若仍为占位符则拒绝启动(防止误部署)
    2. 未设置时自动生成一个随机 key,启动时打 WARNING 提醒:
       重启后所有已签发 token 失效;生产环境请显式设置
    """
    raw = os.getenv("JWT_SECRET_KEY")
    if raw:
        if raw == _JWT_SECRET_PLACEHOLDER:
            raise RuntimeError(
                "JWT_SECRET_KEY 仍使用占位符默认值,生产环境存在严重安全风险。"
                "请在 backend/.env 中设置一个随机字符串(例如: "
                "`python -c \"import secrets; print(secrets.token_urlsafe(64))\"`)。"
            )
        return raw

    generated = secrets.token_urlsafe(64)
    logger.warning(
        "JWT_SECRET_KEY 未设置,本次启动使用自动生成的随机 key。"
        "所有已签发的 token 在重启后将失效,生产环境请在 backend/.env 中显式设置。"
    )
    return generated


SECRET_KEY = _resolve_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict | None:
    """解码访问令牌"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def _bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 头里取出裸 token;不是 Bearer 形态则返回 None。"""
    if authorization and authorization.startswith("Bearer "):
        return authorization.replace("Bearer ", "")
    return None


def get_current_user_from_header(authorization: str = Header(None)) -> dict:
    """FastAPI 依赖:从 Authorization: Bearer <token> 头中提取当前用户。

    统一定义在 api.auth,所有路由文件 import 即可,避免重复实现。
    """
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token已过期或无效")

    return payload


def get_current_user_flexible(
    authorization: str = Header(None),
    t: str = Query(None, description="查询串里的访问令牌,供无法带请求头的场景使用"),
) -> dict:
    """同 get_current_user_from_header,但**额外接受查询串里的 `t=<token>`**。

    为什么必须有这个变体:`<img src="…">` 无法携带 Authorization 头。若改用 fetch
    取二进制再造 objectURL,就丢掉了浏览器原生缓存(ETag/304 复用),而「打开详情要快」
    正是本项目的硬约束 —— 用 URL 传 token 是换取原生缓存的最小代价。

    ⚠ token 出现在 URL 里会被浏览器历史、Referer、访问日志记录。因此**仅限图片/下载
    这类只读接口**使用,不要扩散到任何业务写接口。
    """
    token = _bearer_token(authorization) or t
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token已过期或无效")

    return payload


def get_current_user(token: str):
    """从token获取当前用户信息(非依赖版本)。

    当前无调用方;保留是因为它比两个 Depends 版本更容易在脚本/调试中直接使用。
    若确认长期无人使用,可直接删除。
    """
    payload = decode_access_token(token)
    if not payload:
        return None
    return payload
