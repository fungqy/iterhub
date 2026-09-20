"""鉴权回归网:/api/jobs 与 /api/scheduler 全部接口对匿名请求返回 401。

为什么要单独写:这两个 router 原先完全匿名,而全仓此前**没有任何 401 断言**;
仅靠 dependency_overrides 的正向用例无法发现「新增接口时忘了挂鉴权」。

⚠ 这里刻意**不做** dependency_overrides —— 本文件考察的就是「没有登录态时必须被拦住」。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import jobs as jobs_routes
from api.routes import scheduler as scheduler_routes


@pytest.fixture
def anon_client():
    """最小应用:只挂目标 router,不带任何鉴权覆盖。"""
    app = FastAPI()
    app.include_router(jobs_routes.router)
    app.include_router(scheduler_routes.router)
    with TestClient(app) as client:
        yield client


# (method, path, json_body):json_body 非空时按请求体发送,
# 避免「401 与 422 哪个先到」的争议掩盖漏挂鉴权的问题。
PROTECTED_ENDPOINTS = [
    ("GET", "/api/jobs", None),
    ("POST", "/api/jobs/story-reminder/trigger", None),
    ("POST", "/api/jobs/task-reminder/trigger", None),
    ("POST", "/api/jobs/sonar-reminder/trigger", None),
    ("POST", "/api/jobs/story_reminder/trigger", None),
    ("GET", "/api/scheduler/jobs", None),
    ("GET", "/api/scheduler/today-tasks", None),
    ("POST", "/api/scheduler/jobs/reload", None),
    ("POST", "/api/scheduler/jobs/story_reminder/run", None),
    ("POST", "/api/scheduler/manual/story-reminder", {"project_config_id": 1}),
    ("POST", "/api/scheduler/manual/task-reminder", {"project_config_id": 1}),
    ("POST", "/api/scheduler/manual/sonar-reminder", {"project_config_id": 1}),
    ("GET", "/api/scheduler/manual/report-data/check/1/2", None),
    (
        "POST",
        "/api/scheduler/manual/report-data",
        {"project_config_id": 1, "sprint_id": "2"},
    ),
    ("GET", "/api/scheduler/manual/report-data/status/2", None),
    ("GET", "/api/scheduler/logs", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED_ENDPOINTS)
def test_anonymous_request_is_rejected(anon_client, method, path, body):
    resp = anon_client.request(method, path, json=body)
    assert resp.status_code == 401, (
        f"{method} {path} 未登录却返回 {resp.status_code} —— 该接口可能漏挂登录依赖"
    )
    assert resp.json()["detail"] == "未提供认证信息"


def test_invalid_token_is_rejected(anon_client):
    """坏 token 不能因为「有 Authorization 头」就放行。"""
    resp = anon_client.get(
        "/api/scheduler/jobs", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token已过期或无效"
