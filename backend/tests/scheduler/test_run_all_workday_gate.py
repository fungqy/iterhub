"""run_all_xxx 在非工作日应跳过；在工作日按时间匹配触发"""

from datetime import datetime
from unittest.mock import patch

from api.scheduler import (
    BEIJING_TZ,
    run_all_sonar_scan_reminders,
    run_all_story_tasks,
    run_all_task_reminders,
)
from util.jira import ProjectRemindConfig


def _make_config(**overrides) -> ProjectRemindConfig:
    base = dict(
        board_id="1",
        board_name="b",
        project_id="p",
        project_name="pn",
        project_config_id=1,
        need_story_remind=True,
        need_task_remind=True,
        need_sonar_scan_remind=True,
        story_remind_time="09:30",
        task_remind_time="09:30",
        sonar_remind_time="09:30",
        jira_user="u",
        jira_token="t",
        robot_key="rk",
    )
    base.update(overrides)
    return ProjectRemindConfig(**base)


def test_nonworkday_skips_all_three(workday_false):
    """关键回归：is_workday=False 时 run_all_* 仅记日志、不走业务流程"""
    with patch("api.scheduler.get_project_configs") as mock_get:
        # 故意让 get_project_configs 抛错；若被调用则说明工作日 gate 失效
        mock_get.side_effect = AssertionError("不应在非工作日触发业务逻辑")
        run_all_story_tasks()
        run_all_task_reminders()
        run_all_sonar_scan_reminders()


def test_workday_matches_time_and_runs(workday_true):
    cfg = _make_config()

    fixed_now = datetime(2026, 6, 8, 9, 30, tzinfo=BEIJING_TZ)  # 周一 09:30

    with patch("api.scheduler.now_beijing", return_value=fixed_now), patch(
        "api.scheduler.get_project_configs", return_value=[cfg]
    ), patch("api.scheduler.run_story_task") as mock_run:
        run_all_story_tasks()
        mock_run.assert_called_once()


def test_workday_time_mismatch_skips(workday_true):
    cfg = _make_config(story_remind_time="10:00")

    fixed_now = datetime(2026, 6, 8, 9, 30, tzinfo=BEIJING_TZ)  # 不匹配

    with patch("api.scheduler.now_beijing", return_value=fixed_now), patch(
        "api.scheduler.get_project_configs", return_value=[cfg]
    ), patch("api.scheduler.run_story_task") as mock_run:
        run_all_story_tasks()
        mock_run.assert_not_called()


def test_workday_empty_time_skips(workday_true):
    cfg = _make_config(story_remind_time="")

    fixed_now = datetime(2026, 6, 8, 9, 30, tzinfo=BEIJING_TZ)

    with patch("api.scheduler.now_beijing", return_value=fixed_now), patch(
        "api.scheduler.get_project_configs", return_value=[cfg]
    ), patch("api.scheduler.run_story_task") as mock_run:
        run_all_story_tasks()
        mock_run.assert_not_called()
