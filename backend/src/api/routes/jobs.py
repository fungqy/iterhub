"""任务调度接口

收编原本直接定义在 main.py 中的 /api/jobs 系列接口,
仅依赖 get_scheduler(),不承载业务逻辑。
"""

from fastapi import APIRouter, HTTPException

from api.scheduler import get_scheduler

router = APIRouter(prefix="/api/jobs", tags=["调度任务"])


@router.get("")
async def get_jobs():
    """获取所有定时任务状态"""
    scheduler = get_scheduler()
    return {"total": len(scheduler.get_jobs()), "jobs": scheduler.get_jobs()}


@router.post("/{job_id}/trigger")
async def trigger_job(job_id: str):
    """手动触发指定任务"""
    result = get_scheduler().run_job_now(job_id)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/story-reminder/trigger")
async def trigger_story_reminder():
    """手动触发故事提醒任务"""
    return get_scheduler().run_job_now("story_reminder")


@router.post("/task-reminder/trigger")
async def trigger_task_reminder():
    """手动触发任务提醒任务"""
    return get_scheduler().run_job_now("task_reminder")


@router.post("/sonar-reminder/trigger")
async def trigger_sonar_reminder():
    """手动触发Sonar扫描提醒任务"""
    return get_scheduler().run_job_now("sonar_reminder")
