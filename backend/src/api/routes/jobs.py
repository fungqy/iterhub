"""任务调度接口

收编原本直接定义在 main.py 中的 /api/jobs 系列接口,
仅依赖 get_scheduler(),不承载业务逻辑。

⚠ 整组接口都要求登录:它们会真实触发对外推送(企微/Sonar/GitLab),
  匿名可达等于把「给群里发消息」「打外部系统」开放给任何人。
"""

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_from_header
from api.scheduler import get_scheduler

router = APIRouter(
    prefix="/api/jobs",
    tags=["调度任务"],
    dependencies=[Depends(get_current_user_from_header)],
)


@router.get("")
async def get_jobs():
    """获取所有定时任务状态"""
    scheduler = get_scheduler()
    return {"total": len(scheduler.get_jobs()), "jobs": scheduler.get_jobs()}


# ⚠ 字面量路径必须注册在 /{job_id}/trigger 之前:两者段数相同,
#   否则这三个会被 {job_id} 抢先匹配,落到通用处理器里当成非法 job_id
#   (表现为 404「无效的任务类型」,接口形同不存在)。
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


@router.post("/{job_id}/trigger")
async def trigger_job(job_id: str):
    """手动触发指定任务"""
    result = get_scheduler().run_job_now(job_id)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result
