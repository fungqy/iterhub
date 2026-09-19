"""项目配置相关的数据访问服务

负责从数据库读取项目提醒配置与 JIRA 认证,并组装成 ProjectRemindConfig。
原为 api/scheduler.py 中的叶子函数,现下沉到服务层,由 api/scheduler.py re-export。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.database import get_session
from db.models import JiraAuthConfig, ProjectConfig, ProjectReminderSettings
from util.jira import AuthConfig, ProjectRemindConfig

logger = logging.getLogger(__name__)


def get_jira_auth():
    """获取全局共享的JIRA认证配置(与登录用户无关)。

    已取消「用户-JIRA认证」绑定:凭据是全体用户共用的业务配置。
    表中通常只有一行;多行时取 id 最小的一行,保证结果稳定。
    """

    with get_session() as session:
        config = (
            session.query(JiraAuthConfig)
            .order_by(JiraAuthConfig.id)
            .first()
        )

        if config:
            return AuthConfig(
                user=str(config.jira_user),
                token=str(config.jira_token),
                url=str(config.jira_url),
            )
        return None


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

        result = []
        for setting in reminder_settings:
            config = setting.project_config
            if config is None:
                continue

            # 获取全局共享的JIRA认证
            auth_config = get_jira_auth()

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
    """检查指定 sprint 是否已有数据"""
    try:
        with get_session() as session:
            query = text(
                "SELECT COUNT(1) FROM rdm_issue WHERE sprint_id = :sprint_id"
            )
            result = session.execute(query, {"sprint_id": sprint_id})
            count = result.scalar()
            return count is not None and count > 0
    except SQLAlchemyError as e:
        logger.error(f"查询sprint数据失败, sprint_id={sprint_id}, error={e}")
        return False
