import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auth import get_current_user_from_header
from db.database import get_session
from db.models import ProjectConfig, ProjectReminderSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目配置"])


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# 列表接口对 robot_key 的掩码形态(见 db/models.py 的 mask_robot_key)
_MASKED_SECRET_RE = re.compile(r"^.{4}\*{4}.{4}$")


def _looks_masked(value) -> bool:
    """判断值是否形如列表接口吐出的掩码(如 abcd****wxyz)。"""
    return isinstance(value, str) and bool(_MASKED_SECRET_RE.match(value))


def _validate_hhmm(value: str | None) -> str | None:
    """校验 HH:MM 格式，允许 None / 空字符串（表示未配置）"""
    if value is None or value == "":
        return value
    if not _HHMM_RE.match(value):
        raise ValueError("时间格式必须为 HH:MM（24小时制），如 09:30 / 18:00")
    return value


class ProjectReminderSettingsCreate(BaseModel):
    need_story_remind: bool = False
    need_task_remind: bool = False
    need_sonar_scan_remind: bool = False
    need_report_data: bool = False
    # 各任务类型的自定义调度时间 (HH:MM格式)
    story_remind_time: str | None = None
    task_remind_time: str | None = None
    sonar_remind_time: str | None = None

    @field_validator("story_remind_time", "task_remind_time", "sonar_remind_time")
    @classmethod
    def _check_time_format(cls, v: str | None) -> str | None:
        return _validate_hhmm(v)


class ProjectConfigCreate(BaseModel):
    board_id: str
    board_name: str
    project_id: str
    project_name: str
    gitlab_group_key: str = ""
    sonar_key_prefix: str = ""
    sonar_scan_remind_default_person: str = ""
    robot_key: str = ""
    jira_user: str = ""
    jira_token: str = ""
    reminder_settings: ProjectReminderSettingsCreate | None = None


class ProjectConfigUpdate(BaseModel):
    board_name: str | None = None
    board_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    gitlab_group_key: str | None = None
    sonar_key_prefix: str | None = None
    sonar_scan_remind_default_person: str | None = None
    robot_key: str | None = None
    jira_user: str | None = None
    jira_token: str | None = None
    reminder_settings: ProjectReminderSettingsCreate | None = None


class ProjectReminderSettingsResponse(BaseModel):
    id: int
    project_config_id: int
    need_story_remind: bool
    need_task_remind: bool
    need_sonar_scan_remind: bool
    need_report_data: bool
    story_remind_time: str | None = None
    task_remind_time: str | None = None
    sonar_remind_time: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectConfigResponse(BaseModel):
    id: int
    board_id: str
    board_name: str
    project_id: str
    project_name: str
    gitlab_group_key: str
    sonar_key_prefix: str
    sonar_scan_remind_default_person: str
    robot_key: str
    jira_user: str
    need_story_remind: bool = False
    need_task_remind: bool = False
    need_sonar_scan_remind: bool = False
    need_report_data: bool = False
    story_remind_time: str | None = None
    task_remind_time: str | None = None
    sonar_remind_time: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("", response_model=list[ProjectConfigResponse])
async def list_projects(current_user: dict = Depends(get_current_user_from_header)):
    """获取项目列表(所有用户共享,返回全部项目)"""
    with get_session() as session:
        projects = session.query(ProjectConfig).all()
        return [p.to_dict(include_token=False) for p in projects]


