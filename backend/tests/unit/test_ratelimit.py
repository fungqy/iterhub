"""登录限流器行为"""

from util.ratelimit import RateLimiter


def test_check_passes_when_no_failures():
    rl = RateLimiter(max_failures=3, lockout_seconds=60)
    allowed, _ = rl.check("alice")
    assert allowed is True


def test_lockout_after_max_failures():
    rl = RateLimiter(max_failures=3, lockout_seconds=60)
    for _ in range(3):
        triggered, _ = rl.record_failure("alice")
    assert triggered is True
    # 第 4 次 check 应当被锁
    allowed, retry = rl.check("alice")
    assert allowed is False
    assert 0 < retry <= 60


def test_success_resets_counter():
    rl = RateLimiter(max_failures=3, lockout_seconds=60)
    rl.record_failure("alice")
    rl.record_failure("alice")
    rl.record_success("alice")
    # 计数清零,再连续 3 次失败仍可触发锁定
    for _ in range(2):
        rl.record_failure("alice")
    triggered, _ = rl.record_failure("alice")
    assert triggered is True


def test_different_keys_isolated():
    rl = RateLimiter(max_failures=2, lockout_seconds=60)
    rl.record_failure("alice")
    rl.record_failure("alice")
    # alice 已锁,bob 不受影响
    allowed, _ = rl.check("bob")
    assert allowed is True
