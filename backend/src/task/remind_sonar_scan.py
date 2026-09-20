import logging
import os
from datetime import datetime, timedelta

import requests

from config.project_sonar_key_map import ZHKS_SONAR_KEY_MAP
from util.dateattr import DateAttr
from util.jira import ProjectRemindConfig

logger = logging.getLogger(__name__)

# 外部服务凭据统一从环境变量读取,缺失即拒绝运行,绝不静默放行。
_REMIND_SONAR_REQUIRED_ENV = (
    "GITLAB_URL",
    "GITLAB_TOKEN",
    "GITLAB_USERNAME",
    "SONAR_URL",
    "SONAR_TOKEN",
)
for _key in _REMIND_SONAR_REQUIRED_ENV:
    if not os.getenv(_key):
        raise RuntimeError(
            f"环境变量 {_key} 未设置,无法运行 remind_sonar_scan 任务。"
            f"请在 backend/.env 中配置 {_key}=...,示例见 .env.example。"
        )


def get_debug_configs():
    """获取调试用的项目配置（从数据库）"""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from api.scheduler import get_project_configs

    return get_project_configs()


def get_debug_config(board_id: str):
    """获取指定board_id的调试配置"""
    configs = get_debug_configs()
    for config in configs:
        if config.board_id == board_id:
            return config
    return None


dateattr = DateAttr()


# GITLAB 配置信息（从环境变量读取）
GITLAB_URL = os.environ["GITLAB_URL"]
GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
GITLAB_USERNAME = os.environ["GITLAB_USERNAME"]
GROUP_KEY_MAP = {
    "cmp": "数据工具链平台",
    "mowing": "割草机器人",
    "dms": "调度系统",
}  # GitLab Group ID
GITLAB_HEADERS = {"Private-Token": GITLAB_TOKEN}

# SONAR 配置信息（从环境变量读取）
SONAR_URL = os.environ["SONAR_URL"]
SONAR_TOKEN = os.environ["SONAR_TOKEN"]
SONAR_AUTH = (SONAR_TOKEN, "")
# 获取项目的API
PROJECTS_API = f"{SONAR_URL}/api/projects/search"
# 获取分支列表的API
BRANCHES_API = f"{SONAR_URL}/api/project_branches/list"
MEASURES_API = f"{SONAR_URL}/api/measures/component"
ISSUES_API = f"{SONAR_URL}/api/issues/search"
CMP_PROJECTS_MANAGER = {
    "cmp-basedata-service": ["宋程杰", "刘珏"],
    "cmp-channel-api-service": ["宋程杰", "王楷涵"],
    "cmp-channel-websocket-service": ["宋程杰", "王楷涵"],
    "cmp-collectoragent-service": ["刘珏"],
    "cmp-data-annotation-image-tool": ["李若谷"],
    "cmp-data-annotation-pc-tool": ["李若谷"],
    "cmp-data-annotation-service": ["罗博声"],
    "cmp-data-annotation-text-tool": ["李若谷"],
    "cmp-data-annotation-web": ["李若谷"],
    "cmp-data-process-service": ["彭南科"],
    "cmp-edgefile-service": ["刘珏", "丁玄"],
    "cmp-edge-service": ["刘珏", "丁玄"],
    "cmp-image-algorithm-service": ["罗博声"],
    "cmp-pointcloud-algorithm-service": ["罗博声"],
    "cmp-train-service": ["宋程杰", "刘珏"],
    "cmp-statistics-service": ["宋程杰"],
    "data-collection-client": ["刘珏", "丁玄"],
    "md-data-collector": ["唐柳"],
    "md-datacollector-web": ["向键"],
    "dolphinscheduler": ["彭南科"],
    "storage-management-service": ["王超"],
    "cmp-empty-web": ["李若谷"],
    "cmp-oss-base": ["刘珏"],
}


def remove_prefix(text, prefix):
    return text.removeprefix(prefix)


