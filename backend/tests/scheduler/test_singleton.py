"""get_scheduler() 应该是线程安全的单例"""

import threading

from api.scheduler import TaskScheduler, get_scheduler


def test_returns_same_instance(workday_true):
    a = get_scheduler()
    b = get_scheduler()
    assert a is b
    assert isinstance(a, TaskScheduler)


def test_thread_safe_lazy_init(workday_true):
    """50 个线程同时调用 get_scheduler，应该只构造 1 个 TaskScheduler。"""
    instances: list = []
    barrier = threading.Barrier(50)

    def grab():
        barrier.wait()
        instances.append(get_scheduler())

    threads = [threading.Thread(target=grab) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 50
    # 所有线程应该拿到的都是同一个对象
    assert all(inst is instances[0] for inst in instances)
