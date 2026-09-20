import logging
import re
import threading

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from db.config import get_dsn

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)


# 标识符白名单:表名只能包含字母/数字/下划线,且不能以数字开头,
# 长度 1-64。这样既允许 snake_case,又彻底堵死 SQL 注入。
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _assert_valid_identifier(name: str, kind: str) -> None:
    """校验 SQL 标识符,非法直接抛 ValueError。"""
    if not isinstance(name, str) or not _VALID_IDENTIFIER.match(name):
        raise ValueError(
            f"非法的 SQL {kind} 标识符: {name!r}。"
            f"仅允许字母/数字/下划线,且首字符必须为字母或下划线,长度 1-64。"
        )


# 全局共享引擎(懒加载单例)。get_engine() 若每次调用都 create_engine,
# 新引擎的连接池是空的,每条查询都得重连数据库(新建连接要走 TCP+MySQL 握手);
# 单例化后所有调用方复用同一个连接池。
_engine = None
_engine_lock = threading.Lock()


class DbOperator:
    """数据库操作类"""

    @staticmethod
    def get_engine():
        """获取全局数据库引擎(单例,带连接池 + 探活 + 回收)"""
        global _engine
        if _engine is None:
            with _engine_lock:
                if _engine is None:
                    _engine = create_engine(
                        get_dsn(),
                        poolclass=QueuePool,
                        pool_size=10,
                        max_overflow=10,
                        pool_recycle=1800,
                        pool_pre_ping=True,
                        future=True,
                    )
        return _engine

    @staticmethod
    def truncate_table(table_name):
        """清空表数据(只接受白名单标识符,防 SQL 注入)。

        ⚠ 失败时**向上抛**,不再静默吞掉:历史实现只记日志就返回,调用方以为
        清空成功、接着 append,结果「没清掉但写了新的」产生重复数据
        (调用点见 task/report_wiki_data.py)。
        """
        _assert_valid_identifier(table_name, "table")
        with DbOperator.get_engine().begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE `{table_name}`;"))

    @staticmethod
    def exec_sql(sql_query):
        """执行SQL语句(失败向上抛,不静默吞掉)"""
        with DbOperator.get_engine().begin() as conn:
            conn.execute(text(sql_query))
