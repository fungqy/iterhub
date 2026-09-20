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
    conn,
    sprints_data,
    issues_data,
    stories_changelogs_data,
    bugs_changelogs_data,
):
    """将当前 sprint 的数据写入各主表(使用调用方传入的连接/事务)。

    主表按 sprint_id 清理旧数据 + 追加写入,从而支持多 sprint 共存:
    重复执行同一 sprint 会覆盖其旧数据,同时不影响其他已落地的 sprint。

    ⚠ 刻意不在本函数内自开事务(conn 由调用方传入):主表写入必须与
    process_sprint 的派生表重建**同处一个事务**,否则中途失败会留下
    「主表已提交、派生表空/半成品」的持久不一致。
    """
    # 当前执行的 sprint_id,用于清理该 sprint 在表中的旧数据
    sprint_id = sprints_data[0]["sprint_id"] if sprints_data else None

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


def process_sprint(sprint: JiraSprint | str):
    """处理Sprint的数据

    流程:取数 → (单事务内)写入主表 + 重建派生表。
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

        # ⚠ 主表写入与派生表重建必须处于**同一个事务**:
        #   历史实现分两个事务,派生表那步任一失败会留下「主表新、派生表空」的
        #   持久不一致;而 TRUNCATE 属 DDL 会隐式提交,放进事务也回滚不了,
        #   故改用 DELETE(派生表本就要整表重建,DELETE 语义等价)。
        engine = DbOperator.get_engine()
        with engine.begin() as conn:
            logger.info("- 2/6 开始将RDM数据写入库表 ...")
            insert_to_table(
                conn,
                [sprint.to_dict()],
                issues,
                stories_changelogs,
                bugs_changelogs,
            )
            logger.info("- 2/6 RDM数据写入库表完成")

            logger.info("- 3/6 开始处理故事完成时长数据 rdm_story_duration ...")
            conn.execute(text("DELETE FROM rdm_story_duration"))
            conn.execute(text(RDM_STORY_DURATION_SQL))
            logger.info("- 3/6 故事完成时长数据处理完成")

            logger.info("- 4/6 开始处理故障完成时长数据 rdm_bug_duration ...")
            conn.execute(text("DELETE FROM rdm_bug_duration"))
            conn.execute(text(RDM_BUG_DURATION_SQL))
            logger.info("- 4/6 故障完成时长数据处理完成")

            logger.info("- 5/6 开始处理Sprint故障平均完成时长 rdm_bug_avgtime_sprint ...")
            conn.execute(text("DELETE FROM rdm_bug_avgtime_sprint"))
            conn.execute(text(RDM_BUG_AVGTIME_SPRINT_SQL))
            logger.info("- 5/6 Sprint故障平均完成时长数据处理完成")

            logger.info("- 6/6 开始处理作者故障平均完成时长 rdm_bug_avgtime_author ...")
            conn.execute(text("DELETE FROM rdm_bug_avgtime_author"))
            conn.execute(text(RDM_BUG_AVGTIME_AUTHOR_SQL))
            logger.info("- 6/6 作者故障平均完成时长数据处理完成")

        logger.info(
            f"{sprint.project_name} 的 {sprint.sprint_name} RDM数据处理完毕 "
            f"( 总耗时: {time.perf_counter() - start:.2f}s )"
        )
    finally:
        _process_lock.release()
