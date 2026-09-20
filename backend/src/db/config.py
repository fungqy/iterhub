"""数据库连接映射（单变量 MSQL_DSN）

后端数据库连接统一收敛为单个环境变量 MSQL_DSN，格式为完整 SQLAlchemy URL，
例如: mysql+pymysql://your_user:your_password@localhost:3306/iterdb

- get_dsn(): 返回原始 DSN 字符串，可直接交给 create_engine 使用。
- get_db_config(): 解析为 {host, port, user, password, database} 字典，供 pymysql.connect 使用。
"""
import os
from urllib.parse import unquote, urlparse

_DSN_ENV = "MSQL_DSN"


def get_dsn() -> str:
    """返回原始 MSQL_DSN；缺失时抛 ValueError（启动即失败，不静默放行）。"""
    dsn = os.getenv(_DSN_ENV)
    if not dsn:
        raise ValueError(
            f"数据库配置缺失: 未设置环境变量 {_DSN_ENV}\n"
            f"请配置 MSQL_DSN（完整 SQLAlchemy URL），例如:\n"
            f"  MSQL_DSN=mysql+pymysql://your_user:your_password@localhost:3306/your_database"
        )
    return dsn


def get_db_config() -> dict:
    """解析 MSQL_DSN 为 pymysql 可用的字段字典。"""
    parsed = urlparse(get_dsn())
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username) if parsed.username else "",
        "password": unquote(parsed.password) if parsed.password else "",
        "database": (parsed.path or "").lstrip("/") or None,
    }
