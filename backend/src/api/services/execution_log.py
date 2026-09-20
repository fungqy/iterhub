"""任务执行日志服务

负责把自动/手动任务执行状态写入 TaskExecutionLog。
原为 api/scheduler.py 的叶子函数,现下沉到服务层,由 api/scheduler.py re-export。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("Scheduler")

# 北京时区,与调度器保持一致
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_beijing() -> datetime:
    """返回当前北京时间（带时区信息）"""
    return datetime.now(BEIJING_TZ)


def to_naive_beijing(dt: datetime) -> datetime:
    """把时间归一到「北京时间 naive」。

    ⚠ 库里 DATETIME 列不带时区:直接写 aware 值,最终存进去的是哪个墙钟,
    取决于驱动是否隐式丢 tzinfo —— 语义不确定。显式转换后,「写入」与
    「按日期过滤」两端都确定为北京时间墙钟。
    已是 naive 的值原样返回(调用方已按北京时间给出)。
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(BEIJING_TZ).replace(tzinfo=None)


def record_execution(
    project_config_id: int,
    task_type: str,
    scheduled_time: datetime,
    status: str,
    error_message: str = "",
    task_exec_type: str = "automatic",
) -> int | None:
    """记录任务执行日志,返回新记录 id(供后续按 id 流转更新状态)"""
    from db.database import get_session
    from db.models import TaskExecutionLog

    with get_session() as session:
        try:
            log = TaskExecutionLog(
                project_config_id=project_config_id,
                task_type=task_type,
                scheduled_time=to_naive_beijing(scheduled_time),
                executed_at=to_naive_beijing(now_beijing()),
                status=status,
                error_message=error_message,
                task_exec_type=task_exec_type,
            )
            session.add(log)
            session.flush()  # 刷新以拿到自增 id,整个事务随 commit 提交
            session.commit()
            return log.id
        except Exception as e:
            session.rollback()
            logger.error(f"记录执行日志失败: {e}")
            return None


def update_execution(log_id: int, status: str, error_message: str = "") -> None:
    """按 id 更新已有执行日志的状态(用于将同一执行的状态在原记录上流转)"""
    from db.database import get_session
    from db.models import TaskExecutionLog

    with get_session() as session:
        try:
            log = session.get(TaskExecutionLog, log_id)
            if log is None:
                logger.warning(f"更新执行日志失败: 记录不存在 id={log_id}")
                return
            log.status = status
            log.error_message = error_message
            log.executed_at = to_naive_beijing(now_beijing())
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新执行日志失败: {e}")
