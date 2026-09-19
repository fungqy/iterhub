"""节假日服务在并发调用时必须只抓取一次"""

import threading
from datetime import date
from unittest.mock import patch

import pytest

from src.holiday import holiday_service


@pytest.fixture(autouse=True)
def _reset_holiday_cache():
    """每个用例前后都清空 _holidays_cache，确保不会跨用例污染。"""
    holiday_service._holidays_cache.clear()
    yield
    holiday_service._holidays_cache.clear()


def test_concurrent_check_isworkday_only_fetches_once():
    """20 个线程同时调用 check_isworkday，HTTP 应只发生 1 次。

    这是回归测试：修复前因为 TOCTOU，每个线程都会触发一次 CDN 请求。
    """
    fetch_count = {"n": 0}
    fetch_lock = threading.Lock()

    def fake_fetch(year: int):
        with fetch_lock:
            fetch_count["n"] += 1
        # 模拟网络耗时，放大并发窗口让竞争更容易发生
        import time
        time.sleep(0.05)
        # 必须与生产实现一致地把结果写入 _holidays_cache，
        # 否则其他线程会认为缓存未命中而再次调用 fetch。
        holiday_service._holidays_cache[year] = {
            "holidays": {"2026-06-06"},
            "workdays": set(),
        }
        return holiday_service._holidays_cache[year]

    target = date(2026, 6, 6)
    barrier = threading.Barrier(20)
    results: list = []

    def worker():
        barrier.wait()
        results.append(holiday_service.check_isworkday(target))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    # 必须同时短路「本地文件优先」这条分支:src/config/holiday-2026.json 存在时,
    # _get_year_holiday 会直接从本地文件命中并写缓存,根本走不到 CDN,
    # 本用例的 fetch_count 就恒为 0(测不到任何东西)。故显式让本地加载返回 None。
    with patch.object(
        holiday_service, "_load_holidays_from_local", return_value=None
    ), patch.object(holiday_service, "_fetch_holidays_from_url", side_effect=fake_fetch):
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert fetch_count["n"] == 1
    # 所有线程都拿到了正确结果（端午当天被设为 holiday → 非工作日）
    assert all(r is False for r in results)
