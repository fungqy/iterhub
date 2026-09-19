"""TaskScheduler 生命周期：start / stop / reload，per-(项目,类型) 精确 cron 注册

旧实现注册 3 个每分钟触发的"类型级"job；新实现改为按 (项目, 任务类型) 注册
精确 cron 任务(CronTrigger(hour, minute))，工作日门禁放在运行时。本文件据此
重写契约：job id 形如 "{type}:{project_config_id}"，trigger 钉在配置时间点。
"""

from unittest.mock import patch

from apscheduler.triggers.cron import CronTrigger

from api.scheduler import (
    TASK_TYPE_SONAR,
    TASK_TYPE_STORY,
    TASK_TYPE_TASK,
    get_scheduler,
)
from util.jira import ProjectRemindConfig


def _cfg(pid, story=("09:30", True), task=("10:00", True), sonar=("11:00", True)):
    s_t, s_on = story
    t_t, t_on = task
    so_t, so_on = sonar
    return ProjectRemindConfig(
        project_config_id=pid,
        board_id=str(pid),
        board_name=f"b{pid}",
        project_id=f"p{pid}",
        project_name=f"Project{pid}",
        need_story_remind=s_on,
        need_task_remind=t_on,
        need_sonar_scan_remind=so_on,
        story_remind_time=s_t,
        task_remind_time=t_t,
        sonar_remind_time=so_t,
        jira_user="u",
        jira_token="t",
        robot_key="rk",
    )


def _patch_configs(configs):
    return patch("api.scheduler.get_project_configs", return_value=configs)


def test_jobs_registered_from_configs(workday_true):
    cfg = _cfg(1)
    with _patch_configs([cfg]):
        scheduler = get_scheduler()
        job_ids = {j["id"] for j in scheduler.get_jobs()}
    assert job_ids == {
        f"{TASK_TYPE_STORY}:1",
        f"{TASK_TYPE_TASK}:1",
        f"{TASK_TYPE_SONAR}:1",
    }


def test_jobs_registered_even_when_not_workday(workday_false):
    """关键回归：周末/节假日也必须注册 job（门禁在运行时，不在注册时）"""
    cfg = _cfg(1)
    with _patch_configs([cfg]):
        scheduler = get_scheduler()
        assert len(scheduler.get_jobs()) == 3


def test_per_project_trigger_uses_configured_time(workday_true):
    """关键回归：精确 cron 必须把 job 钉在配置的时间点，而非每分钟触发。"""
    cfg = _cfg(1, story=("09:30", True), task=("14:05", True), sonar=("08:00", True))
    with _patch_configs([cfg]):
        scheduler = get_scheduler()
        job = scheduler.scheduler.get_job(f"{TASK_TYPE_STORY}:1")
        assert isinstance(job.trigger, CronTrigger)
        trig = str(job.trigger)
        # 钉在 09:30
        assert "hour='9'" in trig
        assert "minute='30'" in trig

        job_task = scheduler.scheduler.get_job(f"{TASK_TYPE_TASK}:1")
        trig_task = str(job_task.trigger)
        assert "hour='14'" in trig_task
        assert "minute='5'" in trig_task

        # 必须不再出现每分钟触发（旧实现的反模式）
        for j in scheduler.get_jobs():
            assert "minute='*'" not in j["trigger"]


def test_disabled_type_not_registered(workday_true):
    cfg = _cfg(1, sonar=("11:00", False))
    with _patch_configs([cfg]):
        scheduler = get_scheduler()
        job_ids = {j["id"] for j in scheduler.get_jobs()}
    assert f"{TASK_TYPE_SONAR}:1" not in job_ids
    assert len(job_ids) == 2


def test_reload_jobs_on_nonworkday_rebuilds(workday_false):
    """关键回归：非工作日 reload_jobs 不能让 jobs 数量变成 0，且 id 稳定"""
    cfg = _cfg(1)
    with _patch_configs([cfg]):
        scheduler = get_scheduler()
        assert len(scheduler.get_jobs()) == 3
        scheduler.reload_jobs()
        assert len(scheduler.get_jobs()) == 3
        assert {j["id"] for j in scheduler.get_jobs()} == {
            f"{TASK_TYPE_STORY}:1",
            f"{TASK_TYPE_TASK}:1",
            f"{TASK_TYPE_SONAR}:1",
        }


def test_start_stop_idempotent(workday_true):
    with _patch_configs([_cfg(1)]):
        scheduler = get_scheduler()
        scheduler.start()
        scheduler.start()  # 第二次 start 不应抛错
        assert scheduler.scheduler.running is True
        scheduler.stop()
        scheduler.stop()  # 第二次 stop 不应抛错


def test_run_job_now_unknown_returns_error(workday_true):
    with _patch_configs([]):
        scheduler = get_scheduler()
        res = scheduler.run_job_now("not_a_real_task")
    assert res["status"] == "error"


def test_run_job_now_type_runs_all(workday_true):
    with _patch_configs([]), patch("api.scheduler.run_all_story_tasks") as mock_run:
        scheduler = get_scheduler()
        res = scheduler.run_job_now(TASK_TYPE_STORY)
    assert res["status"] == "success"
    mock_run.assert_called_once()
