from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

from util.qywx import mask_key

Base = declarative_base()


class User(Base):
    """用户模型"""

    __tablename__ = "sys_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self, include_password=False):
        data = {
            "id": self.id,
            "username": self.username,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }
        if include_password:
            data["password"] = self.password
        return data


class JiraAuthConfig(Base):
    """JIRA认证配置模型(全局共享,与登录用户无关)

    已取消「用户-JIRA认证」绑定:凭据是全体用户共用的业务配置,表内通常只有一行。
    """

    __tablename__ = "project_jira_auth"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    jira_url: Mapped[str] = mapped_column(
        String(255), nullable=False, default="http://rdm.zvos.zoomlion.com"
    )
    jira_user: Mapped[str] = mapped_column(String(100), nullable=False)
    jira_token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联：使用此配置的项目
    projects = relationship("ProjectConfig", back_populates="jira_auth_config")

    def to_dict(self, include_token=False):
        data = {
            "id": self.id,
            "jira_url": self.jira_url,
            "jira_user": self.jira_user,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }
        if include_token:
            data["jira_token"] = self.jira_token
        return data


class ProjectConfig(Base):
    """项目配置模型"""

    __tablename__ = "project_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    board_name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gitlab_group_key: Mapped[str] = mapped_column(String(100), default="")
    sonar_key_prefix: Mapped[str] = mapped_column(String(100), default="")
    sonar_scan_remind_default_person: Mapped[str] = mapped_column(String(100), default="")
    robot_key: Mapped[str] = mapped_column(String(100), default="")
    jira_user: Mapped[str] = mapped_column(String(100), default="")
    jira_token: Mapped[str] = mapped_column(String(255), default="")
    jira_auth_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_jira_auth.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联：JIRA认证配置
    jira_auth_config = relationship("JiraAuthConfig", back_populates="projects")
    # 关联：提醒设置
    reminder_settings = relationship(
        "ProjectReminderSettings",
        back_populates="project_config",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_token=False, mask_robot_key=True):
        """序列化项目配置。

        :param include_token: 是否返回 JIRA token 明文
        :param mask_robot_key: 是否对企微 robot_key 脱敏。列表接口保持默认 True
            (webhook key 属凭据,不应在列表里广而告之);详情接口传 False,
            因为编辑表单需要真实值回显 —— 回显掩码会在保存时把掩码写回库里
        """
        data = {
            "id": self.id,
            "board_id": self.board_id,
            "board_name": self.board_name,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "gitlab_group_key": self.gitlab_group_key,
            "sonar_key_prefix": self.sonar_key_prefix,
            "sonar_scan_remind_default_person": self.sonar_scan_remind_default_person,
            "robot_key": (
                (mask_key(self.robot_key) if self.robot_key else "")
                if mask_robot_key
                else self.robot_key
            ),
            "jira_auth_config_id": self.jira_auth_config_id,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }
        # 如果需要包含JIRA认证详情
        if self.jira_auth_config is not None:
            auth_data = self.jira_auth_config.to_dict(include_token=include_token)
            data["jira_url"] = auth_data["jira_url"]
            data["jira_user"] = auth_data["jira_user"]
            if include_token:
                data["jira_token"] = auth_data.get("jira_token")
        else:
            # 直接从项目配置获取
            data["jira_user"] = getattr(self, "jira_user", "")
            data["jira_token"] = (
                getattr(self, "jira_token", "") if include_token else ""
            )
        # 如果包含提醒设置
        if self.reminder_settings is not None:
            reminder_data = self.reminder_settings.to_dict()
            data["need_story_remind"] = reminder_data["need_story_remind"]
            data["need_task_remind"] = reminder_data["need_task_remind"]
            data["need_sonar_scan_remind"] = reminder_data["need_sonar_scan_remind"]
            data["need_report_data"] = reminder_data["need_report_data"]
            data["story_remind_time"] = reminder_data["story_remind_time"]
            data["task_remind_time"] = reminder_data["task_remind_time"]
            data["sonar_remind_time"] = reminder_data["sonar_remind_time"]
            data["reminder_settings"] = reminder_data
        return data


class ProjectReminderSettings(Base):
    """项目提醒设置模型"""

    __tablename__ = "project_reminder_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_config_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("project_configs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    need_story_remind: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否需要故事提醒
    need_task_remind: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否需要子任务到期提醒
    need_sonar_scan_remind: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否需要Sonar扫描提醒
    need_report_data: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否需要生产RDM报表数据
    # 各任务类型的自定义调度时间 (HH:MM格式，留空使用全局默认)
    story_remind_time: Mapped[str] = mapped_column(String(10), nullable=True)  # 故事提醒时间
    task_remind_time: Mapped[str] = mapped_column(String(10), nullable=True)  # 任务提醒时间
    sonar_remind_time: Mapped[str] = mapped_column(String(10), nullable=True)  # Sonar扫描提醒时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联：所属项目
    project_config = relationship("ProjectConfig", back_populates="reminder_settings")

    def to_dict(self):
        return {
            "id": self.id,
            "project_config_id": self.project_config_id,
            "need_story_remind": self.need_story_remind,
            "need_task_remind": self.need_task_remind,
            "need_sonar_scan_remind": self.need_sonar_scan_remind,
            "need_report_data": self.need_report_data,
            "story_remind_time": self.story_remind_time,
            "task_remind_time": self.task_remind_time,
            "sonar_remind_time": self.sonar_remind_time,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }


