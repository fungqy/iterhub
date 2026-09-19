"""DateAttr 的纯日期工具函数"""

from datetime import date

from util.dateattr import DateAttr


def test_weekday_starts_at_one():
    # 2026-06-01 是周一
    da = DateAttr(date(2026, 6, 1))
    assert da.weekday == 1
    # 2026-06-06 是周六
    da_sat = DateAttr(date(2026, 6, 6))
    assert da_sat.weekday == 6


def test_firstday_lastday_of_week():
    # 2026-06-03 是周三
    da = DateAttr(date(2026, 6, 3))
    assert da.firstday_of_week == date(2026, 6, 1)
    assert da.lastday_of_week == date(2026, 6, 7)


def test_firstday_for_sunday():
    # 2026-06-07 是周日
    da = DateAttr(date(2026, 6, 7))
    assert da.firstday_of_week == date(2026, 6, 1)
    assert da.lastday_of_week == date(2026, 6, 7)
