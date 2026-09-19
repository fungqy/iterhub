"""共享 pytest fixture

所有测试都不依赖真实 MySQL、JIRA、企微、GitLab、SonarQube。
DB 相关函数通过 mock get_session 注入 MagicMock。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 数据库连接收敛为单变量 MSQL_DSN，db.database 在 import 时会据此创建 SessionLocal
#（惰性引擎，不真正连库）。测试不依赖真实 MySQL（get_session 由 mock_session 替换），
# 这里注入占位 DSN 仅为了让模块在导入期通过配置校验。
os.environ.setdefault(
    "MSQL_DSN", "mysql+pymysql://test:test@localhost:3306/test_iterdb"
)

# 把 src/ 加入 sys.path（与生产代码中 api/scheduler.py、main.py 的写法一致）
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def mock_session(monkeypatch):
    """返回一个 MagicMock 形态的 SQLAlchemy session，并替换全局 get_session。"""
    session = MagicMock(name="MockSession")
    # get_session 现为上下文管理器，with 语句会调用 __enter__；让 __enter__ 返回同一 session
    session.__enter__.return_value = session
    session.__exit__.return_value = False

    def _factory():
        return session

    # 项目内多个模块都从 db.database 懒加载 get_session
    monkeypatch.setattr("db.database.get_session", _factory, raising=False)
    return session


@pytest.fixture(autouse=True)
def reset_scheduler_singleton():
    """每个用例前后都重置 TaskScheduler 单例，确保互不影响。"""
    from api.scheduler import reset_scheduler_for_tests

    reset_scheduler_for_tests()
    yield
    reset_scheduler_for_tests()


@pytest.fixture
def workday_true(monkeypatch):
    """强制 DateAttr.is_workday 为 True，避免周末/节假日影响调度器测试。"""
    monkeypatch.setattr(
        "api.scheduler.DateAttr",
        lambda *a, **kw: type("FakeDA", (), {"is_workday": True})(),
    )


@pytest.fixture
def workday_false(monkeypatch):
    """强制 DateAttr.is_workday 为 False。"""
    monkeypatch.setattr(
        "api.scheduler.DateAttr",
        lambda *a, **kw: type("FakeDA", (), {"is_workday": False})(),
    )
