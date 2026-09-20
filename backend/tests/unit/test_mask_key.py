"""qywx.mask_key 行为校验"""

from util.qywx import mask_key


def test_empty():
    assert mask_key("") == "<empty>"


def test_short_key_returns_stars():
    assert mask_key("abc") == "***"
    assert mask_key("12345678") == "***"


def test_long_key_partial_mask():
    key = "abcd-1234-5678-efgh"
    masked = mask_key(key)
    assert masked.startswith("abcd")
    assert masked.endswith("efgh")
    assert "****" in masked
    # 中间真实字符不应出现在脱敏字符串中
    assert "1234" not in masked
