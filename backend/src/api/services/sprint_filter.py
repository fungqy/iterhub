"""Sprint 展示屏蔽服务

维护人工指定的「不参与前端展示」Sprint 名单(表 rdm_sprint_exclude),
并给四处展示入口提供同一份判定。

为什么是「表」而不是「查询时现算」
    判定条件是人工给的,不是从数据推导出来的 —— 有些 Sprint 零 issue 数据也该保留
    (例如刚建好、等着手动拉数),有些有数据也该藏起来。所以需要一处可持久化、
    可人工增删的名单。

隔离方式:只在读取侧生效
    刻意**不删除** rdm_sprint 中的原始行。这一点很关键 —— 作业页的 Sprint 下拉
    (GET /api/reports/sprints/{id})走 RDM 实时拉取,并且每次调用都会
    DELETE + 全量重写 rdm_sprint。若把屏蔽做成「写入时不落库」,那行数据会随着
    任何一个用户打开作业页而被重新灌回来,名单形同虚设。
    读取侧过滤则天然免疫:解屏蔽也是即时的,不需要等下一次同步。

覆盖的四处展示入口
    A 报表页 Sprint 时间轴      reports._format_sprints
    B 报表页 趋势图/重开数分布  reports.get_project_sprints_metrics(需拼在 LIMIT 之前)
    C 数据导入 Sprint 下拉      data_import.list_closed_sprints
    D 作业页 手动执行 Sprint 下拉 reports._format_sprints(RDM 实时,与 A 共用收口点)

降级约定
    这是展示层的增强能力,不是核心数据。表缺失 / 不可读时必须等同于「名单为空」,
    绝不能让一张辅助表把报表页和作业页整体打成 500。
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("SprintFilter")

# 探测失败后的重试间隔(秒):覆盖「先起服务、后跑建表脚本」的场景,免得非要重启进程
_PROBE_RETRY_SECONDS = 60.0

_table_ok: bool | None = None
_next_probe_at: float = 0.0


def _table_ready() -> bool:
    """探测 rdm_sprint_exclude 是否可用。

    结果在进程内缓存:确认可用后永久缓存;不可用时缓存 60 秒后再试 ——
    既不会让缺失状态下每个请求都去撞一次失败查询,也无需重启即可自动恢复。
    """
    global _table_ok, _next_probe_at

    if _table_ok is True:
        return True

    now = time.monotonic()
    if _table_ok is False and now < _next_probe_at:
        return False

    from sqlalchemy import text

    from db.database import get_session

    try:
        with get_session() as session:
            session.execute(text("SELECT 1 FROM rdm_sprint_exclude LIMIT 1"))
    except Exception:
        if _table_ok is not False:
            logger.warning(
                "rdm_sprint_exclude 不可用,暂不启用 Sprint 展示屏蔽;"
                "%d 秒后自动重试(建表语句见 sql/init_ddl.sql)",
                int(_PROBE_RETRY_SECONDS),
            )
        _table_ok = False
        _next_probe_at = now + _PROBE_RETRY_SECONDS
        return False

    if _table_ok is not True:
        logger.info("Sprint 展示屏蔽名单(rdm_sprint_exclude)已启用")
    _table_ok = True
    return True


def exclude_sql(alias: str) -> str:
    """返回「排除已屏蔽 Sprint」的 SQL 片段(以 AND 开头);表不可用时返回空串。

    `alias` 是查询中 rdm_sprint 的别名,由调用方以代码内常量传入。
    用 NOT EXISTS 而不是 NOT IN:后者一旦子查询出现 NULL 会整体失效。
    """
    if not _table_ready():
        return ""
    return (
        f"AND NOT EXISTS (SELECT 1 FROM rdm_sprint_exclude e "
        f"WHERE e.sprint_id = {alias}.sprint_id)"
    )


def excluded_sprint_ids() -> set[str]:
    """返回屏蔽名单中的 sprint_id 集合;表不可用时返回空集(等同不屏蔽)。"""
    if not _table_ready():
        return set()

    from sqlalchemy import text

    from db.database import get_session

    with get_session() as session:
        rows = session.execute(text("SELECT sprint_id FROM rdm_sprint_exclude"))
        return {str(row[0]) for row in rows if row[0] is not None}


def list_excluded() -> list[dict]:
    """列出屏蔽名单(按加入时间倒序),附带项目名便于人工核对。"""
    if not _table_ready():
        return []

    from sqlalchemy import text

    from db.database import get_session

    with get_session() as session:
        rows = session.execute(text("""
            SELECT e.id, e.sprint_id, e.project_id, e.sprint_name,
                   e.reason, e.created_at,
                   pc.project_name
            FROM rdm_sprint_exclude e
            LEFT JOIN project_configs pc ON pc.project_id = e.project_id
            ORDER BY e.created_at DESC, e.id DESC
        """))
        return [
            {
                "id": r[0],
                "sprint_id": r[1],
                "project_id": r[2],
                "project_name": r[6] or "",
                "sprint_name": r[3] or "",
                "reason": r[4] or "",
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]


def add_excluded(
    sprint_id: str,
    reason: str | None = None,
) -> dict:
    """把 Sprint 加入屏蔽名单;已存在则覆盖原因(幂等)。

    已取消「操作人」记录:该字段属于用户身份信息,与业务数据无关。

    若 rdm_sprint 中已有该 Sprint,顺带带出 project_id / sprint_name 快照供核对;
    查不到也允许加入 —— 作业页下拉取自 RDM 实时数据,本地表可能尚未同步。
    """
    from sqlalchemy import text

    from db.database import get_session

    sid = str(sprint_id).strip()
    if not sid:
        raise ValueError("sprint_id 不能为空")

    with get_session() as session:
        snapshot = session.execute(
            text("SELECT project_id, sprint_name FROM rdm_sprint WHERE sprint_id = :sid LIMIT 1"),
            {"sid": sid},
        ).fetchone()
        project_id = snapshot[0] if snapshot else None
        sprint_name = (snapshot[1] if snapshot else None) or None
        if sprint_name:
            sprint_name = sprint_name[:512]

        session.execute(
            text("""
                INSERT INTO rdm_sprint_exclude
                    (sprint_id, project_id, sprint_name, reason)
                VALUES (:sid, :pid, :sname, :reason)
                ON DUPLICATE KEY UPDATE
                    project_id = VALUES(project_id),
                    sprint_name = VALUES(sprint_name),
                    reason = VALUES(reason)
            """),
            {
                "sid": sid,
                "pid": project_id,
                "sname": sprint_name,
                "reason": (reason or None),
            },
        )
        session.commit()

    logger.info("已将 Sprint %s 加入展示屏蔽名单", sid)
    return {
        "sprint_id": sid,
        "project_id": project_id,
        "sprint_name": sprint_name or "",
        "reason": reason or "",
    }


def remove_excluded(sprint_id: str) -> bool:
    """把 Sprint 移出屏蔽名单,返回是否确实删掉了一行。"""
    from sqlalchemy import text

    from db.database import get_session

    sid = str(sprint_id).strip()
    with get_session() as session:
        result = session.execute(
            text("DELETE FROM rdm_sprint_exclude WHERE sprint_id = :sid"),
            {"sid": sid},
        )
        session.commit()
        deleted = (result.rowcount or 0) > 0

    if deleted:
        logger.info("已将 Sprint %s 移出展示屏蔽名单", sid)
    return deleted
