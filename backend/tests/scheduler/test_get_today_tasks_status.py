"""get_today_tasks_status 的状态分支：pending / expired / success"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.scheduler import BEIJING_TZ, get_today_tasks_status


def _settings(story=("09:30", True), task=(None, False), sonar=(None, False)):
    return SimpleNamespace(
        need_story_remind=story[1],
        story_remind_time=story[0],
        need_task_remind=task[1],
        task_remind_time=task[0],
        need_sonar_scan_remind=sonar[1],
        sonar_remind_time=sonar[0],
    )


def _project(id_=1, name="ProjectA", settings=None):
    return SimpleNamespace(id=id_, project_name=name, reminder_settings=settings)


def _fake_session(logs, projects):
    """构造一个 SQLAlchemy 风格的 mock session"""
    session = MagicMock()

    def query(model):
        q = MagicMock()
        if "TaskExecutionLog" in str(model):
            q.filter.return_value.all.return_value = logs
        else:  # ProjectConfig
            q.all.return_value = projects
        return q

    session.query.side_effect = query
    # get_session 现为上下文管理器，with 语句会调用 __enter__；让 __enter__ 返回同一 session
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_pending_when_no_log_and_time_in_future():
    fake_now = datetime(2026, 6, 8, 8, 0, tzinfo=BEIJING_TZ)  # 早于 09:30
    project = _project(settings=_settings(story=("09:30", True)))
    session = _fake_session(logs=[], projects=[project])

    with patch("db.database.get_session", return_value=session), patch(
        "api.scheduler.now_beijing", return_value=fake_now
    ):
        result = get_today_tasks_status()

    assert len(result) == 1
    assert result[0]["task_type"] == "story_reminder"
    assert result[0]["status"] == "pending"


def test_expired_when_no_log_and_time_passed():
    fake_now = datetime(2026, 6, 8, 10, 0, tzinfo=BEIJING_TZ)  # 晚于 09:30
    project = _project(settings=_settings(story=("09:30", True)))
    session = _fake_session(logs=[], projects=[project])

    with patch("db.database.get_session", return_value=session), patch(
        "api.scheduler.now_beijing", return_value=fake_now
    ):
        result = get_today_tasks_status()

    assert result[0]["status"] == "expired"


def test_success_when_log_present():
    fake_now = datetime(2026, 6, 8, 10, 0, tzinfo=BEIJING_TZ)
    executed_at = datetime(2026, 6, 8, 9, 31, tzinfo=BEIJING_TZ)
    log = SimpleNamespace(
        project_config_id=1,
        task_type="story_reminder",
        status="success",
        executed_at=executed_at,
    )
    project = _project(settings=_settings(story=("09:30", True)))
    session = _fake_session(logs=[log], projects=[project])

    with patch("db.database.get_session", return_value=session), patch(
        "api.scheduler.now_beijing", return_value=fake_now
    ):
        result = get_today_tasks_status()

    assert result[0]["status"] == "success"
    assert result[0]["executed_at"] == executed_at.isoformat()


def test_disabled_or_no_time_omitted():
    fake_now = datetime(2026, 6, 8, 8, 0, tzinfo=BEIJING_TZ)
    # need_story_remind=False 且 task / sonar 全关
    project = _project(settings=_settings(story=("09:30", False)))
    session = _fake_session(logs=[], projects=[project])

    with patch("db.database.get_session", return_value=session), patch(
        "api.scheduler.now_beijing", return_value=fake_now
    ):
        result = get_today_tasks_status()

    assert result == []
