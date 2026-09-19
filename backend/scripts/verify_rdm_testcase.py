"""建表 + 端到端验证: 执行 rdm_testcase 建表,并跑通取数→入库→查询

用法: 在 backend 目录下执行 uv run python scripts/verify_rdm_testcase.py [sprint_id]
不传 sprint_id 时默认取库中最近的一个 sprint。
"""

import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 将 src 目录加入 sys.path,以便导入 task/db 等模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def ensure_table():
    """按 init_ddl.sql 中的定义建 rdm_testcase 表(已存在则跳过)"""
    engine = create_engine(os.environ["MSQL_DSN"])
    ddl = (
        "CREATE TABLE `rdm_testcase` (\n"
        "  `case_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例issue_id',\n"
        "  `case_key` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例key',\n"
        "  `case_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例名称',\n"
        "  `status` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用例状态',\n"
        "  `exec_status` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '执行状态(cf_11107)',\n"
        "  `module` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '模块(cf_11102)',\n"
        "  `story_key` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '归属故事key(由测试要点解析)',\n"
        "  `labels` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '标签',\n"
        "  `description` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '描述',\n"
        "  `steps` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '测试步骤(JSON数组:no/action/data/expected)',\n"
        "  `sprint_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint id',\n"
        "  `sprint_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sprint名称',\n"
        "  `project_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目id',\n"
        "  `project_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目名称',\n"
        "  `created` datetime DEFAULT NULL COMMENT '创建时间',\n"
        "  `updated` datetime DEFAULT NULL COMMENT '更新时间',\n"
        "  KEY `idx_testcase_sprint_id` (`sprint_id`),\n"
        "  KEY `idx_testcase_case_id` (`case_id`),\n"
        "  KEY `idx_testcase_case_key` (`case_key`),\n"
        "  KEY `idx_testcase_story_key` (`story_key`),\n"
        "  UNIQUE KEY `uk_testcase_case_story` (`case_id`, `story_key`)\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
        "COMMENT='rdm测试用例数据'"
    )
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'rdm_testcase'"
            )
        ).scalar()
        if exists:
            print("[DDL] rdm_testcase 表已存在,跳过建表")
        else:
            conn.execute(text(ddl))
            conn.commit()
            print("[DDL] rdm_testcase 表创建成功")


def main():
    ensure_table()

    from task.report_rdm_data import process_sprint

    sprint_id = sys.argv[1] if len(sys.argv) > 1 else None
    # 第二个参数: full=强制全量并行拉取, auto=自动判断(有数据则增量)
    mode_full = len(sys.argv) > 2 and sys.argv[2] == "full"
    if not sprint_id:
        engine = create_engine(os.environ["MSQL_DSN"])
        with engine.connect() as conn:
            sprint_id = conn.execute(
                text(
                    "SELECT sprint_id FROM rdm_sprint "
                    "ORDER BY ABS(CAST(sprint_id AS SIGNED)) DESC LIMIT 1"
                )
            ).scalar()
        print(f"[RUN] 未指定 sprint_id,使用最近的 sprint: {sprint_id}")

    print(f"[RUN] 开始处理 sprint {sprint_id}(testcase_full={mode_full}) ...")
    process_sprint(sprint_id, testcase_full=True if mode_full else None)

    # 验证入库结果
    engine = create_engine(os.environ["MSQL_DSN"])
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT case_key, case_name, exec_status, module, story_key, sprint_name "
                "FROM rdm_testcase WHERE sprint_id = :sid LIMIT 10"
            ),
            {"sid": str(sprint_id)},
        ).mappings().all()
        total = conn.execute(
            text("SELECT COUNT(*) FROM rdm_testcase WHERE sprint_id = :sid"),
            {"sid": str(sprint_id)},
        ).scalar()
    print(f"\n[CHECK] rdm_testcase 中 sprint {sprint_id} 共 {total} 条,样例:")
    for r in rows:
        print(f"    {r['case_key']} | {r['case_name']} | 执行状态={r['exec_status']} "
              f"| 模块={r['module']} | 故事={r['story_key']}")


if __name__ == "__main__":
    main()
