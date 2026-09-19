"""parse_time 边界用例"""

from api.scheduler import parse_time


def test_valid_time():
    assert parse_time("09:30") == (9, 30)
    assert parse_time("00:00") == (0, 0)
    assert parse_time("23:59") == (23, 59)


def test_empty_string_returns_zero():
    assert parse_time("") == (0, 0)


def test_none_like_handled():
    # 空字符串路径
    assert parse_time("") == (0, 0)


def test_malformed_returns_zero():
    assert parse_time("bad") == (0, 0)
    assert parse_time("9:xx") == (0, 0)
    assert parse_time("99") == (99, 0)  # 单段数字，被当作 hour


def test_only_hour_portion():
    assert parse_time("7") == (7, 0)


def test_extra_segments_ignored():
    assert parse_time("9:30:45") == (9, 30)
