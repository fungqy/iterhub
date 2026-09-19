"""record_execution 异常时必须 rollback"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from api.scheduler import BEIJING_TZ, record_execution


def test_commit_failure_triggers_rollback():
    """关键回归：commit 异常时必须调用 session.rollback()"""
    session = MagicMock()
    session.__enter__.return_value = session
    # get_session 退出时会调用 session.close()，这里在 __exit__ 中模拟
    session.__exit__.side_effect = lambda *a: (session.close(), False)[1]
    session.commit.side_effect = RuntimeError("DB down")

    with patch("db.database.get_session", return_value=session), patch(
        "db.models.TaskExecutionLog"
    ):
        record_execution(
            project_config_id=1,
            task_type="story_reminder",
            scheduled_time=datetime(2026, 6, 8, 9, 30, tzinfo=BEIJING_TZ),
            status="success",
        )

    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_successful_commit_no_rollback():
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.side_effect = lambda *a: (session.close(), False)[1]
    with patch("db.database.get_session", return_value=session), patch(
        "db.models.TaskExecutionLog"
    ):
        record_execution(
            project_config_id=1,
            task_type="story_reminder",
            scheduled_time=datetime(2026, 6, 8, 9, 30, tzinfo=BEIJING_TZ),
            status="success",
        )

    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()