def gitlab_get_group_projects(group_key):
    """获取指定group的所有项目（自动处理分页）"""
    url = f"{GITLAB_URL}/api/v4/groups/{group_key}/projects"
    headers = GITLAB_HEADERS
    params = {"per_page": 200}  # 每页最大记录数
    projects = []

    while url:  # 初始URL不为空，后续由分页链接更新
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            # ⚠ 静默 break 会返回**不完整**的项目列表而不自知,必须留下痕迹
            logger.warning(
                "获取 GitLab group %s 的项目失败, HTTP %s %s (url=%s),已取 %s 个",
                group_key,
                response.status_code,
                response.reason,
                url,
                len(projects),
            )
            break

        projects.extend(response.json())
        next_url = response.links.get("next", {}).get("url")  # 获取下一页URL
        # 防御:上游若把 next 指回当前页,会导致死循环
        if next_url == url:
            logger.warning("GitLab 分页 next 指回当前页,已中止: %s", url)
            break
        url = next_url
    # 过滤名称为release 或 project-doc的项目
    return [
        p
        for p in projects
        if "release" != p["name"]
        and "project-doc" != p["name"]
        and "repo-lib" != p["name"]
        and "alg" != p["name"]
        and "mowing-web" != p["name"]
        and "md-docs-web" != p["name"]
    ]


def gitlab_get_project_branches(project_id):
    """从 GitLab 获取指定项目的所有分支;非 200 返回 [](不再把错误体丢给上游)。

    历史实现直接 `return response.json()`:非 200 时返回的是错误对象(dict),
    上游按列表遍历会取 `branch["commit"]` 直接 TypeError,把一次 HTTP 故障
    伪装成解析崩溃。
    """
    url = f"{GITLAB_URL}/api/v4/projects/{project_id}/repository/branches"
    response = requests.get(url, headers=GITLAB_HEADERS, timeout=30)
    if response.status_code != 200:
        logger.warning(
            "获取 GitLab 项目 %s 的分支失败, HTTP %s %s",
            project_id,
            response.status_code,
            response.reason,
        )
        return []
    return response.json()


def gitlab_get_project_commitdate(project_id):
    """获取项目整个仓库最新提交时间"""
    branches = gitlab_get_project_branches(project_id)
    latest_commitdate = None
    if branches:
        for branch in branches:
            branch_commitdate = branch["commit"]["committed_date"]
            if branch_commitdate is not None and (
                latest_commitdate is None or branch_commitdate > latest_commitdate
            ):
                latest_commitdate = branch_commitdate
    return (
        datetime.strptime(latest_commitdate[0:10], "%Y-%m-%d").date()
        if latest_commitdate
        else None
    )


def gitlab_get_projects_commitdate(group_projects):
    """获取项目的最新提交日期"""
    projects = {}
    for item in group_projects:
        project = item[0]
        latest_commitdate = gitlab_get_project_commitdate(project["id"])
        projects[project["name"]] = latest_commitdate
    return projects


def sonar_check_project_exists(project_key):
    """检查 SonarQube 项目是否存在"""
    try:
        response = requests.get(
            PROJECTS_API,
            params={"projects": project_key},
            headers={"Authorization": f"Bearer {SONAR_TOKEN}"},
            timeout=30,
        )
        response.raise_for_status()  # 检查 HTTP 错误
        data = response.json()
        if "projects" in data:
            for project in data["projects"]:
                if project["key"] == project_key:
                    return True
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"查询失败: {e}")
        return False


def sonar_get_project_branches(project_key):
    """获取指定项目的所有分支列表"""
    _res = requests.get(BRANCHES_API, params={"project": project_key}, auth=SONAR_AUTH, timeout=30)
    if _res.status_code == 200:
        branches = _res.json().get("branches", [])
        return branches
    else:
        logger.info(
            f"[Warning] 获取项目'{project_key}' 的分支失败: {_res.status_code}, {_res.text}"
        )
        return None


