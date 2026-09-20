"""手动执行报表数据:多选 Sprint 的批量入队与跳过语义。

对应 routes/scheduler.py 的 POST /manual/report-data —— 从「单选」改「多选」后新增的分支:
  - 空列表 ⇒ 400,不能静默成功(否则用户点了执行却什么都没发生)
  - 某个 Sprint 已在执行 ⇒ **跳过它**、其余照常入队(而不是整体 409)
  - 所选 Sprint 全部在执行 ⇒ 409
  - RDM 未找到的 Sprint ⇒ 置 failed 并计入 skipped,不拖垮其余
  - 重复 id ⇒ 去重,只入队一次

全部外部依赖(项目配置 / RDM / 执行日志 / 后台任务)均为 mock:
后台任务由 TestClient 在响应后真实调度,这里替换成 no-op 以便断言入队次数。
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from util.jira import ProjectRemindConfig

PROJECT_ID = 1044
URL = "/api/scheduler/manual/report-data"


def _build_app() -> FastAPI:
    app = FastAPI()
    from api.routes import scheduler as scheduler_routes

    app.include_router(scheduler_routes.router)

    from api.routes.auth import get_current_user_from_header

    app.dependency_overrides[get_current_user_from_header] = lambda: {"sub": "1"}
    return app


def _config() -> ProjectRemindConfig:
    """带 JIRA 凭据的项目配置(auth_config 非 None,否则会在入队前被拦下)。"""
    return ProjectRemindConfig(
        project_config_id=PROJECT_ID,
        board_id="1044",
        board_name="board",
        project_id="P1",
        project_name="proj",
        jira_user="u",
        jira_token="t",
    )


class _FakeSprint:
    """只保留路由用到的 sprint_id 字段。"""

    def __init__(self, sprint_id: int) -> None:
        self.sprint_id = sprint_id


def _post(sprint_ids, *, accepted, rdm_sprints):
    """发一次手动执行请求,返回 (resp, 后台任务 mock, fail_manual_report_data mock)。

    accepted: start_manual_report_data 的返回值序列(True=登记成功,False=已在执行)
    rdm_sprints: ProjectUtil(...).sprints 返回的列表(模拟 RDM 侧的迭代)
    """
    with patch(
        "api.routes.scheduler.get_project_config_by_id", return_value=_config()
    ), patch(
        "api.routes.scheduler.start_manual_report_data", side_effect=accepted
    ), patch("api.routes.scheduler.ProjectUtil") as mock_util, patch(
        "api.routes.scheduler.record_execution", return_value=1
    ), patch(
        "api.routes.scheduler._run_report_data_task"
    ) as mock_task, patch(
        "api.routes.scheduler.fail_manual_report_data"
    ) as mock_fail:
        mock_util.return_value.sprints = rdm_sprints
        client = TestClient(_build_app())
        resp = client.post(
            URL, json={"project_config_id": PROJECT_ID, "sprint_ids": sprint_ids}
        )
    return resp, mock_task, mock_fail


def test_empty_sprint_ids_rejected():
    resp, mock_task, _ = _post([], accepted=[], rdm_sprints=[])

    assert resp.status_code == 400
    assert mock_task.call_count == 0


def test_busy_sprint_is_skipped_not_fatal():
    """一个已在执行不该拖垮其余的:它进 skipped,另一个照常入队。"""
    resp, mock_task, _ = _post(
        ["1", "2"], accepted=[True, False], rdm_sprints=[_FakeSprint(1)]
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_ids"] == ["1"]
    assert [s["sprint_id"] for s in body["skipped"]] == ["2"]
    assert mock_task.call_count == 1


def test_all_busy_returns_409():
    resp, mock_task, _ = _post(
        ["1", "2"], accepted=[False, False], rdm_sprints=[_FakeSprint(1)]
    )

    assert resp.status_code == 409
    assert mock_task.call_count == 0


def test_sprint_missing_in_rdm_is_marked_failed_and_skipped():
    """RDM 没找到的 Sprint:置 failed(别让前端轮询等不到终态)+ 计入 skipped。"""
    resp, mock_task, mock_fail = _post(
        ["1", "9"], accepted=[True, True], rdm_sprints=[_FakeSprint(1)]
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_ids"] == ["1"]
    assert [s["sprint_id"] for s in body["skipped"]] == ["9"]
    assert mock_task.call_count == 1
    # 未入队的那一个必须被显式置为 failed
    failed_ids = [c.args[0] for c in mock_fail.call_args_list]
    assert failed_ids == ["9"]


def test_duplicate_ids_queued_once():
    resp, mock_task, _ = _post(
        ["1", "1"], accepted=[True], rdm_sprints=[_FakeSprint(1)]
    )

    assert resp.status_code == 200
    assert resp.json()["task_ids"] == ["1"]
    assert mock_task.call_count == 1


def test_all_sprints_missing_in_rdm_returns_404():
    resp, mock_task, mock_fail = _post(
        ["7"], accepted=[True], rdm_sprints=[]
    )

    assert resp.status_code == 404
    assert mock_task.call_count == 0
    assert mock_fail.call_args_list[0].args[0] == "7"


def test_missing_jira_auth_fails_every_accepted_sprint():
    """缺认证时不能只把状态留在 pending:每个已登记的 Sprint 都要置 failed。"""

    class _NoAuthConfig(ProjectRemindConfig):
        @property
        def auth_config(self):
            return None

    cfg = _NoAuthConfig(
        project_config_id=PROJECT_ID,
        board_id="1044",
        board_name="board",
        project_id="P1",
        project_name="proj",
    )

    with patch(
        "api.routes.scheduler.get_project_config_by_id", return_value=cfg
    ), patch(
        "api.routes.scheduler.start_manual_report_data", return_value=True
    ), patch(
        "api.routes.scheduler._run_report_data_task"
    ) as mock_task, patch(
        "api.routes.scheduler.fail_manual_report_data"
    ) as mock_fail:
        resp = TestClient(_build_app()).post(
            URL, json={"project_config_id": PROJECT_ID, "sprint_ids": ["1", "2"]}
        )

    assert resp.status_code == 400
    assert mock_task.call_count == 0
    assert [c.args[0] for c in mock_fail.call_args_list] == ["1", "2"]
