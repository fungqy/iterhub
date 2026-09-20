import logging
import threading
import time

import pandas as pd
from sqlalchemy import text

from db.dboperator import DbOperator
from db.report_sqls import (
    RDM_BUG_AVGTIME_AUTHOR_SQL,
    RDM_BUG_AVGTIME_SPRINT_SQL,
    RDM_BUG_DURATION_SQL,
    RDM_STORY_DURATION_SQL,
)
from util.jira import Sprint as JiraSprint

logger = logging.getLogger("Report")

# 全局互斥锁:任何时候只允许一个 process_sprint 跑,
# 避免两个 sprint 并发 truncate/insert 互相覆盖对方的数据。
_process_lock = threading.Lock()


def get_radm_data(sprint: JiraSprint) -> tuple:
    """处理Sprint的数据"""
    issues, stories_changelogs, bugs_changelogs = sprint.rdm_report_data

    if issues:
        return issues, stories_changelogs, bugs_changelogs
    return [], [], []


def insert_to_table(
    sprints_data,
    issues_data,
    stories_changelogs_data,
    bugs_changelogs_data,
):
    """将当前 sprint 的数据写入各主表,整体纳入一个事务。

    从「整表 TRUNCATE」改为「按 sprint_id 清理旧数据 + 追加写入」,从而支持多 sprint 共存:
    重复执行同一 sprint 会覆盖其旧数据,同时不影响其他已落地的 sprint。
    派生表仍由 process_sprint 依据这些主表做整表重建。
    """
    engine = DbOperator.get_engine()
    # 当前执行的 sprint_id,用于清理该 sprint 在表中的旧数据
    sprint_id = sprints_data[0]["sprint_id"] if sprints_data else None

    with engine.begin() as conn:
        # 按 sprint 清理旧数据。rdm_story_changelog 无 sprint 字段,借助 rdm_issue 关联其归属
        if sprint_id:
            conn.execute(
                text(
                    "DELETE FROM rdm_story_changelog WHERE story_id IN "
                    "(SELECT issue_id FROM rdm_issue WHERE sprint_id = :sid)"
                ),
                {"sid": sprint_id},
            )
            conn.execute(
                text("DELETE FROM rdm_bug_changelog WHERE sprint_id = :sid"),
                {"sid": sprint_id},
            )
            conn.execute(
                text("DELETE FROM rdm_issue WHERE sprint_id = :sid"),
                {"sid": sprint_id},
            )
            conn.execute(
                text("DELETE FROM rdm_sprint WHERE sprint_id = :sid"),
                {"sid": sprint_id},
            )

        # 写入当前 sprint(追加,保留其他 sprint)
        if sprints_data:
            pd.DataFrame(sprints_data).to_sql(
                "rdm_sprint", con=conn, if_exists="append", index=False
            )

        if issues_data:
            pd.DataFrame(issues_data).to_sql(
                "rdm_issue", con=conn, if_exists="append", index=False
            )

        if stories_changelogs_data:
            stories_changelogs_df = pd.DataFrame(stories_changelogs_data)
            stories_changelogs_df_unique = stories_changelogs_df.drop_duplicates()
            stories_changelogs_df_unique.to_sql(
                "rdm_story_changelog", con=conn, if_exists="append", index=False
            )

        if bugs_changelogs_data:
            bugs_changelogs_df = pd.DataFrame(bugs_changelogs_data)
            bugs_changelogs_df["is_max"] = bugs_changelogs_df.groupby("bug_id")[
                "sprint_id"
            ].transform(lambda x: x == x.max())
            filtered_df = bugs_changelogs_df[bugs_changelogs_df["is_max"]].drop(
                columns="is_max"
            )
            filtered_df.to_sql(
                "rdm_bug_changelog", con=conn, if_exists="append", index=False
            )
    # 离开 with 块时若中间任一步抛错,事务自动回滚


def process_sprint(sprint: JiraSprint | str):
    """处理Sprint的数据

    流程:取数 → 写入主表(单事务) → 重建派生表。
    主表按 sprint 增量维护(多 sprint 共存),派生表依据主表整表重建,
    因此刷新任一 sprint 时,其他已落地 sprint 的派生数据也会一并正确重建。
    全过程持有 _process_lock 互斥,避免并发处理。
    """
    if isinstance(sprint, str):
        sprint = JiraSprint.from_jira_id(sprint)

    # 非阻塞获取:若已有任务在跑,直接抛错(避免无限等待)
    if not _process_lock.acquire(blocking=False):
        raise RuntimeError("另一个 RDM 报表任务正在处理中,请稍后再试")

    try:
        logger.info(f"开始获取 {sprint.project_name} 的 {sprint.sprint_name} RDM数据 ...\n")
        start = time.perf_counter()

        logger.info("- 1/6 开始获取RDM数据 ...")
        issues, stories_changelogs, bugs_changelogs = get_radm_data(sprint)
        logger.info("- 1/6 RDM数据获取完成")

        logger.info("- 2/6 开始将RDM数据写入库表 ...")
        sprints_data = [sprint.to_dict()]
        insert_to_table(sprints_data, issues, stories_changelogs, bugs_changelogs)
        logger.info("- 2/6 RDM数据写入库表完成")

        engine = DbOperator.get_engine()
        with engine.begin() as conn:
            logger.info("- 3/6 开始处理故事完成时长数据 rdm_story_duration ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_story_duration")
            conn.execute(text(RDM_STORY_DURATION_SQL))
            logger.info("- 3/6 故事完成时长数据处理完成")

            logger.info("- 4/6 开始处理故障完成时长数据 rdm_bug_duration ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_duration")
            conn.execute(text(RDM_BUG_DURATION_SQL))
            logger.info("- 4/6 故障完成时长数据处理完成")

            logger.info("- 5/6 开始处理Sprint故障平均完成时长 rdm_bug_avgtime_sprint ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_avgtime_sprint")
            conn.execute(text(RDM_BUG_AVGTIME_SPRINT_SQL))
            logger.info("- 5/6 Sprint故障平均完成时长数据处理完成")

            logger.info("- 6/6 开始处理作者故障平均完成时长 rdm_bug_avgtime_author ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_avgtime_author")
            conn.execute(text(RDM_BUG_AVGTIME_AUTHOR_SQL))
            logger.info("- 6/6 作者故障平均完成时长数据处理完成")

        logger.info(
            f"{sprint.project_name} 的 {sprint.sprint_name} RDM数据处理完毕 "
            f"( 总耗时: {time.perf_counter() - start:.2f}s )"
        )
    finally:
        _process_lock.release()
