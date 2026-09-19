from datetime import date, datetime, timedelta, timezone

from src.holiday import check_isworkday as _check_workday


class DateAttr:
    """日期相关工具类"""

    def __init__(self, dt: date | datetime | None = None) -> None:
        self._date = dt or date.today()

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
    def firstdayofweek(d=date.today()):
        return d - timedelta(days=d.weekday())

    @staticmethod
    def lastdayofweek(d=date.today()):
        days_to_go = 6 - d.weekday()
        if days_to_go < 0:
            days_to_go += 7
        return d + timedelta(days=days_to_go)

    @staticmethod
    def remove_timezone(datetime_str):
        """ ""移除时间中的时区信息"""
        """if not datetime_str:
            return datetime_str"""
        return datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S.%f%z").strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]

    @staticmethod
    def convert_timezone(datetime_str):
        """将UTC+0时区转换为UTC+8时区"""
        return datetime.strptime(datetime_str[0:19], "%Y-%m-%dT%H:%M:%S") + timedelta(
            hours=8
        )

    @staticmethod
    def to_beijing_mysql_datetime(iso_str: str) -> str:
        # 修正时区格式（+0800 -> +08:00）
        if "+" in iso_str and ":" not in iso_str[-5:]:
            iso_str = f"{iso_str[:-2]}:{iso_str[-2:]}"

        dt = datetime.fromisoformat(
            iso_str
        )  # 此时格式为 "2025-02-28T14:40:58.000+08:00"
        beijing_tz = timezone(timedelta(hours=8))
        beijing_time = dt.astimezone(beijing_tz)
        return beijing_time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    dt = DateAttr(date(2026, 5, 9))
    print(dt.is_workday)

    dt2 = DateAttr()
    print(dt2.is_workday)
    print(dt2.firstday_of_week)
