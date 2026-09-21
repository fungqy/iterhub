import logging
import os
from contextlib import contextmanager

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from db.config import get_connect_args, get_dsn

load_dotenv()

logger = logging.getLogger(__name__)


def validate_db_config(config):
    """验证数据库配置是否完整"""
    required_fields = ["host", "user", "password", "database"]
    missing_fields = [field for field in required_fields if not config.get(field)]
    if missing_fields:
        raise ValueError(
            f"数据库配置不完整，缺少以下必填字段: {', '.join(missing_fields)}\n"
            f"请在 backend/.env 文件中配置 MSQL_DSN（完整 SQLAlchemy URL）:\n"
            f"  MSQL_DSN=mysql+pymysql://user:password@host:port/database\n"
            f"示例:.env文件内容:\n"
            f"  MSQL_DSN=mysql+pymysql://your_user:your_password@localhost:3306/your_database"
        )


def get_engine():
    """创建数据库引擎(带连接池 + 探活 + 回收 + 建连超时)"""
    return create_engine(
        get_dsn(),
        connect_args=get_connect_args(),
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,
        future=True,
    )


# 全局 Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


@contextmanager
def get_session():
    """获取数据库会话(上下文管理器,退出时自动关闭)"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# 默认管理员口令的环境变量名。注册接口已下线,该口令是系统唯一的初始登录入口。
_ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"


def create_default_user():
    """创建默认登录账号（如果不存在）。

    已取消用户身份/管理员概念:所有登录用户共享全部数据与功能,故这里只保证
    系统始终有一个可登录的账号,不再设置任何角色标记。

    口令来源:`ADMIN_PASSWORD` 环境变量。
    - 账号已存在:不覆盖口令,直接返回(改口令请走数据库/运维流程)
    - 账号不存在且未设置该变量:**抛错拒绝启动**。注册接口已下线,
      此时系统将无人可登录;静默跳过只会把问题推迟到「登录不进去」才暴露
    """
    from db.models import User

    with get_session() as session:
        user = session.query(User).filter(User.username == "admin").first()
        if user:
            logger.info("默认账号已存在")
            return

        password = os.getenv(_ADMIN_PASSWORD_ENV)
        if not password:
            raise RuntimeError(
                "admin 账号不存在且未设置环境变量 "
                f"{_ADMIN_PASSWORD_ENV},系统将无人可登录。"
                "请在 backend/.env 中设置一个强口令(建议 ≥16 位随机串)后重启。"
            )

        session.add(User(username="admin", password=get_password_hash(password)))
        session.commit()
        # 口令绝不写日志
        logger.info("默认账号 admin 已创建(口令取自环境变量 %s)", _ADMIN_PASSWORD_ENV)
