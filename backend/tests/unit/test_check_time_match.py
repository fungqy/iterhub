"""check_time_match 行为校验"""

from datetime import datetime

from api.scheduler import BEIJING_TZ, check_time_match


def _t(h: int, m: int) -> datetime:
    return datetime(2026, 6, 6, h, m, tzinfo=BEIJING_TZ)


def test_exact_match():
    assert check_time_match("09:30", _t(9, 30)) is True


def test_minute_off_by_one():
    assert check_time_match("09:30", _t(9, 31)) is False
    assert check_time_match("09:30", _t(9, 29)) is False


def test_hour_off():
    assert check_time_match("09:30", _t(10, 30)) is False


def test_empty_config_returns_false():
    assert check_time_match("", _t(9, 30)) is False


def test_off_minute_handled():
    """关键回归：09:05 这种"非 0/5 分钟"的时间必须能被识别"""
    assert check_time_match("09:05", _t(9, 5)) is True
    assert check_time_match("09:33", _t(9, 33)) is True