class Holiday(Base):
    """节假日模型"""

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    datestr: Mapped[datetime] = mapped_column(DateTime, unique=True, nullable=False)
    isholiday: Mapped[bool] = mapped_column(Boolean, default=False)
    iscompday: Mapped[bool] = mapped_column(Boolean, default=False)
    weekday: Mapped[int] = mapped_column(Integer)

    @property
    def datestr_str(self):
        """获取日期字符串"""
        # 检查是否是类调用
        if not isinstance(self, Holiday):
            return None

        datestr_value = getattr(self, 'datestr', None)
        if isinstance(datestr_value, datetime):
            return datestr_value.isoformat()
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "datestr": self.datestr_str,
            "isholiday": self.isholiday,
            "iscompday": self.iscompday,
            "weekday": self.weekday,
        }


class BugMetric(Base):
    """故障度量模型"""

    __tablename__ = "bug_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255))
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_created_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_resolved_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_open_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class BugMetricByDeveloper(Base):
    """开发人员故障度量模型"""

    __tablename__ = "bug_metrics_by_developer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255))
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    developer_id: Mapped[str] = mapped_column(String(50))
    developer_name: Mapped[str] = mapped_column(String(100))
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_created_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_resolved_count: Mapped[int] = mapped_column(Integer, default=0)
    bug_open_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_resolve_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_finish_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AvgMetricByDay(Base):
    """每日平均故障完成时长模型"""

    __tablename__ = "avg_metric_by_day"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    avg_resolve_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_finish_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "metric_date": self.metric_date.isoformat()
            if self.metric_date is not None
            else None,
            "avg_resolve_time_seconds": self.avg_resolve_time_seconds,
            "avg_finish_time_seconds": self.avg_finish_time_seconds,
            "bug_count": self.bug_count,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }


class AvgMetricByProject(Base):
    """各项目故障平均完成时长模型"""

    __tablename__ = "avg_metric_by_project"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255))
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    avg_resolve_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_finish_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "metric_date": self.metric_date.isoformat()
            if self.metric_date is not None
            else None,
            "avg_resolve_time_seconds": self.avg_resolve_time_seconds,
            "avg_finish_time_seconds": self.avg_finish_time_seconds,
            "bug_count": self.bug_count,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }


class AvgMetricByDeveloper(Base):
    """各开发人员故障平均完成时长模型"""

    __tablename__ = "avg_metric_by_developer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False)
    developer_name: Mapped[str] = mapped_column(String(100))
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    avg_resolve_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_finish_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "developer_id": self.developer_id,
            "developer_name": self.developer_name,
            "metric_date": self.metric_date.isoformat()
            if self.metric_date is not None
            else None,
            "avg_resolve_time_seconds": self.avg_resolve_time_seconds,
            "avg_finish_time_seconds": self.avg_finish_time_seconds,
            "bug_count": self.bug_count,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }


class AvgMetricByProjectDeveloper(Base):
    """各项目各开发人员的故障平均完成时长表"""

    __tablename__ = "avg_metric_by_project_developer"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255))
    developer_id: Mapped[str] = mapped_column(String(50), nullable=False)
    developer_name: Mapped[str] = mapped_column(String(100))
    metric_date: Mapped[datetime] = mapped_column(DateTime)
    avg_resolve_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_finish_time_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    bug_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "developer_id": self.developer_id,
            "developer_name": self.developer_name,
            "metric_date": self.metric_date.isoformat()
            if self.metric_date is not None
            else None,
            "avg_resolve_time_seconds": self.avg_resolve_time_seconds,
            "avg_finish_time_seconds": self.avg_finish_time_seconds,
            "bug_count": self.bug_count,
            "created_at": self.created_at.isoformat()
            if self.created_at is not None
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at is not None
            else None,
        }


class TaskExecutionLog(Base):
    """任务执行记录模型"""

    __tablename__ = "project_task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_configs.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # story_reminder, task_reminder, sonar_reminder, report_data
    scheduled_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 计划执行时间
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))  # 实际执行时间
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending, running, success, failed, expired
    error_message: Mapped[str] = mapped_column(String(500), default="")  # 错误信息
    task_exec_type: Mapped[str] = mapped_column(String(50), nullable=False, default="automatic")  # manual, automatic

    def to_dict(self):
        return {
            "id": self.id,
            "project_config_id": self.project_config_id,
            "task_type": self.task_type,
            "scheduled_time": self.scheduled_time.isoformat()
            if self.scheduled_time
            else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "status": self.status,
            "error_message": self.error_message,
            "task_exec_type": self.task_exec_type,
        }
