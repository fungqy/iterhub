"""truncate_table 只接受白名单标识符,防 SQL 注入。"""

import pytest

from db.dboperator import _assert_valid_identifier


@pytest.mark.parametrize("name", [
    "review_records_details",
    "table1",
    "_underscore_start",
    "A_B_C",
])
def test_valid_identifiers(name):
    _assert_valid_identifier(name, "table")  # 不抛


@pytest.mark.parametrize("name", [
    "",
    "123starts_with_digit",
    "drop table x",
    "x;DROP TABLE users",
    "x` OR 1=1",
    "x'union select",
    "x space",
    "x-y",
    "x.y",
    "x" * 65,
])
def test_invalid_identifiers_rejected(name):
    with pytest.raises(ValueError, match="非法的 SQL"):
        _assert_valid_identifier(name, "table")
