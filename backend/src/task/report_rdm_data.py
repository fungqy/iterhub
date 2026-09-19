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


# 测试用例 upsert: 唯一键 (case_id, story_key),冲突时更新用例内容与归属
RDM_TESTCASE_UPSERT_SQL = text(
    """
    INSERT INTO rdm_testcase (
        case_id, case_key, case_name, status, exec_status, module, story_key,
        labels, description, steps, sprint_id, sprint_name, project_id,
        project_name, created, updated
    ) VALUES (
        :case_id, :case_key, :case_name, :status, :exec_status, :module, :story_key,
        :labels, :description, :steps, :sprint_id, :sprint_name, :project_id,
        :project_name, :created, :updated
    )
    ON DUPLICATE KEY UPDATE
        case_key = VALUES(case_key), case_name = VALUES(case_name),
        status = VALUES(status), exec_status = VALUES(exec_status),
        module = VALUES(module), labels = VALUES(labels),
        description = VALUES(description), steps = VALUES(steps),
        sprint_id = VALUES(sprint_id), sprint_name = VALUES(sprint_name),
        project_id = VALUES(project_id), project_name = VALUES(project_name),
        created = VALUES(created), updated = VALUES(updated)
    """
)


def _write_testcases(conn, testcases_data):
    """测试用例写入: 清理用例下不再被引用的旧行 + upsert 当前行。

    清理以用例自身"测试要点"字段(refs)为准,与 sprint 无关:
    - 用例改引其他故事时,旧 story_key 的行会被删除(含改属其他 sprint 的场景);
    - 任何引用变化都会改动用例的 updated,保证该用例总会出现在拉取结果中。
    """
    groups: dict[str, list[dict]] = {}
    for row in testcases_data:
        groups.setdefault(row["case_id"], []).append(row)

    for case_id, rows in groups.items():
        refs = rows[0]["refs"]
        if refs:
            not_in = ", ".join(f":ref{i}" for i in range(len(refs)))
            conn.execute(
                text(
                    f"DELETE FROM rdm_testcase WHERE case_id = :cid "
                    f"AND story_key NOT IN ({not_in})"
                ),
                {"cid": case_id, **{f"ref{i}": r for i, r in enumerate(refs)}},
            )
        else:
            conn.execute(
                text("DELETE FROM rdm_testcase WHERE case_id = :cid"),
                {"cid": case_id},
            )
        # refs 仅用于清理判断,不落库
        conn.execute(
            RDM_TESTCASE_UPSERT_SQL,
            [{k: v for k, v in row.items() if k != "refs"} for row in rows],
        )


def insert_to_table(
    sprints_data,
    issues_data,
    stories_changelogs_data,
    bugs_changelogs_data,
    testcases_data,
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

        # 测试用例: upsert 写入(见 _write_testcases),
        # 以用例自身引用关系为准,不受 sprint 刷新顺序影响
        _write_testcases(conn, testcases_data)

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


def _testcase_since(project_id: str) -> str | None:
    """查询项目测试用例的最后同步时间,用于增量拉取;无数据时返回 None(走全量)"""
    engine = DbOperator.get_engine()
    with engine.connect() as conn:
        last_updated = conn.execute(
            text("SELECT MAX(updated) FROM rdm_testcase WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()
    return last_updated.strftime("%Y-%m-%d %H:%M") if last_updated else None


def process_sprint(sprint: JiraSprint | str, testcase_full: bool | None = None):
    """处理Sprint的数据

    流程:取数 → 写入主表(单事务) → 重建派生表。
    主表按 sprint 增量维护(多 sprint 共存),派生表依据主表整表重建,
    因此刷新任一 sprint 时,其他已落地 sprint 的派生数据也会一并正确重建。
    测试用例拉取支持全量(并行分页)与增量(updated >= 上次同步时间)两种模式:
    :param testcase_full: True 强制全量(手动刷新用);None 自动判断
        (项目下已有用例数据则增量,否则全量)
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

        logger.info("- 1/7 开始获取RDM数据 ...")
        issues, stories_changelogs, bugs_changelogs = get_radm_data(sprint)
        logger.info("- 1/7 RDM数据获取完成")

        # 测试用例归属:用例通过"测试要点"字段引用故事key,与 sprint 内故事求交集
        story_keys = [
            i["issue_key"]
            for i in issues
            if i["issue_type"] in ("故事", "简单故事")
        ]
        # 全量:手动刷新或项目首次同步;增量:只拉上次同步后更新的用例
        since = None if testcase_full else _testcase_since(str(sprint.project_id))
        mode = "增量" if since else "全量"
        logger.info(
            f"- 2/7 开始获取测试用例({mode}, 关联故事 {len(story_keys)} 个) ..."
        )
        testcases = sprint.testcases(story_keys, since=since)
        logger.info(f"- 2/7 测试用例获取完成({mode}, 命中 {len(testcases)} 条)")

        logger.info("- 3/7 开始将RDM数据写入库表 ...")
        sprints_data = [sprint.to_dict()]
        insert_to_table(
            sprints_data, issues, stories_changelogs, bugs_changelogs, testcases
        )
        logger.info("- 3/7 RDM数据写入库表完成")

        engine = DbOperator.get_engine()
        with engine.begin() as conn:
            logger.info("- 4/7 开始处理故事完成时长数据 rdm_story_duration ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_story_duration")
            conn.execute(text(RDM_STORY_DURATION_SQL))
            logger.info("- 4/7 故事完成时长数据处理完成")

            logger.info("- 5/7 开始处理故障完成时长数据 rdm_bug_duration ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_duration")
            conn.execute(text(RDM_BUG_DURATION_SQL))
            logger.info("- 5/7 故障完成时长数据处理完成")

            logger.info("- 6/7 开始处理Sprint故障平均完成时长 rdm_bug_avgtime_sprint ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_avgtime_sprint")
            conn.execute(text(RDM_BUG_AVGTIME_SPRINT_SQL))
            logger.info("- 6/7 Sprint故障平均完成时长数据处理完成")

            logger.info("- 7/7 开始处理作者故障平均完成时长 rdm_bug_avgtime_author ...")
            conn.exec_driver_sql("TRUNCATE TABLE rdm_bug_avgtime_author")
            conn.execute(text(RDM_BUG_AVGTIME_AUTHOR_SQL))
            logger.info("- 7/7 作者故障平均完成时长数据处理完成")

        logger.info(
            f"{sprint.project_name} 的 {sprint.sprint_name} RDM数据处理完毕 "
            f"( 总耗时: {time.perf_counter() - start:.2f}s )"
        )
    finally:
        _process_lock.release()
