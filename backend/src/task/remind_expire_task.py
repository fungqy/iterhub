import logging
from datetime import date

from util.color import red, warn
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


def gene_today_unfinished_tasks_str(today_unfinished_tasks):
    """生成今天未完成任务的数据字符串"""
    return "\n".join(
        [
            f"> [{i + 1}] "
            f"{task['name']} "
            f"<@{task['assignee']}> "
            f"{task['duedate']} {red(task['expired']) if task['expired'] == '已过期' else warn(task['expired'])}"
            for i, task in enumerate(today_unfinished_tasks)
        ]
    )


def gene_spirnt_message(active_sprint) -> str | None:
    # 获取子任务
    tasks = active_sprint.sample_tasks
    # 本周待完成任务
    todo_tasks = [
        task
        for task in tasks
        if task["status"] != "已完成"
        and task["duedate"] is not None
        and task["duedate"] <= dateattr.lastday_of_week.strftime("%Y-%m-%d")
    ]
    # 今天未完成的任务
    today_unfinished_tasks = [
        {
            "name": task["issue_name"].replace(" ", ""),
            "assignee": task["assignee"],
            "duedate": task["duedate"][5:],  # 日期不带年份
            "expired": "已过期"
            if task["duedate"] < date.today().strftime("%Y-%m-%d")
            else "今天到期",
        }
        for task in todo_tasks
        if task["duedate"] <= date.today().strftime("%Y-%m-%d")
    ]

    # 任务未设置到期日个数提醒
    no_duedate_tasks_cnt_str = ""
    has_duedate_task_cnt = sum([1 for task in tasks if task["duedate"] is not None])
    if has_duedate_task_cnt < len(tasks):
        no_duedate_tasks_cnt_str = warn(
            f"共{len(tasks)}个任务, 还有{len(tasks) - has_duedate_task_cnt}个任务未设置到期日！"
        )

    # 生成今天未完成任务的数据字符串
    today_unfinished_tasks_str = gene_today_unfinished_tasks_str(today_unfinished_tasks)

    if has_duedate_task_cnt < len(tasks) or today_unfinished_tasks:
        message = f"## {active_sprint.sprint_name} 任务到期提醒\n{no_duedate_tasks_cnt_str}\n{today_unfinished_tasks_str}"
        return message
    else:
        logger.info(f"{active_sprint.sprint_name} 没有到期的任务")


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
        if not congfig.need_task_remind:
            logger.info(f"{congfig.project_name} 不需要任务到期提醒")
            continue
        message = gene_message(congfig)
        logger.info(message or f"{congfig.project_name} 无到期任务")


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
