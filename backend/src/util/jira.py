from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger("Jira")


# 交互式路径(页面下拉、手动执行入队校验)拉 Sprint 的短超时。
#
# 这两条路径都是「用户在等」的同步请求:RDM 不可达时必须尽快回退本地库 / 报错,
# 不能沿用默认的 60s × 3 次 + 每轮 2s 退避(那是给后台定时任务用的)。
# 前端在这段时间里 options 为空,PrimeVue Select 会直接渲染 "No available options"。
INTERACTIVE_SPRINT_TIMEOUT = 5
INTERACTIVE_SPRINT_RETRIES = 0


def _get_with_retry(
    url: str, headers: dict, *, timeout: int = 60, retries: int = 2
) -> requests.Response:
    """GET 请求 RDM：网络异常、限流(429)、服务端错误(5xx) 自动重试。

    重试耗尽后的行为:
    - 最后一次是网络类异常 ⇒ 抛出该异常(与既有行为一致)
    - 最后一次拿到了响应   ⇒ 原样返回,交由调用方按 status_code 分支
      (ProjectUtil.sprints / active_sprints 就是这么用的,改成抛错会破坏契约)
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        # 每轮重置:避免上一轮的错误响应被当成「最后一次的响应」返回
        resp: requests.Response | None = None
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
        else:
            # 4xx(429 除外)是确定性错误,重试没有意义
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
            last_exc = RuntimeError(f"HTTP {resp.status_code} {resp.reason}")

        if attempt < retries:
            logger.warning(
                "请求 RDM 失败(%s)，第 %s/%s 次重试: %s",
                type(last_exc).__name__,
                attempt + 1,
                retries,
                url,
            )
            time.sleep(2)
            continue

        if resp is not None:
            return resp
        assert last_exc is not None
        raise last_exc


def get_auth_config_from_session(session) -> AuthConfig | None:
    """从给定会话读取全局共享的 JIRA 认证配置(与登录用户无关)。

    已取消「用户-JIRA认证」绑定:凭据是全体用户共用的业务配置。
    表中通常只有一行;多行时取 id 最小的一行,保证结果稳定。

    ⚠ 全仓唯一的查询实现:`api/services/project_configs.get_jira_auth()` 只是
    在它外面包了一层「开 session」。别再复制第二份查询 —— 历史上两份副本就漂移过。
    """
    from db.models import JiraAuthConfig

    auth = session.query(JiraAuthConfig).order_by(JiraAuthConfig.id).first()
    if auth:
        return AuthConfig(user=auth.jira_user, token=auth.jira_token, url=auth.jira_url)
    return None


@dataclass
class AuthConfig:
    """JIRA认证配置"""

    user: str = ""
    token: str = ""
    url: str = "http://rdm.zvos.zoomlion.com"

    @property
    def headers(self):
        auth_str = base64.b64encode(f"{self.user}:{self.token}".encode()).decode(
            "utf-8"
        )
        return {"Authorization": f"Basic {auth_str}"}


# Sprint
@dataclass
class Sprint:
    """Sprint"""

    board_id: str
    board_name: str
    project_id: str
    project_name: str
    sprint_id: str
    origin_sprint_name: str
    sprint_name: str
    short_sprint_name: str
    startdate: str | None
    enddate: str | None
    activated_date: str | None
    complete_date: str | None
    state: str
    goal: str | None
    auth_config: AuthConfig | None = field(default=None)

    def __post_init__(self):
        self.startdate = to_beijing_mysql_datetime(self.startdate)
        self.enddate = to_beijing_mysql_datetime(self.enddate)
        self.activated_date = to_beijing_mysql_datetime(self.activated_date)
        self.complete_date = to_beijing_mysql_datetime(self.complete_date)

    @classmethod
    def from_jira_id(cls, sprint_id: str) -> Sprint:
        """根据 sprint_id 从数据库构造 Sprint 实例"""
        from sqlalchemy import text

        from db.database import get_session

        with get_session() as session:
            query = text(
                """
                SELECT
                    rs.sprint_id, rs.sprint_name, rs.startdate, rs.enddate,
                    rs.state, rs.project_id,
                    rs.short_sprint_name, rs.origin_sprint_name,
                    pc.board_id, pc.board_name, pc.project_name
                FROM rdm_sprint rs
                JOIN project_configs pc ON rs.project_id = pc.project_id
                WHERE rs.sprint_id = :sprint_id
                LIMIT 1
            """
            )
            row = session.execute(query, {"sprint_id": sprint_id}).fetchone()

            if not row:
                raise ValueError(f"未找到 sprint_id={sprint_id} 的 Sprint 数据")

            auth_config = get_auth_config_from_session(session)

            return cls(
                board_id=str(row.board_id),
                board_name=str(row.board_name),
                project_id=str(row.project_id),
                project_name=str(row.project_name),
                sprint_id=str(row.sprint_id),
                origin_sprint_name=row.origin_sprint_name or row.sprint_name or "",
                sprint_name=row.sprint_name or "",
                short_sprint_name=row.short_sprint_name or row.sprint_name or "",
                startdate=row.startdate,
                enddate=row.enddate,
                activated_date=None,
                complete_date=None,
                state=row.state or "",
                goal=None,
                auth_config=auth_config,
            )

    def to_dict(self) -> dict:
        return {
            "sprint_id": self.sprint_id,
            "sprint_name": self.sprint_name,
            "short_sprint_name": self.short_sprint_name,
            "origin_sprint_name": self.origin_sprint_name,
            "board_id": self.board_id,
            "board_name": self.board_name,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "startdate": self.startdate,
            "enddate": self.enddate,
            "activated_date": self.activated_date,
            "complete_date": self.complete_date,
            "state": self.state,
            "goal": self.goal,
        }

    @property
    def auth(self) -> AuthConfig | None:
        """返回当前 Sprint 绑定的认证配置（构造时显式注入）"""
        return self.auth_config

    @property
    def headers(self):
        if self.auth is None:
            raise RuntimeError(
                "Sprint 缺少 auth_config，无法访问 JIRA。请在构造 Sprint 时显式传入 auth_config。"
            )
        return self.auth.headers

    @property
    def api_url(self) -> str:
        if self.auth is None:
            raise RuntimeError(
                "Sprint 缺少 auth_config，无法访问 JIRA。请在构造 Sprint 时显式传入 auth_config。"
            )
        return self.auth.url

    def url(self) -> str:
        return f"{self.api_url}/rest/agile/1.0/board/{self.board_id}/sprint"

    def issues(
        self, issue_types: list[str] | None = None, need_changelog: bool = False
    ) -> list[dict]:
        """通用的获取 issues 的函数(按 startAt 分页取全)

        :param issue_types: 用于筛选 bug 的 JQL 条件（可选）
        :param need_changelog: 是否需要变更日志
        :return: 返回 issues 或 bugs 的列表
        """
        issue_types_param = (
            " AND issuetype in ('{}')".format("','".join(issue_types))
            if issue_types
            else ""
        )
        changelog_param = "&expand=changelog" if need_changelog else ""

        search_url = f"{self.api_url}/rest/api/2/search"
        jql = f"project={self.project_id} AND sprint={self.sprint_id}{issue_types_param}"
        page_size = 500  # 每次请求的最大结果数

        issues: list[dict] = []
        start_at = 0
        while True:
            url = (
                f"{search_url}?jql={jql}&startAt={start_at}"
                f"&maxResults={page_size}{changelog_param}"
            )
            # ⚠ 走统一重试封装;非 200 必须抛错而不是继续循环 ——
            #   历史实现在非 200 时既不 break 也不推进 startAt,会无限重打同一地址。
            resp = _get_with_retry(url, self.headers, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"获取 Sprint {self.sprint_id} 的 issue 失败, "
                    f"HTTP {resp.status_code} {resp.reason} (startAt={start_at})"
                )

            data = resp.json()
            page = data.get("issues") or []
            issues.extend(page)
            total = data.get("total", len(issues))

            # 取完即止;page 为空是防御 —— 上游 total 虚高时不能原地死循环
            if len(issues) >= total or not page:
                break
            start_at += page_size

        return issues

    @property
    def sample_issues(self) -> list[dict]:
        issues = self.issues(["故事", "简单故事", "子任务", "故障"])
        return [
            {
                "issue_key": issue["key"],
                "issue_name": issue["fields"]["summary"],
                "issue_type": issue["fields"]["issuetype"]["name"],
                "duedate": issue["fields"]["duedate"],
                "assignee": (issue["fields"].get("assignee") or {}).get("displayName")
                or None,
                "status": (issue["fields"].get("status") or {}).get("name") or None,
                "story": (issue["fields"].get("parent") or {}).get("key") or None,
            }
            for issue in issues
        ]

    @property
    def sample_tasks(self) -> list[dict]:
        issues = self.issues(["子任务"])
        return [
            {
                "issue_key": issue["key"],
                "issue_name": issue["fields"]["summary"],
                "issue_type": issue["fields"]["issuetype"]["name"],
                "duedate": issue["fields"]["duedate"],
                "assignee": (issue["fields"].get("assignee") or {}).get("displayName")
                or None,
                "status": (issue["fields"].get("status") or {}).get("name") or None,
                "story": (issue["fields"].get("parent") or {}).get("key") or None,
            }
            for issue in issues
        ]

    @property
    def rdm_report_data(self):
        """生成RDM报表数据"""
        issues = self.issues([], need_changelog=True)
        stories = [
            issue
            for issue in issues
            if issue["fields"]["issuetype"]["name"] in ["故事", "简单故事"]
        ]
        bugs = [
            issue for issue in issues if issue["fields"]["issuetype"]["name"] == "故障"
        ]

        report_issues = rdm_report_issues(issues)
        # ⚠ 不能再转一次:activated_date 已在 __post_init__ 归一为
        #   "YYYY-MM-DD HH:MM:SS" 的**北京时间 naive 串**,再过一次
        #   to_beijing_mysql_datetime 会把它按服务器本地时区重新解释,
        #   非 +8 时区下整体平移,is_unplaned 判定随之出错(见下方比较)。
        sprint_active_date = self.activated_date
        for issue in report_issues:
            issue["sprint_id"] = self.sprint_id
            issue["sprint_name"] = self.sprint_name
            issue["sprint_active_date"] = sprint_active_date
            issue["is_unplaned"] = (
                (1 if issue["created"] > sprint_active_date else 0)
                if sprint_active_date
                else None
            )

        report_stories_changelogs = [
            log for story in stories for log in story_changlogs(story)
        ]

        report_bugs_changelogs = [log for bug in bugs for log in bug_changelogs(bug)]
        # 在 report_bugs_changelogs 添加 project_id、project_name、sprint_id、sprint_name
        for changlog in report_bugs_changelogs:
            changlog["project_id"] = self.project_id
            changlog["project_name"] = self.project_name
            changlog["sprint_id"] = self.sprint_id
            changlog["sprint_name"] = self.sprint_name

        return report_issues, report_stories_changelogs, report_bugs_changelogs


@dataclass
class BaseProject:
    """项目提醒配置信息"""

    board_id: str  # 面板ID
    board_name: str  # 面板名称
    project_id: str  # JIRA项目ID
    project_name: str  # JIRA项目名称


@dataclass
class ProjectRemindConfig(BaseProject):
    """项目提醒配置信息"""

    project_config_id: int = 0  # 数据库项目配置ID
    gitlab_group_key: str = ""  # gitlab 项目的group key
    need_story_remind: bool = False  # 是否需要故事提醒
    need_task_remind: bool = False  # 是否需要子任务到期提醒
    need_sonar_scan_remind: bool = False  # 是否需要Sonar扫描提醒
    need_report_data: bool = False  # 是否需要生产RDM报表数据
    sonar_key_prefix: str = ""  # Sonar key 名称前缀（基于项目名称）
    sonar_scan_remind_default_person: str = ""  # Sonar扫描默认提醒人
    robot_key: str = ""  # 企业微信群机器人key
    jira_user: str = ""  # JIRA用户名
    jira_token: str = ""  # JIRA Token
    # 各任务类型的自定义调度时间 (HH:MM格式，留空使用全局默认)
    story_remind_time: str = ""  # 故事提醒时间
    task_remind_time: str = ""  # 任务提醒时间
    sonar_remind_time: str = ""  # Sonar扫描提醒时间

    @property
    def auth_config(self) -> AuthConfig | None:
        """根据当前配置构造 JIRA AuthConfig，若 jira_user/jira_token 缺失返回 None"""
        if self.jira_user and self.jira_token:
            return AuthConfig(user=self.jira_user, token=self.jira_token)
        return None


class ProjectUtil:
    def __init__(
        self,
        project: BaseProject,
        auth_config: AuthConfig | None = None,
        *,
        sprint_timeout: int = 60,
        sprint_retries: int = 2,
    ) -> None:
        self.project = project
        # 优先使用显式传入的 auth_config，其次尝试从 project 上获取（如 ProjectRemindConfig.auth_config）
        if auth_config is None and hasattr(project, "auth_config"):
            auth_config = project.auth_config
        self.auth_config = auth_config
        # Sprint 列表拉取的超时/重试。默认值与 _get_with_retry 保持一致(交互式路径可调小,
        # 详见 reports.py 的 /sprints 端点:那里 RDM 不可达时必须尽快回退本地库)。
        self.sprint_timeout: int = sprint_timeout
        self.sprint_retries: int = sprint_retries

    @property
    def auth(self) -> AuthConfig | None:
        return self.auth_config

    @property
    def headers(self):
        if self.auth is None:
            raise RuntimeError(
                "ProjectUtil 缺少 auth_config，无法访问 JIRA。请在构造时显式传入 auth_config。"
            )
        return self.auth.headers

    @property
    def api_url(self) -> str:
        if self.auth is None:
            raise RuntimeError(
                "ProjectUtil 缺少 auth_config，无法访问 JIRA。请在构造时显式传入 auth_config。"
            )
        return self.auth.url

    def url(self):
        return f"{self.api_url}/rest/agile/1.0/board/{self.project.board_id}/project"

    def sprint_to_obj(self, sprint) -> Sprint | None:
        import re

        def sprint_name(name):
            """格式化Sprint名称"""
            return re.sub(
                r"\s+", "-", re.sub(r"Sprint\s+", "Sprint", name, flags=re.IGNORECASE)
            )

        def short_sprint_name(name):
            """格式化Sprint名称(短名称):统一提取 Sprint 后序号为 Sprint{数字}。
            兼容多种样式,如 JSST-1.0-Sprint-10 -> Sprint10、MOWING Sprint 1 -> Sprint1、botadp-Sprint-1 -> Sprint1。"""
            if name.startswith("md-dc-sp"):
                return "Sprint" + name[len("md-dc-sp") :]
            match = re.search(r"Sprint\s*[-_]?\s*(\d+)", name, flags=re.IGNORECASE)
            return f"Sprint{match.group(1)}" if match else sprint_name(name)

        # 过滤掉不等于参数board_id的数据(之前建错在了其他项目下), 过滤掉cmp项目中以CMP开头的迭代
        if str(sprint.get("originBoardId")) == self.project.board_id and not (
            self.project.board_id == "892" and sprint["name"].startswith("CMP")
        ):
            return Sprint(
                board_id=self.project.board_id, board_name=self.project.board_name, project_id=self.project.project_id, project_name=self.project.project_name, sprint_id=sprint["id"], origin_sprint_name=sprint["name"], sprint_name=sprint_name(sprint["name"]), short_sprint_name=short_sprint_name(sprint["name"]), startdate=sprint.get("startDate", None), enddate=sprint.get("endDate", None), activated_date=sprint.get("activatedDate", None), complete_date=sprint.get("completeDate", None), state=sprint["state"], goal=sprint.get("goal") or None, auth_config=self.auth_config
            )

    @property
    def sprints(self) -> list[Sprint] | None:
        url = f"{self.api_url}/rest/agile/1.0/board/{self.project.board_id}/sprint"
        response = _get_with_retry(
            url,
            self.headers,
            timeout=self.sprint_timeout,
            retries=self.sprint_retries,
        )
        sprint_objs = []
        if response.status_code == 200 and response.json()["values"]:
            for sprint in response.json()["values"]:
                obj = self.sprint_to_obj(sprint)
                if obj:
                    sprint_objs.append(obj)
        elif response.status_code != 200:
            logger.warning(
                "从 RDM 获取项目 %s 的 Sprint 失败, HTTP %s %s (url=%s)",
                self.project.board_name or self.project.board_id,
                response.status_code,
                response.reason,
                url,
            )
        return sprint_objs

    @property
    def active_sprints(self) -> list[Sprint] | None:
        """获取激活中的Sprint"""
        url = f"{self.api_url}/rest/agile/1.0/board/{self.project.board_id}/sprint?state=active"
        response = _get_with_retry(url, self.headers)
        if response.status_code == 200 and response.json()["values"]:
            return [
                s
                for s in [
                    self.sprint_to_obj(sprint) for sprint in response.json()["values"]
                ]
                if s is not None
            ]
        else:
            if response.status_code != 200:
                logger.warning(
                    "获取项目 %s 的激活 Sprint 失败, HTTP %s %s (url=%s)",
                    self.project.board_name or self.project.board_id,
                    response.status_code,
                    response.reason,
                    url,
                )
            return []


def to_beijing_mysql_datetime(iso_str: str | None) -> str | None:
    """
    将ISO时间字符串转换为北京时间的MySQL DATETIME格式（无毫秒）
    Args:
        iso_str: ISO 8601格式时间字符串（如 "2025-04-29T09:03:00.000+08:00"）
    Returns:
        str: MySQL兼容的北京时间字符串，格式 "YYYY-MM-DD HH:MI:SS"
    """
    if not iso_str:
        return None
    from datetime import datetime, timedelta, timezone

    if isinstance(iso_str, datetime):
        # 来自 SQLAlchemy/PyMySQL 的 DATETIME 列,已经是 datetime 对象
        dt = iso_str
    else:
        # 修正时区格式（+0800 -> +08:00）
        if "+" in iso_str and ":" not in iso_str[-5:]:
            iso_str = f"{iso_str[:-2]}:{iso_str[-2:]}"
        dt = datetime.fromisoformat(iso_str)  # 此时格式为 "2025-02-28T14:40:58.000+08:00"
    beijing_tz = timezone(timedelta(hours=8))
    beijing_time = dt.astimezone(beijing_tz)
    return beijing_time.strftime("%Y-%m-%d %H:%M:%S")


def story_changlogs(story):
    """处理故事中的变更记录"""
    story_id = story["id"]
    story_key = story["key"]
    # 表 rdm_story_changelog 对应字段名为 complete_time,需与报表查询 SQL 保持一致
    complete_time = to_beijing_mysql_datetime(
        story["fields"].get("resolutiondate", None)
    )
    author = story["fields"]["creator"]["displayName"]
    change_time = to_beijing_mysql_datetime(story["fields"]["created"])

    # 添加创建日志
    story_changelogs = [
        {
            "log_id": 1,
            "story_id": story_id,
            "story_key": story_key,
            "complete_time": complete_time,
            "author": author,
            "change_time": change_time,
            "change_detail": "创建",
        }
    ]
    # 添加变更日志
    for log in story["changelog"]["histories"]:
        for item in log["items"]:
            if item["field"] == "status":
                story_changelogs.append(
                    {
                        "log_id": log["id"],
                        "story_id": story_id,
                        "story_key": story_key,
                        "complete_time": complete_time,
                        "author": log["author"]["displayName"],
                        "change_time": to_beijing_mysql_datetime(log["created"]),
                        "change_detail": f"从 {item['fromString']} 变更为 {item['toString']}",
                    }
                )
    return story_changelogs


def bug_changelogs(bug):
    def log_type_detail(log):
        # 检查 items 列表中是否存在 field 为 "status" 的元素
        status_item = next(
            (item for item in log["items"] if item.get("field") == "status"), None
        )
        if status_item:
            _type = "status"
            _detail = (
                status_item.get("fromString") + " -> " + status_item.get("toString")
            )
        else:
            first_item = log["items"][0]
            _type = first_item.get("field")
            if _type in ["summary", "description"]:
                _detail = None
            else:
                _detail = (
                    (first_item.get("fromString") or "")
                    + " -> "
                    + (first_item.get("toString") or "")
                )
        return _type, _detail

    """处理BUG中的变更记录"""
    assignee = (bug["fields"].get("assignee") or {}).get("displayName") or None
    bug_solver = (bug["fields"].get("customfield_11700") or {}).get(
        "displayName"
    ) or assignee

    # 添加创建日志
    changelogs = [
        {
            "log_id": "1",
            "bug_id": bug["id"],
            "bug_key": bug["key"],
            "bug_name": bug["fields"]["summary"],
            "bug_solver": bug_solver,
            "author": bug["fields"]["creator"]["displayName"],
            "change_time": to_beijing_mysql_datetime(bug["fields"]["created"]),
            "change_type": "create",
            "change_detail": None,
        }
    ]

    # 添加变更日志
    logs = bug["changelog"]["histories"]
    if logs:
        for _log in logs:
            change_type, change_detail = log_type_detail(_log)
            changelogs.append(
                {
                    "log_id": _log["id"],
                    "bug_id": bug["id"],
                    "bug_key": bug["key"],
                    "bug_name": bug["fields"]["summary"],
                    "bug_solver": bug_solver,
                    "author": _log["author"]["displayName"],
                    "change_time": to_beijing_mysql_datetime(_log["created"]),
                    "change_type": change_type,
                    "change_detail": change_detail,
                }
            )
    return changelogs


def _seconds_to_hours(value) -> float | None:
    """秒 → 小时(保留两位小数)。

    RDM 的工时字段(timeoriginalestimate / timespent / timetracking)以**秒**为单位,
    而库表 rdm_issue.plan_worktime / actual_worktime 是 float「工时」(见 sql/init_ddl.sql
    的列注释),故在此换算。取不到值一律返回 None 而**不是 0** —— 报表侧需要区分
    「该 Sprint 未接入工时数据」与「确实为 0 工时」,前者前端渲染为预留态。
    """
    if value is None:
        return None
    try:
        return round(int(value) / 3600, 2)
    except (TypeError, ValueError):
        return None


def _issue_worktime(_fields: dict) -> tuple[float | None, float | None]:
    """取单条 issue 的 (计划工时, 实际工时),单位为小时。

    只取 issue **自身**的估算/登记值,不用 aggregate* —— 父项(故事)的聚合值已包含其子任务,
    而子任务在本系统里会作为独立行落库,用聚合值会重复计入同一 Sprint 的工时合计。
    RDM 的 /search 在扁平字段与 timetracking 对象两处都可能给值,故各留一条回退。
    """
    timetracking = _fields.get("timetracking") or {}
    plan_seconds = _fields.get("timeoriginalestimate")
    if plan_seconds is None:
        plan_seconds = timetracking.get("originalEstimateSeconds")
    actual_seconds = _fields.get("timespent")
    if actual_seconds is None:
        actual_seconds = timetracking.get("timeSpentSeconds")
    return _seconds_to_hours(plan_seconds), _seconds_to_hours(actual_seconds)


def rdm_report_issues(issues):
    result = []
    for _issue in issues:
        _fields = _issue.get("fields", {})
        _created = to_beijing_mysql_datetime(_fields.get("created"))
        _updated = to_beijing_mysql_datetime(_fields.get("updated"))
        _plan_worktime, _actual_worktime = _issue_worktime(_fields)

        result.append(
            {
                "issue_id": _issue.get("id"),
                "sprint_id": None,
                "sprint_name": None,
                "issue_key": _issue.get("key"),
                "issue_type": _fields["issuetype"]["name"],
                "issue_name": _fields["summary"],
                "reporter": _fields["reporter"]["displayName"],
                "assignee": (_fields.get("assignee") or {}).get("displayName") or None,
                "created": _created,
                "updated": _updated,
                "description": _fields["description"],
                "status": _fields["status"]["name"],
                "resolution": (_fields.get("resolution") or {}).get("name") or None,
                "priority": (_fields.get("priority") or {}).get("name") or None,
                "require_type": (_fields.get("customfield_11302") or {}).get("value")
                or None,
                "callback": int(val)
                if (val := _fields.get("customfield_11300")) is not None
                else None,
                "developer": (_fields.get("customfield_11506") or {}).get("displayName")
                or None,
                "tester": (_fields.get("customfield_11304") or {}).get("displayName")
                or None,
                "duedate": _fields.get("duedate") or None,
                "module": ", ".join(
                    comp["name"] for comp in _fields.get("components", [])
                )
                or None,
                "bug_story": (_fields.get("parent") or {}).get("key") or None,
                "bug_type": (_fields.get("customfield_10303") or {}).get("value")
                or None,
                "bug_flag": (_fields.get("labels") or [None])[0],
                "bug_reason": (
                    f"{v['value']} - {v['child']['value']}"
                    if (v := _fields.get("customfield_11400"))
                    else None
                ),
                "bug_solver": (_fields.get("customfield_11700") or {}).get(
                    "displayName"
                )
                or None,
                "bug_maker": (_fields.get("customfield_11307") or {}).get("displayName")
                or None,
                "is_unplaned": None,
                "sprint_active_date": None,
                "plan_worktime": _plan_worktime,
                "actual_worktime": _actual_worktime,
            }
        )
    return result