def sonar_get_project_scandate(project_branches):
    """获取项目的最近一次分析时间"""
    latest_scan_branch, latest_scan_date = None, None
    if not project_branches:
        return latest_scan_branch, latest_scan_date
    for branch in project_branches:
        branch_analysisdate = branch.get("analysisDate", None)
        if branch_analysisdate is not None and (
            latest_scan_date is None or branch_analysisdate > latest_scan_date
        ):
            latest_scan_branch = branch
            latest_scan_date = branch_analysisdate
    # 改成北京时间
    if latest_scan_date:
        latest_scan_date = (
            datetime.strptime(latest_scan_date[0:19], "%Y-%m-%dT%H:%M:%S")
            + timedelta(hours=8)
        ).date()
    return latest_scan_branch, latest_scan_date


def sonar_get_branch_bug_cnt(project_key, branch_name, islatest="false"):
    response = requests.get(
        ISSUES_API,
        params={
            "componentKeys": project_key,
            "types": "BUG",
            "resolved": "false",
            "branch": branch_name,
            "sinceLeakPeriod": islatest,  # 是否查询最近一次分析之后的缺陷
        },
        auth=SONAR_AUTH,
        timeout=30,
    )
    if response.status_code == 200:
        return response.json().get("total", 0)
    else:
        logger.info(
            f"[Warning] 查询项目 {project_key} 分支 {branch_name} 的BUG数失败'': {response.status_code}"
        )
        return None


def sonar_get_project_bug_cnt(project_key, project_branches):
    """获取项目的所有分支的BUG数"""
    cnt = 0
    for branch in project_branches:
        branch_bug_cnt = sonar_get_branch_bug_cnt(project_key, branch["name"])
        if branch_bug_cnt:
            cnt += branch_bug_cnt
    return cnt


def sonar_projects_bug_count(projects):
    """从 SonarQuebe 获取所有项目的缺陷数量"""
    projects_bug_count = {}
    for item in projects:
        project = item[0]
        sonar_project_key = item[1]
        branches = sonar_get_project_branches(sonar_project_key)
        bugs_cnt = (
            sonar_get_project_bug_cnt(sonar_project_key, branches) if branches else 0
        )
        if bugs_cnt:
            projects_bug_count[project["name"]] = bugs_cnt
        else:
            projects_bug_count[project["name"]] = 0
    return projects_bug_count


def sonar_get_projects_scan_info(projects):
    """从 SonarQube 获取所有项目本周最近的扫描日期"""
    projects_scan_info = {}
    for item in projects:
        project = item[0]
        sonar_project_key = item[1]
        branches = sonar_get_project_branches(sonar_project_key)
        latest_scan_branch, latest_scan_date = sonar_get_project_scandate(branches)
        projects_scan_info[project["name"]] = (latest_scan_branch, latest_scan_date)
    return projects_scan_info


def sonar_get_project_key(gitlab_group_key, sonar_key_prefix, project_name):
    """根据 group_key 和 project_name 拼接 sonar_project_key"""
    if gitlab_group_key == "zhks":
        sonar_project_key = ZHKS_SONAR_KEY_MAP[project_name]
    else:
        if sonar_key_prefix and sonar_key_prefix.startswith("-"):
            sonar_project_key = remove_prefix(project_name, sonar_key_prefix[1:])
        elif sonar_key_prefix and not sonar_key_prefix.startswith("-"):
            sonar_project_key = sonar_key_prefix + project_name
        else:
            sonar_project_key = project_name
    return sonar_project_key


