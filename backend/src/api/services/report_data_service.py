"""报表数据手动执行服务

从 api/routes/scheduler.py 迁入报表数据后台任务的状态机:
模块级状态缓存 + 后台任务执行 + 执行日志记录。
路由层只需做参数校验并调用本模块的封装函数。
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("SchedulerAPI")

# 手动执行报表数据任务状态: sprint_id -> {status, started_at, finished_at, error}
# status: "pending" | "running" | "success" | "failed"
_report_data_status: dict[str, dict] = {}
_report_data_status_lock = threading.Lock()


def _run_report_data_task(
    project_config_id: int,
    sprint_id: str,
    scheduled_time,
    sprint,
    log_id: int | None = None,
):
    """后台执行报表数据处理任务,并原地更新执行日志状态(每条执行只留一条记录)。"""
    from api.services.execution_log import update_execution
    from task.report_rdm_data import process_sprint

    update_execution(log_id, "running")
    with _report_data_status_lock:
        _report_data_status[sprint_id]["status"] = "running"
    try:
        process_sprint(sprint)
        with _report_data_status_lock:
            _report_data_status[sprint_id]["status"] = "success"
            _report_data_status[sprint_id]["finished_at"] = time.time()
        update_execution(log_id, "success")
    except Exception as e:
        logger.exception("报表数据任务失败: sprint_id=%s", sprint_id)
        from util.errors import classify_error

        _status, friendly = classify_error(e)
        with _report_data_status_lock:
            _report_data_status[sprint_id]["status"] = "failed"
            _report_data_status[sprint_id]["finished_at"] = time.time()
            _report_data_status[sprint_id]["error"] = friendly
        update_execution(log_id, "failed", friendly)


def start_manual_report_data(project_config_id: int, sprint_id: str) -> bool:
    """登记报表任务状态,若已有任务在跑则返回 False（并发冲突）。"""
    with _report_data_status_lock:
        existing = _report_data_status.get(sprint_id)
        if existing and existing["status"] in ("pending", "running"):
            return False
        _report_data_status[sprint_id] = {
            "status": "pending",
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
        }
    return True


def fail_manual_report_data(sprint_id: str, error: str) -> None:
    """将已登记的任务状态置为 failed（用于入队前校验失败，避免状态卡在 pending）"""
    with _report_data_status_lock:
        info = _report_data_status.get(sprint_id)
        if info and info["status"] in ("pending", "running"):
            info["status"] = "failed"
            info["finished_at"] = time.time()
            info["error"] = error


def get_manual_report_data_status(sprint_id: str):
    """查询报表任务当前状态"""
    with _report_data_status_lock:
        info = _report_data_status.get(sprint_id)
    if not info:
        return {"sprint_id": sprint_id, "status": "unknown"}
    return {"sprint_id": sprint_id, **info}
