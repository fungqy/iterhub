import logging
from contextlib import contextmanager

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from db.config import get_dsn

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
    """创建数据库引擎(带连接池 + 探活 + 回收)"""
    return create_engine(
        get_dsn(),
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


def init_database():
    """初始化数据库表结构"""
    from db.models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)


def create_default_user():
    """创建默认登录账号（如果不存在）。

    已取消用户身份/管理员概念:所有登录用户共享全部数据与功能,故这里只保证
    系统始终有一个可登录的账号,不再设置任何角色标记。
    """
    from db.models import User

    with get_session() as session:
        user = session.query(User).filter(User.username == "admin").first()
        if not user:
            # 只有用户不存在时才创建
            user = User(username="admin", password=get_password_hash("admin123"))
            session.add(user)
            session.commit()
            logger.info("默认账号已创建: admin / admin123")
        else:
            logger.info("默认账号已存在")