def gene_message(config: ProjectRemindConfig):
    gitlab_group_key = config.gitlab_group_key
    sonar_remind_person = config.sonar_scan_remind_default_person

    gitlab_group_projects = gitlab_get_group_projects(gitlab_group_key)
    # 智慧矿山特殊处理：只取有与sonar key有映射关系的项目
    if gitlab_group_key == "zhks":
        gitlab_group_projects = [
            item
            for item in gitlab_group_projects
            if item["name"] in ZHKS_SONAR_KEY_MAP.keys()
        ]

    gitlab_group_projects = [
        (
            project,
            sonar_get_project_key(
                gitlab_group_key, config.sonar_key_prefix, project["name"]
            ),
        )
        for project in gitlab_group_projects
    ]

    # 获取所有项目在gitlab上的最新提交日期
    projects_commitdate = gitlab_get_projects_commitdate(gitlab_group_projects)

    # 获取有BUG的项目, 获取本周有进行sonar分析的项目
    # projects_bug_count = sonar_projects_bug_count(gitlab_group_projects)
    projects_scan_info = sonar_get_projects_scan_info(gitlab_group_projects)

    message = ""
    for item in gitlab_group_projects:
        porject = item[0]
        sonar_project_key = item[1]
        project_name = porject["name"]
        # bug_cnt = projects_bug_count.get(project_name, 0)
        latest_commit_date = projects_commitdate.get(project_name) or None
        commit_in_this_week = (
            dateattr.firstday_of_week <= latest_commit_date <= dateattr.lastday_of_week
            if latest_commit_date
            else False
        )
        scan_info = projects_scan_info.get(project_name) or None
        latest_scan_branch = scan_info[0] if scan_info else None
        latest_scan_date = scan_info[1] if scan_info else None
        latest_scan_branch_bug_cnt = sonar_get_branch_bug_cnt(
            sonar_project_key, latest_scan_branch, "true"
        )
        scan_in_this_week = (
            dateattr.firstday_of_week <= latest_scan_date <= dateattr.lastday_of_week
            if latest_scan_date
            else False
        )

        date_message = (
            f"(最近提交日期 {latest_commit_date}, 最近扫描日期 {latest_scan_date})"
        )
        scan_message = (
            '<font color="warning">从未扫描</font>'
            if not latest_scan_date
            else (
                '<font color="warning">未扫描</font>'
                if commit_in_this_week and not scan_in_this_week
                else ""
            )
        )
        bug_message = (
            f'<font color="warning">, 且存在{latest_scan_branch_bug_cnt}个缺陷</font>'
            if latest_scan_branch_bug_cnt
            and latest_scan_branch_bug_cnt > 0
            and scan_message
            else (
                f'<font color="warning">存在{latest_scan_branch_bug_cnt}个缺陷</font>'
                if latest_scan_branch_bug_cnt and latest_scan_branch_bug_cnt > 0
                else ""
            )
        )

        if gitlab_group_key == "cmp":
            project_manager = (
                " ".join(
                    [
                        f"<@{manager}>"
                        for manager in CMP_PROJECTS_MANAGER.get(project_name, [])
                    ]
                )
                if CMP_PROJECTS_MANAGER.get(project_name, [])
                else sonar_remind_person
            )
        else:
            project_manager = sonar_remind_person

        if scan_message + bug_message:
            message += (
                "> "
                + f'<font color="blue">{project_name}</font>'
                + " "
                + scan_message
                + bug_message
                + " "
                + date_message
                + " "
                + project_manager
                + "\n"
            )
    if message:
        message = "## SONAR 扫描情况" + "\n" + message
    return message


def debug_all():
    for congfig in get_debug_configs():
        if not congfig.need_sonar_scan_remind:
            logger.info(f"{congfig.project_name} 不需要Sonar扫描提醒")
            continue
        message = gene_message(congfig)
        logger.info(message or f"{congfig.project_name} 无Sonar扫描异常")


def debug_one():
    congfig = get_debug_config("892")  # 智慧矿山
    if congfig:
        message = gene_message(congfig)
        logger.info(message)
    else:
        logger.info("未找到board_id=892的项目配置")


if __name__ == "__main__":
    debug_one()
