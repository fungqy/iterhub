"""数据库连接映射（单变量 MSQL_DSN）

后端数据库连接统一收敛为单个环境变量 MSQL_DSN，格式为完整 SQLAlchemy URL，
例如: mysql+pymysql://your_user:your_password@localhost:3306/iterdb

- get_dsn(): 返回原始 DSN 字符串，可直接交给 create_engine 使用。
- get_db_config(): 解析为 {host, port, user, password, database} 字典，供 pymysql.connect 使用。
- get_connect_args(): 返回 create_engine(connect_args=...) 的建连参数（建连超时）。
"""
import os
from urllib.parse import unquote, urlparse

from sqlalchemy.engine import make_url

_DSN_ENV = "MSQL_DSN"

# 单次「建立连接」的超时(秒)。详见 get_connect_args() 说明。
CONNECT_TIMEOUT_SECONDS = 5


def get_dsn() -> str:
    """返回原始 MSQL_DSN；缺失时抛 ValueError（启动即失败，不静默放行）。"""
    dsn = os.getenv(_DSN_ENV)
    if not dsn:
        raise ValueError(
            f"数据库配置缺失: 未设置环境变量 {_DSN_ENV}\n" + 
            f"请配置 MSQL_DSN（完整 SQLAlchemy URL），例如:\n" +
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


def get_connect_args() -> dict[str, int]:
    """返回 create_engine(connect_args=...) 所需的建连参数。

    为什么必须限时:MySQL 默认**没有**建连超时,遇到「主机不可达但不断连」
    (SYN 被防火墙丢弃,而不是 connection refused)时会一直阻塞到内核 TCP 超时
    (Linux 默认约 127s)。而 /health 每 3~5s 就被探针调用一次,每次都在 uvicorn
    的线程池里留下一个卡死的建连 —— 几十次之后默认 40 个线程被吃光,**所有**接口
    (含登录)一起假死。加上超时后,「库连不上」表现为一次快速的 503 / 异常,
    而不是整个服务雪崩。

    ⚠ 只约束「建立连接」这一步,**不设 read/write timeout**:报表聚合与 283MB 的
      文档导入本身就是分钟级长查询,给查询加超时会误杀正常业务。

    非 MySQL 驱动(如本地调试用的 sqlite)不接受该参数,故按驱动返回。
    """
    if make_url(get_dsn()).get_backend_name() == "mysql":
        return {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    return {}
