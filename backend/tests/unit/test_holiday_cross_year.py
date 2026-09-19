"""update_holidays_table 跨年写入行为"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_engine(monkeypatch):
    """让 DbOperator.get_engine() 返回一个 MagicMock,可以在测试里检查 SQL。"""
    engine = MagicMock()
    monkeypatch.setattr(
        "db.dboperator.DbOperator.get_engine", staticmethod(lambda: engine)
    )
    return engine


def test_writes_both_current_and_next_year(mock_engine, monkeypatch):
    """关键回归:必须同时检查并写入 current_year + next_year,避免 12/31 跨年空窗。"""

    # 让 _year_exists 始终返回 False,迫使 _populate_year 被调用
    with patch("holiday.holidays._year_exists", return_value=False), patch(
        "holiday.holidays._populate_year"
    ) as mock_pop, patch("holiday.holidays.date") as mock_date:
        mock_date.today.return_value = date(2026, 12, 31)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        from holiday.holidays import update_holidays_table
        update_holidays_table()

    # 两次调用,分别针对 2026 和 2027
    called_years = {c.args[1] for c in mock_pop.call_args_list}
    assert called_years == {2026, 2027}


def test_skips_years_already_present(mock_engine, monkeypatch):
    """已存在的年份不应重复抓取/写入。"""
    with patch("holiday.holidays._year_exists", return_value=True), patch(
        "holiday.holidays._populate_year"
    ) as mock_pop:
        from holiday.holidays import update_holidays_table
        update_holidays_table()

    mock_pop.assert_not_called()
