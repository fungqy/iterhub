"""节假日数据服务模块

提供统一的节假日数据获取和缓存功能，被 dateattr.py 和 holidays.py 共用
"""

import json
import logging
import threading
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger("Holiday")

# 节假日数据缓存
# {year: {"holidays": set(), "workdays": set()}}
_holidays_cache: dict[int, dict[str, set[str]]] = {}
_cache_lock = threading.Lock()


def _parse_holidays(data: dict) -> tuple[set[str], set[str]]:
    """从 CDN/本地 JSON 的 days 列表拆分节假日与工作日。

    Returns:
        (holidays, workdays): 分别为休息日与上班日（补班）的 "YYYY-MM-DD" 集合
    """
    holidays: set[str] = set()
    workdays: set[str] = set()
    for day in data.get("days", []):
        day_date = day["date"]
        if day.get("isOffDay", False):
            holidays.add(day_date)
        else:
            workdays.add(day_date)
    return holidays, workdays


def _local_holidays_path(year: int) -> Path:
    """本地节假日 JSON 文件路径: backend/src/config/holiday-{year}.json"""
    return Path(__file__).resolve().parents[1] / "config" / f"holiday-{year}.json"


def _load_holidays_from_local(year: int) -> dict[str, set[str]] | None:
    """若 src/config 下存在 holiday-{year}.json 则直接解析,否则返回 None。"""
    path = _local_holidays_path(year)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"解析本地节假日文件失败 {path}: {e}")
        return None

    holidays, workdays = _parse_holidays(data)
    _holidays_cache[year] = {"holidays": holidays, "workdays": workdays}
    logger.info(
        f"从本地文件加载 {year} 年节假日数据: {len(holidays)} 个节假日, {len(workdays)} 个工作日"
    )
    return _holidays_cache[year]


def _fetch_holidays_from_url(year: int) -> dict[str, set[str]] | None:
    """从URL获取指定年份的节假日数据并缓存

    假设 _cache_lock 已持有，避免与并发抓取者竞争。
    """
    url = f"https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            holidays, workdays = _parse_holidays(data)

            _holidays_cache[year] = {"holidays": holidays, "workdays": workdays}
            logger.info(
                f"成功从URL获取 {year} 年节假日数据: {len(holidays)} 个节假日, {len(workdays)} 个工作日"
            )
            return _holidays_cache[year]
        else:
            logger.warning(f"获取节假日数据失败: HTTP {resp.status_code}")
            return None
    except requests.RequestException as e:
        logger.error(f"获取节假日数据失败: {e}")
        return None


def _get_year_holiday(year: int) -> dict[str, set[str]] | None:
    """获取指定年份的节假日数据（优先使用缓存）

    内部用 _cache_lock 串行化抓取动作：第一个进入的线程发起 HTTP，
    其余线程在锁上阻塞；首个线程写完缓存释放锁后，其余线程命中缓存直接返回。
    """
    # 快路径：未持锁读缓存，绝大多数调用应在此处返回
    if year in _holidays_cache:
        return _holidays_cache[year]

    with _cache_lock:
        # 持锁后再次确认，防止与并发写入竞争
        if year in _holidays_cache:
            return _holidays_cache[year]

        # 优先使用本地配置文件(src/config/holiday-{year}.json),未命中再回退 CDN
        holiday_data = _load_holidays_from_local(year)
        if holiday_data:
            return holiday_data

        holiday_data = _fetch_holidays_from_url(year)
        if holiday_data:
            return holiday_data

        # URL 获取失败时尝试任何已有缓存
        if year in _holidays_cache:
            return _holidays_cache[year]

        return None


def check_isworkday(d: date) -> bool:
    """判断指定日期是否为工作日

    Args:
        d: 日期

    Returns:
        bool: 是否为工作日
    """

    # 加载节假日数据
    holiday_data = _get_year_holiday(d.year)

    if holiday_data is None:
        return True

    holidays = holiday_data["holidays"]
    workdays = holiday_data["workdays"]

    weekday = d.weekday() + 1

    # 判断是否是假日或补班日
    date_str = d.strftime("%Y-%m-%d")
    isholiday = date_str in holidays
    iscompday = date_str in workdays

    # 判断是否为工作日
    return (weekday <= 5 and not isholiday) or iscompday


def get_year_workdays(year: int) -> list[dict]:
    """获取指定年份的工作日数据，用于写入数据库

    未获取到该年节假日数据时直接返回空列表——**不做兜底**，
    避免把"全年都当工作日"的假数据写入 sys_workday。

    Returns:
        list: 包含 year, datestr 的字典列表,无可用节假日数据时为空列表
    """
    import calendar

    if _get_year_holiday(year) is None:
        logger.error(f"未获取到 {year} 年节假日数据，跳过写入(不做兜底)")
        return []

    result = []
    for month in range(1, 13):
        _, days_in_month = calendar.monthrange(year, month)

        for day in range(1, days_in_month + 1):
            current_date = date(year, month, day)
            isworkday = check_isworkday(current_date)

            if isworkday:
                result.append(
                    {
                        "year": year,
                        "datestr": current_date.strftime("%Y-%m-%d"),
                    }
                )

    return result
