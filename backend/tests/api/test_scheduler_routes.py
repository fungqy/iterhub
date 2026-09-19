"""/api/scheduler/* HTTP 路由的烟测，不触发数据库

新实现按 (项目, 类型) 注册精确 cron 任务，job id 形如 "{type}:{pid}"，
因此本文件将原"恰好 3 个固定 job"的断言改为基于 mock 配置的 per-project 契约。
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import scheduler as scheduler_routes
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


@pytest.fixture
def client():
    """构造一个仅挂载 scheduler 路由的最小 FastAPI 应用，避免触发 lifespan / DB。"""
    app = FastAPI()
    app.include_router(scheduler_routes.router)

    # 把需要鉴权的 dependency override 掉
    from api.routes.auth import get_current_user_from_header

    app.dependency_overrides[get_current_user_from_header] = lambda: {"sub": "1"}

    with TestClient(app) as c:
        yield c


def test_get_jobs_uses_singleton(client, workday_true):
    with patch("api.scheduler.get_project_configs", return_value=[_cfg(1)]):
        resp = client.get("/api/scheduler/jobs")
    assert resp.status_code == 200
    ids = {j["id"] for j in resp.json()}
    assert ids == {
        "story_reminder:1",
        "task_reminder:1",
        "sonar_reminder:1",
    }


def test_run_job_now_validates_type(client, workday_true):
    resp = client.post("/api/scheduler/jobs/unknown/run")
    assert resp.status_code == 400


def test_reload_jobs_keeps_count(client, workday_false):
    """关键回归：非工作日 reload 后 jobs 数量仍为配置驱动的数量（不为 0）"""
    with patch("api.scheduler.get_project_configs", return_value=[_cfg(1)]):
        resp = client.post("/api/scheduler/jobs/reload")
        assert resp.status_code == 200

        resp = client.get("/api/scheduler/jobs")
        assert len(resp.json()) == 3


def test_logs_bad_date_returns_400(client, workday_true):
    """关键回归：非法 executed_date 必须 400，不能静默回退到今日"""
    resp = client.get("/api/scheduler/logs?executed_date=not-a-date")
    assert resp.status_code == 400


def test_logs_valid_date_calls_db(client, workday_true):
    """validdate 路径下应进入 DB 流程，这里 mock 掉返回空列表"""
    with patch("api.routes.scheduler.get_session") as mock_get_session:
        session = mock_get_session.return_value
        session.__enter__.return_value = session  # with 语句复用同一 session
        query = session.query.return_value
        query.join.return_value = query
        query.filter.return_value = query
        query.count.return_value = 0
        query.order_by.return_value = query
        query.offset.return_value = query
        query.limit.return_value = query
        query.all.return_value = []

        resp = client.get("/api/scheduler/logs?executed_date=2026-06-08")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_run_job_story_reminder(client, workday_true):
    with patch("api.scheduler.get_project_configs", return_value=[]), patch(
        "api.scheduler.run_all_story_tasks"
    ) as mock_run:
        resp = client.post("/api/scheduler/jobs/story_reminder/run")

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    mock_run.assert_called_once()