@router.get("/{project_id}", response_model=ProjectConfigResponse)
async def get_project(
    project_id: int, current_user: dict = Depends(get_current_user_from_header)
):
    """获取单个项目详情"""
    with get_session() as session:
        project = (
            session.query(ProjectConfig).filter(ProjectConfig.id == project_id).first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        # 详情接口返回 robot_key 明文:编辑表单需要真实值回显(见 to_dict 的说明)
        return project.to_dict(include_token=True, mask_robot_key=False)


@router.post("", response_model=ProjectConfigResponse)
async def create_project(
    config: ProjectConfigCreate,
    current_user: dict = Depends(get_current_user_from_header),
):
    """创建新项目配置"""
    with get_session() as session:
        # 检查 board_id 是否已存在
        existing = (
            session.query(ProjectConfig)
            .filter(ProjectConfig.board_id == config.board_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Board ID 已存在")

        # 检查 project_id 是否已存在
        existing = (
            session.query(ProjectConfig)
            .filter(ProjectConfig.project_id == config.project_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Project ID 已存在")

        # 创建项目配置
        new_project = ProjectConfig(
            board_id=config.board_id,
            board_name=config.board_name,
            project_id=config.project_id,
            project_name=config.project_name,
            gitlab_group_key=config.gitlab_group_key,
            sonar_key_prefix=config.sonar_key_prefix,
            sonar_scan_remind_default_person=config.sonar_scan_remind_default_person,
            robot_key=config.robot_key,
            jira_user=config.jira_user,
            jira_token=config.jira_token,
        )
        session.add(new_project)
        session.flush()  # 获取项目ID

        # 创建提醒设置
        if config.reminder_settings:
            rs = config.reminder_settings
            reminder_settings = ProjectReminderSettings(
                project_config_id=new_project.id,
                need_story_remind=rs.need_story_remind,
                need_task_remind=rs.need_task_remind,
                need_sonar_scan_remind=rs.need_sonar_scan_remind,
                need_report_data=rs.need_report_data,
                story_remind_time=getattr(rs, "story_remind_time", None),
                task_remind_time=getattr(rs, "task_remind_time", None),
                sonar_remind_time=getattr(rs, "sonar_remind_time", None),
            )
            session.add(reminder_settings)

        session.commit()
        session.refresh(new_project)

        return new_project.to_dict()


@router.put("/{project_id}", response_model=ProjectConfigResponse)
async def update_project(
    project_id: int,
    config: ProjectConfigUpdate,
    current_user: dict = Depends(get_current_user_from_header),
):
    """更新项目配置"""
    with get_session() as session:
        project = (
            session.query(ProjectConfig).filter(ProjectConfig.id == project_id).first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        # 更新项目字段
        update_data = config.model_dump(exclude_unset=True)

        # 分离提醒设置和项目配置
        reminder_settings_data = update_data.pop("reminder_settings", None)

        # 将 reminder_settings_data 转换为 dict（如果是 Pydantic 模型）
        if reminder_settings_data is not None and hasattr(
            reminder_settings_data, "model_dump"
        ):
            reminder_settings_data = reminder_settings_data.model_dump(
                exclude_unset=True
            )

        for key, value in update_data.items():
            if key == "reminder_settings":
                continue
            # 防御:列表接口对 robot_key 脱敏,若调用方把掩码原样回传,绝不能写进库
            # (否则真实 webhook key 会被 "abcd****wxyz" 覆盖,企微推送直接失效)
            if key == "robot_key" and _looks_masked(value):
                logger.warning(
                    "忽略疑似脱敏值的 robot_key 更新: project_id=%s", project_id
                )
                continue
            if hasattr(project, key):
                setattr(project, key, value)

        # 更新提醒设置
        if reminder_settings_data is not None:
            existing_settings = (
                session.query(ProjectReminderSettings)
                .filter(ProjectReminderSettings.project_config_id == project_id)
                .first()
            )

            if existing_settings:
                for key, value in reminder_settings_data.items():
                    if hasattr(existing_settings, key):
                        setattr(existing_settings, key, value)
            elif reminder_settings_data:
                # 如果之前没有设置，创建新的
                new_settings = ProjectReminderSettings(
                    project_config_id=project_id,
                    **reminder_settings_data,
                )
                session.add(new_settings)

        session.commit()
        session.refresh(project)

        return project.to_dict()


@router.delete("/{project_id}")
async def delete_project(
    project_id: int, current_user: dict = Depends(get_current_user_from_header)
):
    """删除项目配置"""
    with get_session() as session:
        project = (
            session.query(ProjectConfig).filter(ProjectConfig.id == project_id).first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        session.delete(project)
        session.commit()

        return {"message": "项目已删除"}
