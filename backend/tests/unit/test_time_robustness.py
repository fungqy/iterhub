"""时间健壮性回归:DateAttr 不得定格「今天」、aware/naive 必须显式归一。

背景(两份缺陷):
1. `DateAttr` 原以 `date.today()` 作默认参数/构造即取值,而任务模块在 import 期
   就 new 了实例 ⇒ 常驻进程跨周后 firstday/lastday_of_week 永远停在启动那一周;
2. `TaskExecutionLog` 的时间列无时区,却写入 aware 值、又用 aware 边界过滤,
   正确性只能依赖驱动隐式丢 tzinfo。现统一经 to_naive_beijing 显式归一。
"""

from __future__ import annotations

import datetime as _dt
import importlib

from api.services.execution_log import to_naive_beijing


class _FakeDate(_dt.date):
    """可控的 date:today() 返回 holder 里的值。"""

    holder = {"today": _dt.date(2026, 6, 3)}  # 周三

    @classmethod
    def today(cls):
        return cls.holder["today"]


def test_dateattr_does_not_freeze_today(monkeypatch):
    """跨周后同一个 DateAttr 实例必须给出新一周的边界。"""
    mod = importlib.import_module("util.dateattr")
    monkeypatch.setattr(mod, "date", _FakeDate)
    _FakeDate.holder["today"] = _dt.date(2026, 6, 3)  # 周三

    da = mod.DateAttr()  # 等价于任务模块 import 期构造的那一个
    assert da.firstday_of_week == _dt.date(2026, 6, 1)
    assert da.lastday_of_week == _dt.date(2026, 6, 7)

    _FakeDate.holder["today"] = _dt.date(2026, 6, 10)  # 下一周的周三
    assert da.firstday_of_week == _dt.date(2026, 6, 8)
    assert da.lastday_of_week == _dt.date(2026, 6, 14)


def test_dateattr_static_defaults_are_not_frozen(monkeypatch):
    """静态方法不带 d 时同样取「当下」,不能是 import 期求值的默认参数。"""
    mod = importlib.import_module("util.dateattr")
    monkeypatch.setattr(mod, "date", _FakeDate)
    _FakeDate.holder["today"] = _dt.date(2026, 6, 3)

    assert mod.DateAttr.firstdayofweek() == _dt.date(2026, 6, 1)
    _FakeDate.holder["today"] = _dt.date(2026, 6, 10)
    assert mod.DateAttr.firstdayofweek() == _dt.date(2026, 6, 8)


def test_to_naive_beijing_converts_aware():
    aware_utc = _dt.datetime(2026, 6, 1, 0, 0, tzinfo=_dt.timezone.utc)
    # UTC 00:00 ⇒ 北京时间 08:00,且不带 tzinfo
    converted = to_naive_beijing(aware_utc)
    assert converted == _dt.datetime(2026, 6, 1, 8, 0)
    assert converted.tzinfo is None


def test_to_naive_beijing_keeps_naive_untouched():
    naive = _dt.datetime(2026, 6, 1, 9, 30)
    assert to_naive_beijing(naive) == naive
