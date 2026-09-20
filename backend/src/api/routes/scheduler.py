"""调度器路由"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc

from api.auth import get_current_user_from_header
from api.scheduler import (
    TASK_TYPE_REPORT,
    get_scheduler,
    get_today_tasks_status,
    manual_run_sonar_scan_reminder,
    manual_run_story_task,
    manual_run_task_reminder,
    now_beijing,
    record_execution,
    to_naive_beijing,
)
from api.services.project_configs import (
    check_sprint_data_exists,
    check_sprints_data_exists,
    get_project_config_by_id,
)
from api.services.report_data_service import (
    _run_report_data_task,
    fail_manual_report_data,
    get_manual_report_data_status,
    start_manual_report_data,
)
from db.database import get_session
from db.models import ProjectConfig, TaskExecutionLog
from util.jira import (
    INTERACTIVE_SPRINT_RETRIES,
    INTERACTIVE_SPRINT_TIMEOUT,
    ProjectUtil,
)

logger = logging.getLogger("SchedulerAPI")


# ⚠ 整组接口都要求登录:它们会真实触发外部动作(企微推送、拉取 RDM/Sonar)
#   或改动调度状态,匿名可达会被当成「发消息 / 打外部系统」的开关。
#   健康检查 /health 与登录接口不在本 router 内,天然保持匿名。
router = APIRouter(
    prefix="/api/scheduler",
    tags=["调度器"],
    dependencies=[Depends(get_current_user_from_header)],
)


class ManualExecuteRequest(BaseModel):
    project_config_id: int


class ManualReportDataRequest(BaseModel):
    project_config_id: int
    # 支持一次勾选多个 Sprint 批量入队。执行侧是**串行**的:
    # process_sprint 持有全局互斥锁,且同一请求的 background 任务本就顺序执行。
    sprint_ids: list[str]


class CheckReportDataRequest(BaseModel):
    sprint_ids: list[str]


@router.get("/jobs", response_model=list)
def get_jobs():
    """获取调度器当前所有任务状态"""
    scheduler = get_scheduler()
    return scheduler.get_jobs()


@router.get("/today-tasks")
def get_today_tasks():
    """获取今日任务状态"""
    return get_today_tasks_status()


@router.post("/jobs/{job_id}/run")
def run_job_now(job_id: str):
    """手动触发指定任务"""
    valid_types = ["story_reminder", "task_reminder", "sonar_reminder"]
    if job_id not in valid_types:
        raise HTTPException(
            status_code=400, detail=f"无效的任务类型，可选值: {valid_types}"
        )
    scheduler = get_scheduler()
    return scheduler.run_job_now(job_id)


@router.post("/jobs/reload")
def reload_jobs():
    """重新加载所有调度任务"""
    scheduler = get_scheduler()
    scheduler.reload_jobs()
    return {"status": "success", "message": "调度任务已重新加载"}


@router.get("/logs")
def get_execution_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    project_name: str | None = Query(None),
    executed_date: str | None = Query(None),
    task_type: str | None = Query(None),
    current_user: dict = Depends(get_current_user_from_header),
):
    with get_session() as session:
        query = session.query(TaskExecutionLog, ProjectConfig.project_name).join(
            ProjectConfig,
            TaskExecutionLog.project_config_id == ProjectConfig.id,
        )

        if executed_date:
            try:
                target_date = datetime.strptime(executed_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="executed_date 格式必须为 YYYY-MM-DD",
                )
        else:
            # ⚠ executed_at 是无时区列,过滤边界统一用 naive 北京时间
            #   (显式传入 executed_date 时 strptime 出来的本就是 naive)
            target_date = to_naive_beijing(now_beijing())

        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = target_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        query = query.filter(
            and_(
                TaskExecutionLog.executed_at >= day_start,
                TaskExecutionLog.executed_at <= day_end,
            )
        )

        if project_name:
            query = query.filter(
                ProjectConfig.project_name.like(f"%{project_name}%")
            )

        if task_type:
            query = query.filter(TaskExecutionLog.task_type == task_type)

        total = query.count()
        results = (
            query.order_by(desc(TaskExecutionLog.executed_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items = []
        for log, proj_name in results:
            items.append(
                {
                    "id": log.id,
                    "project_name": proj_name,
                    "task_type": log.task_type,
                    "executed_at": log.executed_at.isoformat()
                    if log.executed_at
                    else None,
                    "scheduled_time": log.scheduled_time.isoformat()
                    if log.scheduled_time
                    else None,
                    "status": log.status,
                    "error_message": log.error_message,
                    "task_exec_type": log.task_exec_type,
                }
            )

        return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/manual/story-reminder")
def manual_story_reminder(req: ManualExecuteRequest):
    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = now_beijing()
    manual_run_story_task(config, now)
    return {"status": "success", "message": f"项目 {config.project_name} 故事提醒已执行"}


@router.post("/manual/task-reminder")
def manual_task_reminder(req: ManualExecuteRequest):

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = now_beijing()
    manual_run_task_reminder(config, now)
    return {"status": "success", "message": f"项目 {config.project_name} 任务提醒已执行"}


@router.post("/manual/sonar-reminder")
def manual_sonar_reminder(req: ManualExecuteRequest):

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = now_beijing()
    manual_run_sonar_scan_reminder(config, now)
    return {
        "status": "success",
        "message": f"项目 {config.project_name} Sonar提醒已执行",
    }


@router.get("/manual/report-data/check/{project_config_id}/{sprint_id}")
def check_report_data_exists(project_config_id: int, sprint_id: str):
    exists = check_sprint_data_exists(sprint_id)
    return {"exists": exists}


@router.post("/manual/report-data/check")
def check_report_data_batch(req: CheckReportDataRequest):
    """批量检查所选 Sprint 是否已有数据(多选下前端只发一次请求)。

    返回 `existing` = 已有 rdm_issue 数据的 sprint_id 列表,前端据此提示「将被覆盖」。
    """
    return {"existing": check_sprints_data_exists(req.sprint_ids)}


@router.post("/manual/report-data")
def manual_report_data(req: ManualReportDataRequest, background: BackgroundTasks):
    """手动执行报表数据,支持一次入队多个 Sprint。

    多选下的取舍:
      - 某个 Sprint 已在执行 ⇒ **跳过它**,其余照常入队(而不是整体 409 —— 一个冲突
        不该把用户勾的其它迭代一起拦下);跳过原因随响应返回,由前端提示。
      - 入队前的校验(认证 / Sprint 是否存在)只拉一次 RDM,逐个比对;校验不过的
        Sprint 同步置为 failed,避免前端轮询永远等不到终态。
    """
    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    # 去重且保序:同一个 Sprint 在一次请求里只入队一次
    sprint_ids = list(dict.fromkeys(s for s in req.sprint_ids if s))
    if not sprint_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个 Sprint")

    accepted: list[str] = []
    skipped: list[dict] = []
    for sid in sprint_ids:
        if start_manual_report_data(req.project_config_id, sid):
            accepted.append(sid)
        else:
            skipped.append(
                {"sprint_id": sid, "reason": "该 Sprint 的报表数据任务正在执行中"}
            )

    if not accepted:
        raise HTTPException(
            status_code=409, detail="所选 Sprint 的报表数据任务均在执行中"
        )

    scheduled_time = now_beijing()

    # 从 RDM 实时获取所选 Sprint（下拉框数据同样来自 RDM，本地 rdm_sprint 表可能尚未同步）
    if not config.auth_config:
        for sid in accepted:
            fail_manual_report_data(sid, "项目缺少JIRA认证配置")
        raise HTTPException(
            status_code=400, detail="项目缺少JIRA认证配置,无法获取Sprint"
        )
    try:
        # 交互式路径:探测 RDM 用短超时,否则用户要多等默认的 60s×3(见 util.jira 常量)
        sprints = (
            ProjectUtil(
                config,
                config.auth_config,
                sprint_timeout=INTERACTIVE_SPRINT_TIMEOUT,
                sprint_retries=INTERACTIVE_SPRINT_RETRIES,
            ).sprints
            or []
        )
    except Exception:
        for sid in accepted:
            fail_manual_report_data(sid, "从 RDM 获取 Sprint 失败")
        raise

    sprint_by_id = {str(s.sprint_id): s for s in sprints}

    queued: list[str] = []
    for sid in accepted:
        sprint = sprint_by_id.get(str(sid))
        if sprint is None:
            fail_manual_report_data(sid, f"RDM 未找到 sprint_id={sid} 的 Sprint")
            skipped.append({"sprint_id": sid, "reason": "RDM 未找到该 Sprint"})
            continue

        # 先插入一条 pending 日志,后续 running/success/failed 在该记录上原地更新
        log_id = record_execution(
            req.project_config_id,
            TASK_TYPE_REPORT,
            scheduled_time,
            "pending",
            task_exec_type="manual",
        )
        # ⚠ 同一请求的多个 background 任务是**顺序**执行的(Starlette BackgroundTasks),
        #   正好对上 process_sprint 的全局互斥锁:多个 Sprint 排队逐个跑,不会互相打断。
        background.add_task(
            _run_report_data_task,
            req.project_config_id,
            sid,
            scheduled_time,
            sprint,
            log_id,
        )
        queued.append(sid)

    if not queued:
        raise HTTPException(status_code=404, detail="所选 Sprint 在 RDM 均未找到")

    return {
        "status": "pending",
        "task_ids": queued,
        "skipped": skipped,
        "message": f"项目 {config.project_name} 的 {len(queued)} 个 Sprint 报表数据已加入执行队列",
    }


@router.get("/manual/report-data/status/{sprint_id}")
def get_report_data_status(sprint_id: str):
    return get_manual_report_data_status(sprint_id)
