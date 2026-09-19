import logging
from datetime import date

import pandas as pd
from sqlalchemy import text

from db.dboperator import DbOperator

from .holiday_service import get_year_workdays

logger = logging.getLogger("Holiday")


def _year_exists(engine, year: int) -> bool:
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM sys_workday WHERE year = :year"),
            {"year": year},
        ).scalar()
    return bool(count and count > 0)


def _populate_year(engine, year: int) -> None:
    """按年份抓取并写入工作日数据(单年原子操作)"""
    logger.info(f"正在处理 {year} 年的工作日数据...")
    result = get_year_workdays(year)
    if not result:
        logger.error(f"获取 {year} 年数据失败，跳过")
        return
    logger.info(f"获取到 {len(result)} 条 {year} 年数据")

    holidays_df = pd.DataFrame(result)
    # if_exists="append" 配前置去重检查:同一年不会重复写入
    holidays_df.to_sql("sys_workday", con=engine, if_exists="append", index=False)
    logger.info(f"{year} 年数据写入完成")


def update_holidays_table():
    """更新工作日数据库表,确保**当前年与下一年**都已存在。

    为什么是两年:
    - 12/31 晚跑会立即跨年,下一年无数据导致 1/1 提醒链路缺底层数据
    - 节假日 CDN 通常在年末才会发布下一年数据,所以 1 月初可能要补一次
    """
    engine = DbOperator.get_engine()
    current_year = date.today().year
    next_year = current_year + 1

    for year in (current_year, next_year):
        if _year_exists(engine, year):
            logger.info(f"{year} 年的工作日数据已存在，跳过")
            continue
        _populate_year(engine, year)


def main():
    """主函数"""
    try:
        update_holidays_table()
    except Exception as err:
        logger.error(f"脚本执行出错: {err}")


if __name__ == "__main__":
    main()
