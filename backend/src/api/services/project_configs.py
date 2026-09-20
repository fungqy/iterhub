"""项目配置相关的数据访问服务

负责从数据库读取项目提醒配置与 JIRA 认证,并组装成 ProjectRemindConfig。
原为 api/scheduler.py 中的叶子函数,现下沉到服务层,由 api/scheduler.py re-export。
"""

from __future__ import annotations

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from db.database import get_session
from db.models import ProjectConfig, ProjectReminderSettings
from util.jira import ProjectRemindConfig, get_auth_config_from_session

logger = logging.getLogger(__name__)


def get_jira_auth():
    """获取全局共享的JIRA认证配置(与登录用户无关)。

    仅负责「开一个 session」,查询逻辑复用 util.jira.get_auth_config_from_session ——
    历史实现与 util/jira.py 里那份私有副本是同源的两份代码,改一处漏一处。
    """

    with get_session() as session:
        return get_auth_config_from_session(session)


def get_project_configs():
    """从数据库获取项目配置"""

    with get_session() as session:
        # 查询所有需要提醒的项目配置
        reminder_settings = (
            session.query(ProjectReminderSettings)
            .filter(
                (ProjectReminderSettings.need_story_remind.is_(True))
                | (ProjectReminderSettings.need_task_remind.is_(True))
                | (ProjectReminderSettings.need_sonar_scan_remind.is_(True))
                | (ProjectReminderSettings.need_report_data.is_(True))
            )
            .all()
        )

        # ⚠ 认证配置是全局共享的,必须在循环外取一次:
        #   原先写在循环里 = 每个项目都新建一次 session 查同一张表(N+1)
        auth_config = get_jira_auth()

        result = []
        for setting in reminder_settings:
            config = setting.project_config
            if config is None:
                continue

            # 构建 ProjectRemindConfig 对象
            _gitlab_key = (
                str(config.gitlab_group_key)
                if config.gitlab_group_key is not None
                else ""
            )
            _sonar_key = (
                str(config.sonar_key_prefix)
                if config.sonar_key_prefix is not None
                else ""
            )
            _sonar_person = (
                str(config.sonar_scan_remind_default_person)
                if config.sonar_scan_remind_default_person is not None
                else ""
            )
            _robot_key = str(config.robot_key) if config.robot_key is not None else ""

            # 获取各任务的自定义时间
            story_time = getattr(setting, "story_remind_time", None) or ""
            task_time = getattr(setting, "task_remind_time", None) or ""
            sonar_time = getattr(setting, "sonar_remind_time", None) or ""

            result.append(
                ProjectRemindConfig(
                    project_config_id=config.id,
                    board_id=str(config.board_id),
                    board_name=str(config.board_name),
                    project_id=str(config.project_id),
                    project_name=str(config.project_name),
                    gitlab_group_key=_gitlab_key,
                    need_story_remind=bool(setting.need_story_remind),
                    need_task_remind=bool(setting.need_task_remind),
                    need_sonar_scan_remind=bool(setting.need_sonar_scan_remind),
                    need_report_data=bool(setting.need_report_data),
                    sonar_key_prefix=_sonar_key,
                    sonar_scan_remind_default_person=_sonar_person,
                    robot_key=_robot_key,
                    jira_user=auth_config.user if auth_config else "",
                    jira_token=auth_config.token if auth_config else "",
                    story_remind_time=story_time,
                    task_remind_time=task_time,
                    sonar_remind_time=sonar_time,
                )
            )
        return result


def get_project_config_by_id(project_config_id: int):
    """根据项目配置ID获取单个 ProjectRemindConfig"""

    with get_session() as session:
        config = (
            session.query(ProjectConfig)
            .filter(ProjectConfig.id == project_config_id)
            .first()
        )
        if not config:
            return None

        setting = config.reminder_settings
        auth_config = get_jira_auth()

        return ProjectRemindConfig(
            project_config_id=config.id,
            board_id=str(config.board_id),
            board_name=str(config.board_name),
            project_id=str(config.project_id),
            project_name=str(config.project_name),
            gitlab_group_key=str(config.gitlab_group_key or ""),
            need_story_remind=bool(setting.need_story_remind) if setting else False,
            need_task_remind=bool(setting.need_task_remind) if setting else False,
            need_sonar_scan_remind=bool(setting.need_sonar_scan_remind) if setting else False,
            need_report_data=bool(setting.need_report_data) if setting else False,
            sonar_key_prefix=str(config.sonar_key_prefix or ""),
            sonar_scan_remind_default_person=str(config.sonar_scan_remind_default_person or ""),
            robot_key=str(config.robot_key or ""),
            jira_user=auth_config.user if auth_config else "",
            jira_token=auth_config.token if auth_config else "",
            story_remind_time=getattr(setting, "story_remind_time", "") or "",
            task_remind_time=getattr(setting, "task_remind_time", "") or "",
            sonar_remind_time=getattr(setting, "sonar_remind_time", "") or "",
        )


def check_sprint_data_exists(sprint_id: str) -> bool:
    """检查指定 sprint 是否已有数据。

    ⚠ 查询失败时**向上抛**,不能 return False:「查不到」= 该迭代无数据(前端不提示
    覆盖,可直接执行),「查不了」= 故障。把故障伪装成「无数据」会让用户在库抖动时
    跳过覆盖确认直接重刷(调用点见 routes/scheduler.py 的 manual/report-data/check)。
    """
    try:
        with get_session() as session:
            query = text(
                "SELECT COUNT(1) FROM rdm_issue WHERE sprint_id = :sprint_id"
            )
            result = session.execute(query, {"sprint_id": sprint_id})
            count = result.scalar()
            return count is not None and count > 0
    except SQLAlchemyError:
        logger.exception("查询 sprint 数据失败: sprint_id=%s", sprint_id)
        raise


def check_sprints_data_exists(sprint_ids: list[str]) -> list[str]:
    """批量检查哪些 sprint 在 rdm_issue 中已有数据,返回命中的 sprint_id 列表。

    手动执行支持一次勾选多个 Sprint,逐个查会变成 N 次数据库往返,故在此一次 IN 查询收口。
    契约与 check_sprint_data_exists 一致:查询失败**向上抛**,绝不把故障伪装成「无数据」。
    """
    ids = [str(s) for s in sprint_ids if s not in (None, "")]
    if not ids:
        return []

    try:
        with get_session() as session:
            query = text(
                "SELECT DISTINCT sprint_id FROM rdm_issue WHERE sprint_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            rows = session.execute(query, {"ids": ids})
            return [str(row[0]) for row in rows]
    except SQLAlchemyError:
        logger.exception("批量查询 sprint 数据失败: sprint_ids=%s", ids)
        raise
