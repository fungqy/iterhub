"""`_workday_count` 的区间语义与空值口径(迭代概览「迭代时长」卡的两套口径之一)。

为什么值得单测:卡片上「实际自然日跨度 + 工作日数」必须**同区间**,而区间来自两个
不同的字段对(计划 startdate→enddate、实际 activated_date→complete_date)。
这里把口径钉成三条不变量:

  1. 参数一律截到「天」再查 —— 两列的 datetime 时分不同(激活 09:30 / 完成 18:00),
     不截断会让 BETWEEN 的边界日时松时紧;
  2. 缺任一端点、或区间倒挂 → None(「无区间可算」),**不是 0** ——
     0 会被前端读成「跑了 0 个工作日」,与「还没跑完」含义相反;
  3. 区间存在但恰好没有工作日(如整段落在长假) → 0,是真实值。

不打 HTTP、不连库:会话是假的,只认这一句 COUNT。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from api.routes import reports as rp


class _FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """只接 sys_workday 的 COUNT;记录每次 SQL 与参数供断言。"""

    def __init__(self, count: int):
        self.count = count
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):  # noqa: ANN001
        sql = str(stmt)
        assert "sys_workday" in sql and "COUNT(*)" in sql, f"未预期的查询: {sql[:120]}"
        self.calls.append((sql, dict(params or {})))
        return _FakeResult([(self.count,)])


def test_returns_count_and_passes_date_only_params():
    session = _FakeSession(11)
    assert rp._workday_count(session, date(2026, 6, 1), date(2026, 6, 15)) == 11
    assert session.calls[0][1] == {"start": "2026-06-01", "end": "2026-06-15"}


def test_datetime_endpoints_are_truncated_to_day():
    """激活 / 完成时刻带时分,必须截到天 —— 否则边界日会被 BETWEEN 漏掉。"""
    session = _FakeSession(3)
    rp._workday_count(session, datetime(2026, 6, 1, 9, 30), datetime(2026, 6, 3, 18, 45))
    assert session.calls[0][1] == {"start": "2026-06-01", "end": "2026-06-03"}


def test_none_when_either_endpoint_missing():
    """迭代未完结时没有 complete_date:整组为 None,且不应发出查询。"""
    for start, end in ((None, date(2026, 6, 1)), (date(2026, 6, 1), None), (None, None)):
        session = _FakeSession(5)
        assert rp._workday_count(session, start, end) is None
        assert session.calls == []


def test_none_when_reversed():
    """倒挂区间(完成早于激活,脏数据)同样返回 None,不发查询。"""
    session = _FakeSession(5)
    assert rp._workday_count(session, date(2026, 6, 15), date(2026, 6, 1)) is None
    assert session.calls == []


def test_zero_is_a_real_value():
    """区间有效但没有工作日 → 0,与 None(无区间)区分开。"""
    assert rp._workday_count(_FakeSession(0), date(2026, 10, 1), date(2026, 10, 7)) == 0
