"""Sprint 展示屏蔽服务:SQL 片段生成、降级行为与展示层过滤。

不依赖真实 MySQL —— _format_sprints 内部的 DbOperator 引擎用 mock 替换,
与服务层自身的表可用性探针解耦。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from api.services import sprint_filter as svc


@pytest.fixture
def table_available(monkeypatch):
    """屏蔽表已就绪。"""
    monkeypatch.setattr(svc, "_table_ok", True)
    yield


@pytest.fixture
def table_missing(monkeypatch):
    """屏蔽表不可用,并锁住重探窗口,避免用例真的去连库。"""
    monkeypatch.setattr(svc, "_table_ok", False)
    monkeypatch.setattr(svc, "_next_probe_at", time.monotonic() + 9999)
    yield


class TestExcludeSql:
    def test_generates_not_exists_clause(self, table_available):
        clause = svc.exclude_sql("s")
        assert "NOT EXISTS" in clause
        assert "rdm_sprint_exclude" in clause
        assert "e.sprint_id = s.sprint_id" in clause
        # 片段要能直接拼在既有 WHERE 之后,故以 AND 起头
        assert clause.lstrip().startswith("AND")

    def test_uses_caller_alias(self, table_available):
        """必须按调用方传入的别名关联,否则拼进子查询会关联错表。"""
        assert "x.sprint_id" in svc.exclude_sql("x")

    def test_degrades_to_empty_when_table_missing(self, table_missing):
        """表不可用时退化成空串,原 SQL 照常执行(不能整条查询失败)。"""
        assert svc.exclude_sql("s") == ""


class TestDegrade:
    def test_excluded_ids_empty(self, table_missing):
        assert svc.excluded_sprint_ids() == set()

    def test_list_empty(self, table_missing):
        assert svc.list_excluded() == []


def _patch_engine(monkeypatch, done_ids):
    """把 _format_sprints 内部取「有数据 sprint」的引擎换成 mock。"""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.execute.return_value = [(i,) for i in done_ids]

    engine = MagicMock()
    engine.connect.return_value = conn
    monkeypatch.setattr("db.dboperator.DbOperator.get_engine", lambda: engine)


class TestFormatSprints:
    """_format_sprints 是报表时间轴(A)与作业页手动执行(D)的共同收口点。"""

    ROWS = [
        (1, "sp1", None, None, None, "closed"),
        (2, "sp2", None, None, None, "closed"),
        (3, "sp3", None, None, None, "closed"),
    ]

    def test_filters_excluded_sprint(self, monkeypatch):
        from api.routes import reports

        _patch_engine(monkeypatch, done_ids=[1, 2, 3])
        monkeypatch.setattr(reports, "excluded_sprint_ids", lambda: {"2"})

        out = reports._format_sprints(self.ROWS)
        assert [x["sprint_id"] for x in out] == [1, 3]

    def test_keeps_all_when_no_exclusion(self, monkeypatch):
        from api.routes import reports

        _patch_engine(monkeypatch, done_ids=[1])
        monkeypatch.setattr(reports, "excluded_sprint_ids", lambda: set())

        out = reports._format_sprints(self.ROWS)
        assert [x["sprint_id"] for x in out] == [1, 2, 3]
        assert [x["has_report_data"] for x in out] == [True, False, False]

    def test_keeps_all_when_table_missing(self, monkeypatch, table_missing):
        """降级路径:表不可用时展示层不得丢掉任何 Sprint。

        刻意不 patch excluded_sprint_ids —— 走服务层真实的降级分支。
        """
        from api.routes import reports

        _patch_engine(monkeypatch, done_ids=[])
        out = reports._format_sprints(self.ROWS)
        assert [x["sprint_id"] for x in out] == [1, 2, 3]
