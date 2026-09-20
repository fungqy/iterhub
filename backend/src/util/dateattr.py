from datetime import date, datetime, timedelta

from src.holiday import check_isworkday as _check_workday


class DateAttr:
    """日期相关工具类

    ⚠ 传 None 时「今天」在**每次取用时**解析,而不是构造时定格。
    任务模块在 import 期就 new 了实例(`dateattr = DateAttr()`),若构造时定格,
    常驻进程跨周后 firstday_of_week / lastday_of_week 会一直停在启动那一周,
    「本周待完成 / 本周扫描」的判定随之错一整个周期。
    """

    def __init__(self, dt: date | datetime | None = None) -> None:
        self._dt = dt

    @property
    def _date(self):
        # 惰性解析:未显式指定日期时,始终取「当下」的今天
        return self._dt or date.today()

    @property
    def weekday(self):
        return self._date.weekday() + 1

    @property
    def firstday_of_week(self):
        return DateAttr.firstdayofweek(self._date)

    @property
    def lastday_of_week(self):
        return DateAttr.lastdayofweek(self._date)

    @property
    def is_workday(self):
        return _check_workday(self._date)

    @staticmethod
    def firstdayofweek(d: date | None = None):
        # ⚠ 不能用 d=date.today() 作默认值:默认参数在 import 期求值,会永久定格
        d = d or date.today()
        return d - timedelta(days=d.weekday())

    @staticmethod
    def lastdayofweek(d: date | None = None):
        d = d or date.today()
        days_to_go = 6 - d.weekday()
        if days_to_go < 0:
            days_to_go += 7
        return d + timedelta(days=days_to_go)

    # 注:原 remove_timezone / convert_timezone / to_beijing_mysql_datetime 三个静态方法
    # 全仓无调用方,且最后一个与 util/jira.py 的 to_beijing_mysql_datetime 是同一逻辑的
    # 两份实现(jira 那份还额外支持 datetime 入参)—— 已于 2026-09-20 删除,
    # 时间归一统一走 util/jira.py 与 api/services/execution_log.to_naive_beijing。


if __name__ == "__main__":
    dt = DateAttr(date(2026, 5, 9))
    print(dt.is_workday)

    dt2 = DateAttr()
    print(dt2.is_workday)
    print(dt2.firstday_of_week)
