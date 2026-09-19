"""进程内简易限流器(基于线程锁 + 字典)。

适用场景:登录防爆破、上传频控等无需跨进程共享的低 QPS 场景。
若未来要横向扩展或多 worker,可换成 Redis 实现,接口签名保持不变。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    failures: int = 0
    first_failure_at: float = 0.0
    locked_until: float = 0.0


class RateLimiter:
    """滑动失败次数限流:连续 N 次失败后锁定 T 秒。"""

    def __init__(
        self,
        max_failures: int = 5,
        lockout_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _bucket(self, key: str) -> _Bucket:
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket()
            self._buckets[key] = b
        return b

    def check(self, key: str) -> tuple[bool, int]:
        """检查 key 是否被锁。返回 (是否放行, 剩余锁定秒数)。"""
        now = self._clock()
        with self._lock:
            b = self._bucket(key)
            if b.locked_until > now:
                return False, int(b.locked_until - now)
            # 锁定过期后,清空计数
            if b.locked_until and b.locked_until <= now:
                b.failures = 0
                b.first_failure_at = 0.0
                b.locked_until = 0.0
            return True, 0

    def record_failure(self, key: str) -> tuple[bool, int]:
        """记录一次失败。返回 (是否触发锁定, 锁定秒数)。"""
        now = self._clock()
        with self._lock:
            b = self._bucket(key)
            if b.first_failure_at == 0.0:
                b.first_failure_at = now
            b.failures += 1
            if b.failures >= self.max_failures:
                b.locked_until = now + self.lockout_seconds
                return True, self.lockout_seconds
            return False, 0

    def record_success(self, key: str) -> None:
        """成功时清空计数。"""
        with self._lock:
            b = self._buckets.get(key)
            if b is not None:
                b.failures = 0
                b.first_failure_at = 0.0
                b.locked_until = 0.0


# 进程内全局单例:登录防爆破
login_limiter = RateLimiter(max_failures=5, lockout_seconds=300)
