import logging

from util.color import blue_b, grey, warn_b
from util.dateattr import DateAttr
from util.jira import ProjectRemindConfig, ProjectUtil

logger = logging.getLogger(__name__)


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


def gene_overall_progress_message(stories, tasks, todo_bugs):
    """生成整体进度信息"""
    from collections import Counter

    # 整体进度中故事的数据字符串
    stores_str = f"> 1. 故事 {blue_b(len(stories))} 个"
    if stories:
        stories_status_counter = Counter(story["status"] for story in stories).items()
        stores_str += (
            " ( "
            + " | ".join(f"{k}{warn_b(v)}" for k, v in stories_status_counter)
            + " )"
        )

    # 整体进度中子任务的数据字符串
    tasks_str = f"> 2. 子任务 {blue_b(len(tasks))} 个"
    if tasks:
        tasks_staus_counter = Counter(task["status"] for task in tasks).items()
        tasks_str += (
            " ( " + " | ".join(f"{k}{warn_b(v)}" for k, v in tasks_staus_counter) + " )"
        )

    # 整体进度中未解决bug的数据字符串
    bugs_str = f"> 3. 未解决故障 {blue_b(len(todo_bugs))} 个"
    todo_bugs_assignee_counter = Counter(
        "<@" + bug["assignee"] + ">" for bug in todo_bugs if bug["assignee"]
    ).items()
    if todo_bugs:
        bugs_str += (
            " ( "
            + " | ".join(
                f"{assignee}{warn_b(cnt)}"
                for assignee, cnt in todo_bugs_assignee_counter
            )
            + " )"
        )

    # 返回整体进度字符串
    return (
        "> ** 整体进度 ** \n" + stores_str + "\n" + tasks_str + "\n" + bugs_str + "\n"
    )


def gene_this_week_todo_stories_message(stories, todo_tasks):
    """生成本周待完成故事数据信息"""
    from collections import defaultdict

    valid_story_keys = {item["story"] for item in todo_tasks}

    assignee_dict = defaultdict(set)
    max_duedate_dit = defaultdict(list)

    for item in todo_tasks:
        story = item["story"]
        # 1. 收集assignee（带@标记）
        assignee_dict[story].add(f"<@{item['assignee']}>")

        # 2. 更新最大duedate
        current_date = item.get("duedate", "")  # 获取当前duedate，假设可能为空
        if current_date:  # 只处理非空日期
            if not max_duedate_dit[story] or current_date > max_duedate_dit[story]:
                max_duedate_dit[story] = current_date

    todo_stories = [
        {
            "name": item["issue_name"],
            "assignees": " ".join(assignee_dict[item["issue_key"]]),
            "max_duedate": max_duedate_dit[item["issue_key"]],
        }
        for item in stories
        if item["issue_key"] in valid_story_keys
    ]
    # 按 max_duedate 排序
    todo_stories.sort(key=lambda x: x["max_duedate"] if x["max_duedate"] else "")

    # 返回本周待完成故事的字符串
    return f"> ** 本周待完成故事 ** {warn_b(len(todo_stories))} \n" + "\n".join(
        [
            f"> [{i + 1}] {s['name']} {s['assignees']} {s['max_duedate'][5:]}"
            for i, s in enumerate(todo_stories)
        ]
    )


def gene_spirnt_message(active_sprint) -> str | None:
    # 获取迭代中的所有Issue
    issues = active_sprint.sample_issues
    # 所有故事
    stories = [issue for issue in issues if issue["issue_type"] in ["故事", "简单故事"]]
    # 所有子任务
    tasks = [issue for issue in issues if issue["issue_type"] == "子任务"]
    # 所有bug
    bugs = [issue for issue in issues if issue["issue_type"] == "故障"]
    # 本周待完成子任务
    todo_tasks = [
        task
        for task in tasks
        if task["status"] != "已完成"
        and task["duedate"] is not None
        and task["duedate"] <= dateattr.lastday_of_week.strftime("%Y-%m-%d")
    ]
    # 所有未解决bug
    todo_bugs = [bug for bug in bugs if bug["status"] != "完成"]

    # 生成整体进度字符串
    overall_progress_str = gene_overall_progress_message(stories, tasks, todo_bugs)
    # 生成本周待完成故事数据字符串
    this_week_todo_stories_str = gene_this_week_todo_stories_message(
        stories, todo_tasks
    )

    # 生成完整消息内容
    enddate_str = f"结束日期: {grey(active_sprint.enddate[0:10])}"
    message = (
        f"## {active_sprint.sprint_name} 进度"
        + "\n"
        + enddate_str
        + "\n"
        + overall_progress_str
        + this_week_todo_stories_str
    )
    return message


def gene_message(config: ProjectRemindConfig) -> list[str] | None:
    # 获取当前活动的sprint信息
    project_util = ProjectUtil(config)
    active_sprints = project_util.active_sprints
    if not active_sprints:
        logger.info(f"{config.project_name} 当前没有活动的Sprint")
    else:
        message_list = [
            msg
            for msg in [
                gene_spirnt_message(active_sprint) for active_sprint in active_sprints
            ]
            if msg is not None
        ]
        return message_list if message_list else None


def debug_all():
    for congfig in get_debug_configs():
        if not congfig.need_story_remind:
            logger.info(f"{congfig.project_name} 不需要本周故事提醒")
            continue
        message = gene_message(congfig)
        logger.info(message or f"{congfig.project_name} 本周无故事")


def debug_one():
    congfig = get_debug_config("1044")
    if congfig:
        messages = gene_message(congfig)
        if messages:
            for msg in messages:
                logger.info(msg)
    else:
        logger.info("未找到board_id=1044的项目配置")


if __name__ == "__main__":
    debug_one()
