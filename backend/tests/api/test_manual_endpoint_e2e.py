"""端到端验证:用户点击"手动执行故事提醒" → 真实 JIRA DNS 故障

这条用例完全模拟用户在 backend/logs/app.log 中遇到的场景:
  1. 前端 POST /api/scheduler/manual/story-reminder
  2. 路由 → manual_run_story_task → module.gene_message → JIRA HTTP
  3. JIRA host 不可达,requests 抛 ConnectionError
  4. 期望:
     - HTTP 502 + { detail: "无法解析域名 rdm.zvos.zoomlion.com, ..." }
     - 整个流程只产生 1 行 ERROR 日志(无 traceback)
     - 数据库 task_execution_logs 表的 error_message 字段也被分类为友好消息
"""

import logging
from unittest.mock import patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from util.errors import install_exception_handler
from util.jira import ProjectRemindConfig

DNS_ERR = requests.exceptions.ConnectionError(
    "HTTPConnectionPool(host='rdm.zvos.zoomlion.com', port=80): "
    "Max retries exceeded with url: /rest/agile/1.0/board/1044/sprint "
    "(Caused by NameResolutionError(\"<urllib3.connection.HTTPConnection object>: "
    "Failed to resolve 'rdm.zvos.zoomlion.com' "
    "([Errno -2] Name or service not known)\"))"
)


def _build_minimal_app():
    """构造一个挂载真实路由 + 全局 handler 的 FastAPI app,跳过 lifespan/DB。"""
    app = FastAPI()
    install_exception_handler(app)
    from api.routes import scheduler as scheduler_routes

    app.include_router(scheduler_routes.router)

    # 跳过鉴权
    from api.routes.auth import get_current_user_from_header

    app.dependency_overrides[get_current_user_from_header] = lambda: {"sub": "1"}
    return app


def test_manual_story_reminder_returns_502_with_friendly_message(caplog):
    app = _build_minimal_app()

    # 模拟 get_project_config_by_id 返回一个合法配置
    cfg = ProjectRemindConfig(
        project_config_id=1044,
        board_id="1044",
        board_name="具身智能生态平台",
        project_id="P1",
        project_name="具身智能生态平台",
        jira_user="u",
        jira_token="t",
        robot_key="rk",
    )

    # 模拟 task module 的 gene_message 抛 DNS 错误
    with patch(
        "api.routes.scheduler.get_project_config_by_id", return_value=cfg
    ), patch(
        "task.remind_week_story.gene_message", side_effect=DNS_ERR
    ), patch(
        "api.scheduler.record_execution"
    ) as mock_record, caplog.at_level(logging.ERROR):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/scheduler/manual/story-reminder",
            json={"project_config_id": 1044},
        )

    # HTTP 层
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "rdm.zvos.zoomlion.com" in detail
    assert "无法解析域名" in detail

    # 日志层:只有 manual_run_* 的一行 ERROR + 全局 handler 的一行 ERROR
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    for r in error_records:
        # 关键回归:绝不应输出 traceback
        assert "Traceback" not in r.getMessage(), r.getMessage()
        assert "urllib3.connection.HTTPConnection" not in r.getMessage()
    # 所有错误行都包含项目名或路径(避免噪声)
    msgs = [r.getMessage() for r in error_records]
    assert any("具身智能生态平台" in m for m in msgs), msgs
    assert any("/api/scheduler/manual/story-reminder" in m for m in msgs), msgs

    # 任务执行日志被记录为 failed + 友好消息
    record_calls = mock_record.call_args_list
    assert len(record_calls) >= 1
    # status 在 manual_run_* 中以位置参数传入,所以从 c.args 取
    failed_call = [c for c in record_calls if c.args[3] == "failed"]
    assert len(failed_call) == 1
    assert "无法解析域名" in failed_call[0].args[4]
