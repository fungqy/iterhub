import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from api.auth import get_current_user_from_header
from api.services.sprint_filter import exclude_sql, excluded_sprint_ids
from db.database import get_session
from util.jira import (
    INTERACTIVE_SPRINT_RETRIES,
    INTERACTIVE_SPRINT_TIMEOUT,
    BaseProject,
)

router = APIRouter(prefix="/api/reports", tags=["质量报表"])


logger = logging.getLogger("Reports")


# 「原因分布」的规范词表 —— 以**源表（docs/应用平台现场问题沟通新.xlsx「问题明细表」）的
# 【问题类别】列用词**为准。源表实际取值：代码问题/需求完善/功能优化/环境问题/沟通问题/模型能力问题。
# ⚠ 「代码问题」是拍板用词（09-17）：原先叫「代码实现」，现统一改回源表用词。
CANONICAL_TAGS = ("代码问题", "需求完善", "功能优化", "环境问题", "沟通问题", "模型能力问题", "其他")

# RDM（rdm_issue.bug_reason）的历史用词 → 规范词。RDM 的 bug_reason 形如 '代码实现 - 代码逻辑问题'，
# 其类别段是**早期人工维护的旧口径**，与源表不是同一套词，必须显式alias，不能靠字符串相等。
# ⚠ 逐个都有实测依据（全表仅这 5 种取值，见 09-17 排查）：
#   代码实现(532) → 代码问题   ；业务需求(146) → 需求完善
#   环境配置(57)  → 环境问题   ；其他(46)     → 其他
#   NULL(47)      → 空值，走下面的空值分支落「其他」
RDM_TAG_ALIAS: dict[str, str] = {
    "代码实现": "代码问题",
    "业务需求": "需求完善",
    "环境配置": "环境问题",
    # 源表也用的词，幂等映射（写出来是为了让「RDM 全词表」一眼可见，避免漏项时静默落「其他」）
    "代码问题": "代码问题",
    "需求完善": "需求完善",
    "环境问题": "环境问题",
    "沟通问题": "沟通问题",
    "功能优化": "功能优化",
    "模型能力问题": "模型能力问题",
    "其他": "其他",
}


def parse_tag(raw: str | None, source: str = 'RDM') -> str:
    """把「原因」原始值归到一个标签，供「原因分布」统计。统一出口 = CANONICAL_TAGS 用词。

    RDM（rdm_issue.bug_reason）：形如 '代码实现 - 代码逻辑问题'，按 '-' 取第一段，
      再经 RDM_TAG_ALIAS 翻译成规范词。**未命中的段落「其他」** —— RDM 侧是封闭枚举，
      别名表外的值说明口径又变了，宁可归「其他」也不要在图上凭空多出野生类别。
    DOC（rdm_doc_bug.type）：源表的【问题类别】列**直通保留**，值是什么就是什么，
      不做枚举校验。理由：文档表的类别是人工维护的开放语义，若按词表收口，
      新值会被静默丢进「其他」，用户就看不出真实分布。
      空值（''/None/纯空白）才落「其他」。
    """
    if not raw or not raw.strip():
        return '其他'
    if source == 'DOC':
        return raw.strip()
    seg = raw.split('-')[0].strip()
    return RDM_TAG_ALIAS.get(seg, '其他')


@router.get("/projects")
async def list_user_projects(current_user: dict = Depends(get_current_user_from_header)):
    """获取已启用报表数据的项目列表(所有用户共享)"""
    with get_session() as session:
        query = text("""
            SELECT pc.id, pc.project_id, pc.project_name, pc.board_name
            FROM project_configs pc
            INNER JOIN project_reminder_settings prs ON pc.id = prs.project_config_id
            WHERE prs.need_report_data = TRUE
            ORDER BY pc.project_name
        """)
        result = session.execute(query)

        projects = []
        for row in result:
            projects.append({
                "id": row[0],
                "project_id": row[1],
                "project_name": row[2],
                "board_name": row[3],
            })
        return projects



def _load_sprints_from_db(jira_project_id) -> list[tuple]:
    """RDM 拉取失败时的兜底:从本地 rdm_sprint 表读取该项目的存量 Sprint 行"""
    logger.info(f"从数据库读取项目 {jira_project_id} 的 Sprint 数据")
    from db.dboperator import DbOperator

    with DbOperator.get_engine().connect() as conn:
        return conn.execute(text("""
            SELECT sprint_id, sprint_name, startdate, enddate, activated_date, state
            FROM rdm_sprint
            WHERE project_id = :pid
            ORDER BY sprint_id
        """), {"pid": str(jira_project_id)}).fetchall()


def _format_sprints(rows) -> list[dict]:
    """将 Sprint 行数据组装为接口响应,统一供两条数据源复用:
    - RDM 实时获取:sprint 对象先转元组
    - 数据库兜底:rdm_sprint 表查询结果(元组)
    行结构: (sprint_id, sprint_name, startdate, enddate, activated_date, state)

    这里是「报表页时间轴(A)」与「作业页手动执行下拉(D)」的共同收口点,
    故 Sprint 展示屏蔽(rdm_sprint_exclude)在此一次生效,两条路径不必各自处理。

    注意:屏蔽只作用于**返回给前端的列表**。调用方若要写库,必须继续使用屏蔽前的
    原始数据 —— 例如 /sprints 的全量覆盖写入仍应写入 RDM 返回的全部 Sprint,
    不能拿本函数的返回值去落库,否则会自动把被屏蔽项从 rdm_sprint 里抹掉。
    """
    from db.dboperator import DbOperator

    with DbOperator.get_engine().connect() as conn:
        # rdm_issue 无 project_id 列,sprint_id 全局唯一,直接全表 DISTINCT 判断
        done_ids = {
            str(r[0])
            for r in conn.execute(text("SELECT DISTINCT sprint_id FROM rdm_issue"))
        }

    excluded_ids = excluded_sprint_ids()

    return [
        {
            "sprint_id": int(r[0]),
            "sprint_name": r[1] or "",
            "start_date": r[2],
            "end_date": r[3],
            "activated_date": r[4],
            "state": r[5] or "",
            "has_report_data": str(r[0]) in done_ids,
        }
        for r in rows
        if r[0] is not None and str(r[0]) not in excluded_ids
    ]


def _get_project_row(project_id: int):
    """查询项目配置行:(board_id, board_name, jira_project_id, project_name),不存在返回 None"""
    with get_session() as session:
        row = session.execute(text("""
            SELECT board_id, board_name, project_id, project_name
            FROM project_configs WHERE id = :project_id
        """), {"project_id": project_id}).fetchone()
    return row


@router.get("/db-sprints/{project_id}")
async def list_project_sprints_from_db(
    project_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """质量报表专用:仅从数据库 rdm_sprint 表读取 Sprint,不触发任何 RDM 拉取。
    数据由任务调度模块同步到本地;RDM 实时拉取请用 /sprints/{project_id}。"""
    row = _get_project_row(project_id)
    if not row:
        return []

    jira_project_id = row[2]
    return _format_sprints(_load_sprints_from_db(jira_project_id))


@router.get("/sprints/{project_id}")
async def list_project_sprints(
    project_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """根据项目ID实时从 RDM 获取 Sprint 列表（不再依赖本地 rdm_sprint 表）；
    RDM 拉取失败或缺少 JIRA 认证时，回退返回数据库中的存量数据

    ⚠⚠ **本接口是「读」却带「写」副作用**(2026-09-20 评审后确认暂时保留):
    RDM 拉取成功时会 `DELETE FROM rdm_sprint WHERE project_id=?` 再全量重写。
    由此带来两个必须知道的后果,改动本接口前先读:
      1. 它与 task/report_rdm_data.process_sprint(按 sprint 写 rdm_sprint)并发时
         会互相覆盖/删行 —— 后者提交的 sprint 可能被本接口的「全量覆盖」抹掉;
      2. 作业页手动执行弹窗打开即会触发它,即「只是打开下拉框」也会写库。
    彻底修法是拆成显式的「同步迭代列表」写接口 + 纯只读查询接口(需前端配合),
    本轮按决策不动,仅在此标注。

    另:探测 RDM 用的是收窄过的超时(见 _RDM_SPRINT_PROBE_TIMEOUT),到点即回退本地库;
    否则本接口是同步阻塞的,下拉会长时间拿不到 options。"""
    from api.services.project_configs import get_jira_auth
    from util.jira import ProjectUtil

    row = _get_project_row(project_id)
    if not row:
        return []

    board_id, board_name, jira_project_id, project_name = row

    # 使用全局共享的 JIRA 认证直接从 RDM(http://rdm.zvos.zoomlion.com)拉取 Sprint
    auth_config = get_jira_auth()
    if auth_config is None:
        logger.warning(f"项目 {project_name}({project_id}) 缺少 JIRA 认证配置,回退返回数据库中的 Sprint")
        return _format_sprints(_load_sprints_from_db(jira_project_id))

    config = BaseProject(
        board_id=str(board_id),
        board_name=str(board_name) if board_name else "",
        project_id=str(jira_project_id),
        project_name=project_name or "",
    )
    # 交互式只读端点:探测 RDM 用短超时,到点即回退本地 rdm_sprint(见 util.jira 常量)
    project_util = ProjectUtil(
        config,
        auth_config,
        sprint_timeout=INTERACTIVE_SPRINT_TIMEOUT,
        sprint_retries=INTERACTIVE_SPRINT_RETRIES,
    )

    try:
        sprints = project_util.sprints or []
    except Exception:
        # RDM 拉取失败时不覆盖本地数据,回退返回数据库存量
        logger.warning(f"从 RDM 获取项目 {project_name} 的 Sprint 失败,回退返回数据库中的 Sprint")
        return _format_sprints(_load_sprints_from_db(jira_project_id))
    else:
        # 只要 RDM 获取成功就全量覆盖该项目:先清空该项目,再按当前结果写入。
        # 即使 RDM 上某 sprint 已移除(列表不再包含它),也会被覆盖删掉;
        # 拉取抛异常走 except 分支,则不覆盖以保留原数据。
        from db.dboperator import DbOperator

        with DbOperator.get_engine().begin() as conn:
            conn.execute(
                text("DELETE FROM rdm_sprint WHERE project_id = :pid"),
                {"pid": str(jira_project_id)},
            )
            if sprints:
                import pandas as pd

                pd.DataFrame([s.to_dict() for s in sprints]).to_sql(
                    "rdm_sprint", con=conn, if_exists="append", index=False
                )

    # RDM 实时数据与数据库兜底共用同一响应组装逻辑(含 has_report_data 判断)
    return _format_sprints([
        (s.sprint_id, s.sprint_name, s.startdate, s.enddate, s.activated_date, s.state)
        for s in sprints
    ])



@router.get("/metrics")
async def get_sprint_metrics(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取Sprint的指标数据：故事数、故障数"""
    with get_session() as session:
        # 故事数：issueType 为 故事 或 简单故事
        story_query = text("""
            SELECT COUNT(*) FROM rdm_issue
            WHERE sprint_id = :sprint_id
            AND issue_type IN ('故事', '简单故事')
        """)
        story_result = session.execute(story_query, {"sprint_id": sprint_id})
        story_count = story_result.fetchone()[0] or 0   # type: ignore[attr-defined]

        # 故障数：issueType 为 故障
        bug_query = text("""
            SELECT
                (SELECT COUNT(*) FROM rdm_issue WHERE sprint_id = :sprint_id AND issue_type = '故障') +
                (SELECT COUNT(*) FROM rdm_doc_bug WHERE sprint_id = :sprint_id)
            AS total_count;
        """)
        bug_result = session.execute(bug_query, {"sprint_id": sprint_id})
        bug_count = bug_result.fetchone()[0] or 0   # type: ignore[attr-defined]

        # 故障重开数：rdm_issue关联rdm_bug_changelog，存在"待测试 -> 处理中"变更记录
        reopen_query = text("""
            SELECT COUNT(DISTINCT i.issue_id)
            FROM rdm_issue i
            INNER JOIN rdm_bug_changelog c ON i.issue_id = c.bug_id
            WHERE i.sprint_id = :sprint_id
            AND i.issue_type = '故障'
            AND c.change_detail = '待测试 -> 处理中'
        """)
        reopen_result = session.execute(reopen_query, {"sprint_id": sprint_id})
        bug_reopen_count = reopen_result.fetchone()[0] or 0   # type: ignore[attr-defined]

        return {
            "story_count": story_count,
            "bug_count": bug_count,
            "bug_reopen_count": bug_reopen_count,
        }


@router.get("/burndown")
async def get_sprint_burndown(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取Sprint故事燃尽图数据：按天统计剩余故事数（实际线）并生成理想线"""
    with get_session() as session:
        # Sprint 时间窗：优先激活时间，其次计划开始时间；结束优先实际完成时间
        sprint_query = text("""
            SELECT sprint_name, startdate, enddate, activated_date, complete_date
            FROM rdm_sprint
            WHERE sprint_id = :sprint_id
            LIMIT 1
        """)
        sprint_row = session.execute(sprint_query, {"sprint_id": sprint_id}).fetchone()

        # 故事列表：LEFT JOIN 故事变更记录取完成时间（resolutiondate），口径与 rdm_story_duration 一致
        story_query = text("""
            SELECT i.created, c.complete_time
            FROM rdm_issue i
            LEFT JOIN (
                SELECT story_id, MIN(complete_time) AS complete_time
                FROM rdm_story_changelog
                WHERE complete_time IS NOT NULL
                GROUP BY story_id
            ) c ON i.issue_id = c.story_id
            WHERE i.sprint_id = :sprint_id
            AND i.issue_type IN ('故事', '简单故事')
        """)
        stories = session.execute(story_query, {"sprint_id": sprint_id}).fetchall()

        empty_result = {
            "sprint_id": sprint_id, "sprint_name": "", "start_date": None,
            "end_date": None, "total": 0, "dates": [], "actual": [], "ideal": [],
        }
        if not sprint_row or not stories:
            return empty_result

        created_list = [row[0] for row in stories if row[0]]
        complete_list = [row[1] for row in stories if row[1]]

        # 时间窗兜底：Sprint 日期缺失时用故事实际创建/完成时间推导
        start_dt = sprint_row[3] or sprint_row[1] or (min(created_list) if created_list else None)
        end_dt = sprint_row[4] or sprint_row[2] or (max(complete_list or created_list) if (complete_list or created_list) else None)
        if not start_dt or not end_dt:
            return empty_result

        start_date = start_dt.date() if isinstance(start_dt, datetime) else start_dt
        end_date = end_dt.date() if isinstance(end_dt, datetime) else end_dt
        if start_date > end_date:
            start_date = end_date

        # 异常时间窗防护（超过一年视为脏数据），不生成图表数据
        day_count = (end_date - start_date).days + 1
        if day_count > 366:
            return empty_result

        total = len(stories)
        dates: list[str] = []
        actual: list[int] = []
        ideal: list[float] = []
        for idx in range(day_count):
            day = start_date + timedelta(days=idx)
            eod = datetime.combine(day, datetime.max.time())
            # 当日剩余 = 当日已创建、且当日结束时仍未完成的故事数
            remaining = sum(
                1
                for row in stories
                if (not row[0] or row[0] <= eod) and (not row[1] or row[1] > eod)
            )
            dates.append(day.strftime("%m-%d"))
            actual.append(remaining)
            # 理想线：从总量线性递减到 0
            ideal.append(
                round(total * (1 - idx / (day_count - 1)), 1) if day_count > 1 else float(total)
            )

        return {
            "sprint_id": sprint_id,
            "sprint_name": sprint_row[0] or "",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total": total,
            "dates": dates,
            "actual": actual,
            "ideal": ideal,
        }



@router.get("/bugs/detail")
async def get_bug_details(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取故障详情，按开发人员、级别、标签分组统计"""
    with get_session() as session:
        # 查询故障详情
        # ⚠ 最后一列 source 是给 parse_tag 分流用的：RDM 的 bug_reason 是
        #   '类别 - 描述' 结构且必须命中封闭枚举；DOC 的 type 就是类别本身、直通保留。
        #   两者语义不同，union 后**必须**能区分，否则 DOC 的开放值会被误归「其他」。
        query = text("""
            SELECT
                COALESCE(bug_maker, reporter, '其他') as developer,
                priority,
                bug_reason,
                issue_id,
                'RDM' as source
            FROM rdm_issue
            WHERE sprint_id = :sprint_id
            AND issue_type = '故障'
            union all
            SELECT
                maker as developer,
                priority,
                type as bug_reason,
                `key` as issue_id,
                'DOC' as source
            FROM rdm_doc_bug
            WHERE sprint_id = :sprint_id
        """)
        result = session.execute(query, {"sprint_id": sprint_id})
        rows = result.fetchall()

        # 定义优先级排序
        priority_order = {'致命': 0, '严重': 1, '一般': 2, '轻微': 3, '优化': 4}

        # 定义标签排序
        # ⚠ 顺序与 CANONICAL_TAGS 一致（改词表时两处一起改）。
        # ⚠ DOC 侧是开放语义，可能出现不在表里的新类别 ⇒ 兜底 key 用 (99, 名称)，
        #   既能排在「其他」之后，又能让多个未知类别自身按名称稳定排序
        #   （只给 99 会并列，sorted 虽稳定但依赖插入顺序，跨请求可能抖动）。
        tag_order = {t: i for i, t in enumerate(CANONICAL_TAGS)}

        # 处理数据
        developers = {}  # {developer: {priority: {tag: count}}}

        for row in rows:
            developer = row[0]
            priority = row[1] or ''
            # [修复#9] 过滤空 priority，避免出现空白列头
            if not priority:
                continue

            # [修复#10] 使用公共函数解析标签(按来源分流:RDM 收口枚举 / DOC 直通保留)
            tag = parse_tag(row[2], row[4] or 'RDM')

            # 初始化
            if developer not in developers:
                developers[developer] = {}

            # 获取该开发者的优先级映射
            priority_map = developers[developer]
            if priority not in priority_map:
                priority_map[priority] = {}

            # 累加计数
            tag_counts = priority_map[priority]
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # 构建返回结果
        # 获取所有出现过的优先级和标签
        all_priorities = set()
        all_tags = set()
        for dev_data in developers.values():
            all_priorities.update(dev_data.keys())
            for tag_map in dev_data.values():
                all_tags.update(tag_map.keys())

        # 排序优先级
        sorted_priorities = sorted(
            all_priorities,
            key=lambda x: priority_order.get(x, 99)
        )

        # 排序标签
        sorted_tags = sorted(
            all_tags,
            key=lambda x: (tag_order.get(x, 99), x)
        )

        # 构建开发者行数据
        developer_rows = []
        for developer in sorted(developers.keys()):
            row_data = {"developer": developer}
            total = 0
            for priority in sorted_priorities:
                priority_map = developers[developer]
                if priority in priority_map:
                    for tag in sorted_tags:
                        if tag in priority_map[priority]:
                            total += priority_map[priority][tag]
            row_data["total"] = total
            developer_rows.append(row_data)

        return {
            "developers": developer_rows,
            "priorities": sorted_priorities,
            "tags": sorted_tags,
            "data": developers,
        }



@router.get("/bugs/list")
async def get_bug_list(
    sprint_id: int,
    priority: str = '',
    tag: str = '',
    developer: str = '',
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取故障明细列表"""
    with get_session() as session:
        # [修复#3] developer 过滤下推到 SQL 层；priority/tag 因依赖 parse_tag 仍在 Python 层过滤
        if developer:
            query = text("""
                SELECT
                    issue_key,
                    COALESCE(bug_maker, reporter, '其他') as developer,
                    priority,
                    issue_name,
                    bug_reason,
                    'RDM' as source,
                    NULL as image_count,
                    bug_reason as reason_text
                FROM rdm_issue
                WHERE sprint_id = :sprint_id
                AND issue_type = '故障'
                AND COALESCE(bug_maker, reporter, '其他') = :developer
                union all
                SELECT
                    `key` as issue_key,
                    maker as developer,
                    priority,
                    `name` as issue_name,
                    `type` as bug_reason,
                    'DOC' as source,
                    (SELECT COUNT(*) FROM rdm_doc_bug_image i
                     WHERE i.doc_bug_key = d.`key`) as image_count,
                    reason as reason_text
                FROM rdm_doc_bug d
                WHERE sprint_id = :sprint_id
                AND maker = :developer
            """)
            result = session.execute(query, {
                "sprint_id": sprint_id,
                "developer": developer
            })
        else:
            query = text("""
                SELECT
                    issue_key,
                    COALESCE(bug_maker, reporter, '其他') as developer,
                    priority,
                    issue_name,
                    bug_reason,
                    'RDM' as source,
                    NULL as image_count,
                    bug_reason as reason_text
                FROM rdm_issue
                WHERE sprint_id = :sprint_id
                AND issue_type = '故障'
                union all
                SELECT
                    `key` as issue_key,
                    maker as developer,
                    priority,
                    `name` as issue_name,
                    `type` as bug_reason,
                    'DOC' as source,
                    (SELECT COUNT(*) FROM rdm_doc_bug_image i
                     WHERE i.doc_bug_key = d.`key`) as image_count,
                    reason as reason_text
                FROM rdm_doc_bug d
                WHERE sprint_id = :sprint_id
            """)
            result = session.execute(query, {"sprint_id": sprint_id})
        rows = result.fetchall()
        logger.info(f"原始查询结果: {rows}")

        # [修复#10] 使用公共函数解析标签(按来源分流:见 parse_tag)
        # ⚠ row[4] 是**类别**(RDM=bug_reason 切段 / DOC=type)，row[7] 才是展示用的长文本。
        #   两者以前同源(row[4]=reason) ⇒ DOC 行的「标签」会是整段原因、且按标签过滤必然漏行。
        filtered_rows = []
        for row in rows:
            row_priority = row[2] or ''
            bug_reason = row[4] or ''
            row_source = row[5] or 'RDM'
            row_tag = parse_tag(bug_reason, row_source)
            reason_text = row[7] or ''

            priority_match = not priority or row_priority == priority
            tag_match = not tag or row_tag == tag
            if priority_match and tag_match:
                filtered_rows.append({
                    "issue_key": row[0],
                    "developer": row[1],
                    "priority": row_priority,
                    "issue_name": row[3] or '',
                    "reason_analysis": reason_text,  # 原因及分析(长文本,与 tag 分列)
                    "is_typical": '',  # 是否典型：先默认为空
                    "source": row_source,
                    # 文档故障的截图张数(0 = 没有截图)。列表用它决定是否给出「截图」入口 ——
                    # 没有图的行走进去只会看到空态,不如不给。
                    # 代价 = 每个 DOC 行一次索引子查询(命中 uk_doc_bug_image_seq 的前缀)。
                    # 实测 sprint 8354(13 RDM + 16 DOC 行)：全量 3.09ms、净差 −0.02ms，
                    # 即落在测量噪音内 —— 截图表只有几十行，这个子查询是内存级。
                    "image_count": row[6] or 0,
                    "tag": row_tag,  # 返回解析后的标签
                })

        # 添加序号
        for i, item in enumerate(filtered_rows, 1):
            item["index"] = i

        return filtered_rows



@router.get("/bugs/avg-time")
async def get_bug_avg_time(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取故障平均Dev时长和Test时长"""
    with get_session() as session:
        query = text("""
            SELECT
                COALESCE(AVG(dev_seconds), 0) as avg_dev_seconds,
                COALESCE(AVG(test_seconds), 0) as avg_test_seconds
            FROM rdm_bug_avgtime_sprint
            WHERE sprint_id = :sprint_id
        """)
        result = session.execute(query, {"sprint_id": sprint_id})
        row = result.fetchone()

        return {
            "avg_dev_seconds": int(row[0]) if row[0] else 0,   # type: ignore[attr-defined]
            "avg_test_seconds": int(row[1]) if row[1] else 0,    # type: ignore[attr-defined]
        }


@router.get("/bugs/avg-time/developers")
async def get_bug_avg_time_by_developers(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取某 Sprint 下各开发人员的故障时长明细(关联 rdm_issue 的编码/名称/状态),按总时长倒序"""
    with get_session() as session:
        query = text("""
            SELECT
                COALESCE(b.author, '其他') as developer,
                i.issue_id as bug_id,
                i.issue_key,
                i.issue_name,
                i.status,
                COALESCE(b.dev_seconds, 0) as dev_seconds,
                COALESCE(b.test_seconds, 0) as test_seconds,
                COALESCE(COALESCE(b.dev_seconds, 0) + COALESCE(b.test_seconds, 0), 0) as total_seconds
            FROM rdm_bug_duration b
            LEFT JOIN rdm_issue i ON b.bug_id = i.issue_id
            WHERE b.sprint_id = :sprint_id
            HAVING total_seconds > 0
            ORDER BY total_seconds DESC, dev_seconds DESC
        """)
        result = session.execute(query, {"sprint_id": sprint_id})
        rows = result.fetchall()

        items = []
        for idx, row in enumerate(rows, 1):
            items.append({
                "index": idx,
                "developer": row[0] or '',
                "bug_id": row[1],
                "issue_key": row[2] or '',
                "issue_name": row[3] or '',
                "status": row[4] or '',
                "dev_seconds": int(row[5] or 0),
                "test_seconds": int(row[6] or 0),
                "total_seconds": int(row[7] or 0),
            })
        return items



def _workday_seconds(session, start: datetime, end: datetime) -> int:
    """计算 [start, end] 区间内落在 sys_workday 上的秒数(与 rdm_bug_duration 同口径)。
    通过 sys_workday 逐日统计重叠秒数,休息日/节假日不计入。"""
    if not start or not end or end <= start:
        return 0
    # 一次性取出区间内的所有工作日日期
    wd_query = text("""
        SELECT datestr FROM sys_workday
        WHERE datestr BETWEEN DATE(:start) AND DATE(:end)
    """)
    wd_result = session.execute(wd_query, {"start": start, "end": end})
    workday_dates = [r[0] for r in wd_result]

    total = 0
    for day in workday_dates:
        # datestr 为 CHAR(10) 'YYYY-MM-DD',拼接起止时刻后与区间求交集
        if isinstance(day, datetime):
            day_str = day.strftime("%Y-%m-%d")
        else:
            day_str = str(day)[:10]
        day_start = datetime.strptime(day_str, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)
        seg_start = max(start, day_start)
        seg_end = min(end, day_end)
        if seg_end > seg_start:
            total += int((seg_end - seg_start).total_seconds())
    return total


def _bug_changelog_items(session, bug_id) -> list[dict]:
    """某故障的 create/status 变更记录(去重 → 排序 → 工作日耗时) —— 唯一口径定义处。

    这里同时服务 /bugs/changelog(独立接口)与 /bugs/one(详情内联),
    两处共用同一段实现,避免"同名字但口径漂移"(本函数就修掉过两个真实缺陷):

    ① **不要 LEFT JOIN rdm_issue 取 issue_key** —— rdm_issue 里同一 issue_id 可能有多行
       (实测 JSST-560 被 JSST-1.0-Sprint-1/6845 与 JSST-1.0-Sprint-3/6954 各拉了一行),
       JOIN 会把每条记录**扇形展开**:实测 8 条变 16 条,时间线每一步出现两次。
       故 issue_key 改为标量子查询(MIN, 单值)。
    ② **按 log_id 去重** —— rdm_bug_changelog 按 sprint 增量写(先 DELETE 本 sprint 再插),
       而一只故障若横跨两个 Sprint,它的同一条 Jira 变更日志(tlog_id 相同)会被**各写一份**。
       不去重的话时间线仍是"每一步两遍"(实测 JSST-560 的 4 个节点变 8 条)。
       GROUP BY 带上全部被选列,既等价于按 log_id 去重又满足 only_full_group_by。

    排序沿用 log_id 升序(与既有接口一致);log_id 是 varchar,故是字典序 ——
    与 Jira 的数值序在本库数据上一致,保留既有行为不做改动。
    """
    query = text("""
        SELECT t.change_type, t.change_time, t.change_detail,
               (SELECT MIN(i.issue_key) FROM rdm_issue i
                 WHERE i.issue_id = t.bug_id) AS issue_key
        FROM (
            SELECT c.log_id, c.bug_id, c.change_type, c.change_time, c.change_detail
            FROM rdm_bug_changelog c
            WHERE c.bug_id = :bug_id
            AND c.change_type IN ('create', 'status')
            GROUP BY c.log_id, c.bug_id, c.change_type, c.change_time, c.change_detail
        ) t
        ORDER BY t.log_id ASC
    """)
    rows = session.execute(query, {"bug_id": bug_id}).fetchall()

    items = []
    prev_time = None  # 上一条记录的时间,用于计算当前条的工作日耗时
    for idx, row in enumerate(rows, 1):
        change_type = row[0] or ''
        change_time = row[1]
        # create 行详情统一为"创建";其余保留原始变更详情
        detail = '创建' if change_type == 'create' else (row[2] or '')

        cur_time = None
        if hasattr(change_time, "strftime"):
            cur_time = change_time
        elif change_time:
            cur_time = datetime.strptime(str(change_time)[:19], "%Y-%m-%d %H:%M:%S")

        elapsed_seconds = _workday_seconds(session, prev_time, cur_time) if prev_time else 0
        prev_time = cur_time

        items.append({
            "index": idx,
            "issue_key": row[3] or '',
            "change_type": change_type,
            "change_time": cur_time.strftime("%Y-%m-%d %H:%M:%S") if cur_time else '',
            "change_detail": detail,
            "elapsed_seconds": elapsed_seconds,
        })
    return items


@router.get("/bugs/changelog")
async def get_bug_changelog(
    bug_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取某故障的状态变更记录:仅取 change_type 为 create/status 的行,按 log_id 升序。
    change_type 为 create 时详情统一显示为"创建"。
    每条记录额外返回 elapsed_seconds(相对上一步的工作日耗时),与 rdm_bug_duration 同为工作日口径。

    实现见 _bug_changelog_items —— 去重(按 log_id)与 issue_key 的取法都收口在那里,
    因为 /bugs/one 的详情内联必须与这里逐条一致,两处各写一份必然漂移。
    """
    with get_session() as session:
        return _bug_changelog_items(session, bug_id)


@router.get("/bugs/one")
async def get_bug_one(
    issue_key: str,
    sprint_id: int | None = None,
    current_user: dict = Depends(get_current_user_from_header)
):
    """单只 RDM 故障的详情(统一「故障详情」弹窗用):全字段 + **内联**状态变更记录。

    为什么把变更记录内联进详情,而不是让前端再打一次 /bugs/changelog:
      变更记录天然属于「这只故障的详情」,且量极小 —— 全库实测 828 只故障对应
      create 828 条 + status 2422 条,平均每只不到 4 条。拆成两个请求只会让弹窗
      多付一次鉴权 + 建连 + 序列化的开销,而两者用的是同一个 session。
      DOC 故障没有变更记录(它们不在 rdm_bug_changelog 里),故前端对 DOC 是
      **整段不渲染**,而不是渲染一个空态。

    为什么 issue_key 之外还要可选 sprint_id —— 因为 issue_key 不是唯一键:
      实测 `rdm_issue.issue_key` 存在重复:`JSST-560` 被 JSST-1.0-Sprint-1(6845)
      与 JSST-1.0-Sprint-3(6954) 各拉了一行,但两行的 `issue_id` 同为 804565、
      其余字段也一致,只有 sprint_name/sprint_id 不同。
      故:传了 sprint_id 就精确到那一次拉取;没传就按 updated 倒序取一行。
      真正唯一的是 issue_id,而变更记录正是按 bug_id = issue_id 查的
      —— 所以这次消歧不会让时间线错位。

    返回体直接给 DB 列名(展示口径留在前端),外加 `source` 与 `changelog`。
    """
    with get_session() as session:
        # 条件按需拼接:sprint_id 为 None 时不带该条件,避免依赖 `:p IS NULL OR col = :p`
        # 这种写法在无类型标注时的参数推断。
        sql = """
            SELECT
                issue_id, issue_key, issue_type, issue_name, status, resolution, priority,
                reporter, assignee, developer, tester, bug_maker, bug_solver,
                created, updated, duedate, module, bug_story, bug_type, bug_flag,
                bug_reason, callback, is_unplaned,
                sprint_id, sprint_name, description
            FROM rdm_issue
            WHERE issue_key = :issue_key
            AND issue_type = '故障'
        """
        params: dict = {"issue_key": issue_key}
        if sprint_id is not None:
            sql += " AND sprint_id = :sprint_id"
            params["sprint_id"] = sprint_id
        sql += " ORDER BY updated DESC LIMIT 1"

        row = session.execute(text(sql), params).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="未找到该故障")

        # 列名与上面的 SELECT 逐字对齐(不用 row._mapping:列清单是契约的一部分,
        # 显式写出来才能在新增列时立刻看到两处需要同步)。
        columns = [
            "issue_id", "issue_key", "issue_type", "issue_name", "status", "resolution",
            "priority", "reporter", "assignee", "developer", "tester", "bug_maker",
            "bug_solver", "created", "updated", "duedate", "module", "bug_story",
            "bug_type", "bug_flag", "bug_reason", "callback", "is_unplaned",
            "sprint_id", "sprint_name", "description",
        ]
        item = dict(zip(columns, row))
        item["source"] = "RDM"
        for k in ("created", "updated"):
            v = item.get(k)
            item[k] = v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else (str(v) if v else None)

        # ── 变更记录:直接复用 _bug_changelog_items ──
        # 与独立接口 /bugs/changelog 逐条一致(同一函数、同一去重、同一工作日耗时口径)。
        # 这里刻意**不**自己再写一遍 SQL:同名字的两段实现正是口径漂移的温床,
        # 而这一步的 verify 脚本就是拿两个接口逐条对账的。
        item["changelog"] = _bug_changelog_items(session, item["issue_id"])
        return item


@router.get("/bugs/reopen")
async def get_reopen_bugs(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取故障重开列表

    每只故障返回一条记录,并带上 reopen_times(该故障被重开的次数)。
    次数由 COUNT(*) 直接得到 —— 因为 INNER JOIN + WHERE change_detail='待测试 -> 处理中'
    已经只留下「重开」这一种流转,分组内 remaining 的行数就是重开次数。

    口径与 /project-metrics 的 reopen_once/twice/many 严格同源(同一 JOIN、同一 WHERE、
    同一分组键)。

    返回字段里两处值得说明:
      · tag —— 由 parse_tag 把 bug_reason 的首段翻成规范词,与 /bugs/list 的「标签」同一出口。
        ⚠ 不要把 RDM_TAG_ALIAS 搬到前端重算:它是本模块的口径,复制一份必然漂移。
      · bug_reason —— 即界面上「原因及分析」列的正文(RDM 口径下它与 /bugs/list 的
        reason_analysis 是同一个值:那条查询就是 `bug_reason as reason_text`),
        故前端直接用它,不再多返回一个同值的 reason_analysis。
    """
    with get_session() as session:
        query = text("""
            SELECT
                i.issue_key,
                i.issue_name,
                COALESCE(i.bug_maker, i.reporter, '其他') as bug_maker,
                i.reporter,
                i.bug_type,
                i.priority,
                i.bug_reason,
                i.resolution,
                COUNT(*) as reopen_times
            FROM rdm_issue i
            INNER JOIN rdm_bug_changelog c ON i.issue_id = c.bug_id
            WHERE i.sprint_id = :sprint_id
            AND i.issue_type = '故障'
            AND c.change_detail = '待测试 -> 处理中'
            GROUP BY i.issue_id, i.issue_key, i.issue_name, i.bug_maker,
                     i.reporter, i.bug_type, i.priority, i.bug_reason, i.resolution
            ORDER BY i.priority, i.issue_key
        """)
        result = session.execute(query, {"sprint_id": sprint_id})
        rows = result.fetchall()

        items = []
        for idx, row in enumerate(rows, 1):
            items.append({
                "index": idx,
                "issue_key": row[0] or '',
                "issue_name": row[1] or '',
                "bug_maker": row[2] or '',
                "reporter": row[3] or '',
                "bug_type": row[4] or '',
                "priority": row[5] or '',
                "bug_reason": row[6] or '',
                "resolution": row[7] or '',
                # 标签:与 /bugs/list 同一出口。RDM 的 bug_reason 形如
                # '代码实现 - 代码逻辑问题',取 '-' 前一段再过 RDM_TAG_ALIAS 翻成规范词。
                "tag": parse_tag(row[6], 'RDM'),
                # 重开次数:与卡片上的三个数字同一口径 —— 单一数据源,不在前端另行计数
                "reopen_times": int(row[8] or 0),
            })

        return items



@router.get("/project-metrics/{project_id}")
async def get_project_sprints_metrics(
    project_id: int,
    limit: int = 7,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取项目下Sprint的汇总指标数据;limit>0 时仅返回最近 N 个,limit<=0 返回全部

    故障重开口径:rdm_issue(issue_type='故障')内联 rdm_bug_changelog,
    change_detail = '待测试 -> 处理中' 记一次重开。除总数 bug_reopen_count 外,
    另按每只故障的重开次数返回分布 reopen_once / reopen_twice / reopen_many(≥3 次),
    三者之和恒等于 bug_reopen_count。
    """
    with get_session() as session:
        project_query = text("""
            SELECT project_id FROM project_configs WHERE id = :project_id
        """)
        project_result = session.execute(project_query, {"project_id": project_id})
        project_row = project_result.fetchone()

        if not project_row:
            return []

        jira_project_id = project_row[0]

        # limit>0 时限制最近 N 个 closed sprint,否则不加 LIMIT 返回全部
        limit_clause = "LIMIT :limit" if limit > 0 else ""
        # 屏蔽子句必须拼在 LIMIT 之前 —— 否则被屏蔽的 Sprint 会先占掉名额,
        # 实际返回条数就会少于 limit(表不可用时 exclude_sql 返回空串,自动降级)。
        sprints_query = text(f"""
            SELECT * FROM (
                SELECT s.sprint_id, s.sprint_name, s.short_sprint_name
                FROM rdm_sprint s
                WHERE s.project_id = :jira_project_id
                AND s.state = 'closed'
                {exclude_sql('s')}
                GROUP BY s.sprint_id, s.sprint_name, s.short_sprint_name
                ORDER BY s.sprint_id desc
                {limit_clause}
            ) AS t
            ORDER BY sprint_id asc
        """)
        query_params: dict = {"jira_project_id": jira_project_id}
        if limit > 0:
            query_params["limit"] = limit
        sprints_result = session.execute(sprints_query, query_params)
        sprints = sprints_result.fetchall()

        if not sprints:
            return []

        metrics_list = []
        for sprint_row in sprints:
            sprint_id = sprint_row[0]
            sprint_name = sprint_row[1]
            sprint_short = sprint_row[2]

            if not sprint_id:
                continue

            try:
                # 故事数
                story_query = text("""
                    SELECT COUNT(*) FROM rdm_issue
                    WHERE sprint_id = :sprint_id
                    AND issue_type IN ('故事', '简单故事')
                """)
                story_result = session.execute(story_query, {"sprint_id": sprint_id})
                story_count = story_result.fetchone()[0] or 0   # type: ignore[attr-defined]

                # 故障数
                bug_query = text("""
                    SELECT
                        (SELECT COUNT(*) FROM rdm_issue
                         WHERE sprint_id = :sprint_id AND issue_type = '故障') +
                        (SELECT COUNT(*) FROM rdm_doc_bug
                         WHERE sprint_id = :sprint_id)
                    AS total_count
                """)
                bug_result = session.execute(bug_query, {"sprint_id": sprint_id})
                bug_count = bug_result.fetchone()[0] or 0   # type: ignore[attr-defined]

                # 故障重开「次数分布」:同一批「待测试 -> 处理中」变更记录,
                # 先按故障分组数出每只故障被重开的次数,再按次数分桶(1 次 / 2 次 / ≥3 次)。
                #
                # 口径与旧的 COUNT(DISTINCT i.issue_id) 严格同源 —— 内层每个分组恰好对应
                # 一只「重开过至少一次」的故障,故各桶之和恒等于原来的重开故障数。
                # 刻意由**同一次查询**派生 bug_reopen_count(而不是再跑一遍 DISTINCT COUNT):
                # 两处各查一次迟早会因数据写入时序而漂移,前端表格的「合计」列要求与卡片数逐字对上。
                reopen_query = text("""
                    SELECT t.reopen_times, COUNT(*) AS bug_count
                    FROM (
                        SELECT i.issue_id, COUNT(*) AS reopen_times
                        FROM rdm_issue i
                        INNER JOIN rdm_bug_changelog c ON i.issue_id = c.bug_id
                        WHERE i.sprint_id = :sprint_id
                        AND i.issue_type = '故障'
                        AND c.change_detail = '待测试 -> 处理中'
                        GROUP BY i.issue_id
                    ) AS t
                    GROUP BY t.reopen_times
                """)
                reopen_once = reopen_twice = reopen_many = 0
                reopen_rows = session.execute(reopen_query, {"sprint_id": sprint_id}).fetchall()
                for reopen_times, bucket_count in reopen_rows:
                    times = int(reopen_times or 0)
                    count = int(bucket_count or 0)
                    if times == 1:
                        reopen_once += count
                    elif times == 2:
                        reopen_twice += count
                    elif times >= 3:
                        reopen_many += count
                bug_reopen_count = reopen_once + reopen_twice + reopen_many

                # 平均时长
                avg_time_query = text("""
                    SELECT
                        COALESCE(AVG(dev_seconds), 0) as avg_dev_seconds,
                        COALESCE(AVG(test_seconds), 0) as avg_test_seconds
                    FROM rdm_bug_avgtime_sprint
                    WHERE sprint_id = :sprint_id
                """)
                avg_time_result = session.execute(avg_time_query, {"sprint_id": sprint_id})
                avg_time_row = avg_time_result.fetchone()

                metrics_list.append({
                    "sprint_id": sprint_id,
                    "sprint_name": sprint_name,
                    "short_sprint_name": sprint_short or sprint_name,
                    "story_count": story_count,
                    "bug_count": bug_count,
                    "bug_reopen_count": bug_reopen_count,
                    # 重开次数分布(只数)。三者之和 == bug_reopen_count,
                    # 供质量报表的「故障重开数」分布表按 Sprint 逐行展示。
                    "reopen_once": reopen_once,
                    "reopen_twice": reopen_twice,
                    "reopen_many": reopen_many,
                    "avg_dev_seconds": int(avg_time_row[0]) if avg_time_row and avg_time_row[0] else 0,
                    "avg_test_seconds": int(avg_time_row[1]) if avg_time_row and avg_time_row[1] else 0,
                })
            except Exception as e:
                # 单个sprint查询失败不影响其他sprint
                metrics_list.append({
                    "sprint_id": sprint_id,
                    "sprint_name": sprint_name,
                    "short_sprint_name": sprint_short or sprint_name,
                    "story_count": 0,
                    "bug_count": 0,
                    "bug_reopen_count": 0,
                    "reopen_once": 0,
                    "reopen_twice": 0,
                    "reopen_many": 0,
                    "avg_dev_seconds": 0,
                    "avg_test_seconds": 0,
                    "error": str(e)
                })

        return metrics_list


def _rate(numerator: int, denominator: int) -> float | None:
    """占比口径:分母为 0 时返回 None(前端渲染为「—」),不返回 0 ——
    0% 与「无样本」在报表上含义完全不同,不该混用同一个值。"""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _duration_days(start, end) -> int | None:
    """自然日跨度(含首尾)。任一为空或倒挂则返回 None。"""
    if not start or not end:
        return None
    start_date = start.date() if isinstance(start, datetime) else start
    end_date = end.date() if isinstance(end, datetime) else end
    if end_date < start_date:
        return None
    return (end_date - start_date).days + 1


def _workday_count(session, start, end) -> int | None:
    """[start, end] 内落在 sys_workday 上的天数。任一为空或倒挂则返回 None。

    sys_workday 是工作日的唯一源(由 holiday 任务写入),休息日 / 节假日不在表中,
    故直接 COUNT 即为区间工作日数。与 _duration_days 同规则返回 None ——
    「无区间可算」不是 0,前端据此渲染「—」而不是一个看起来真实的 0 天。
    """
    if not start or not end:
        return None
    start_date = start.date() if isinstance(start, datetime) else start
    end_date = end.date() if isinstance(end, datetime) else end
    if end_date < start_date:
        return None
    return int(session.execute(text("""
        SELECT COUNT(*) FROM sys_workday
        WHERE datestr BETWEEN :start AND :end
    """), {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
    }).fetchone()[0] or 0)


@router.get("/sprint-summary")
async def get_sprint_summary(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """Sprint 迭代概览:一次返回点击时间轴点位后弹窗所需的全部指标。

    口径说明(与既有接口保持一致,避免同一个数在两处对不上):
    - 成员数:assignee ∪ developer ∪ tester 去重人数(即「参与该迭代的人」)。
      members 数组**按任务数 DESC、姓名 ASC 排序** —— 概览弹窗的「团队成员」卡
      只铺前 3 个姓名胶囊,要让排在前面的就是「本迭代做事最多」的几个人,
      同任务数时按姓名稳定排序(否则每次刷新可能换顺序)。
      任务数同 /sprint-members 口径(assignee 的 issue_type='子任务' 数),
      仅在故事上挂 developer/tester 的成员会得到 0 ——— 这种成员仍出现在 members 里,
      姓名胶囊仍在前 3 位时等于 0 任务的人被挑出来了,但因为其他成员多数有任务,
      这种情况很少见;若全员 0 任务(空迭代或全故事无子任务),按姓名稳定排序。
    - 迭代时长:**两套区间各给一对「自然日跨度 + 工作日数」**,不混用 ——
      计划区间 = rdm_sprint.startdate → enddate,对应 duration_days / workday_count;
      实际区间 = activated_date → complete_date,对应 actual_days / actual_workday_count。
      两个自然日跨度都含首尾;两个工作日数都取自 sys_workday(工作日的唯一源,
      区间内落在该表上的天数即工作日数,休息日 / 节假日不在表中)。
      ⚠ 迭代未完成时没有 complete_date,实际区间那一对整组返回 null(不是 0)——
      「还没跑完」与「跑了 0 天」含义不同,混用会让卡片显示出误导性的 0。
    - 任务数:issue_type = '子任务'。本系统「任务到期提醒」即以后者为准
      (util/jira.py 的 sample_tasks)。rdm_issue 中另有 issue_type='任务' 的极少量行,
      但它是「有子任务的需求项」这类父级,与故事/子任务层级重叠,故不计入,避免重复。
    - 故障数:rdm_issue 的故障 + rdm_doc_bug,与 /metrics、/project-metrics 同口径。
      响应里另按来源拆成 bug_rdm_count(rdm_issue 的 issue_type='故障')与
      doc_bug_count(rdm_doc_bug),**两者之和恒等于 bug_count** ——
      供前端「故障数」卡按来源列出(为 0 的那类不列),别在别处另算一遍。
    - 计划/实际工时:rdm_issue 的 plan_worktime / actual_worktime 求和,单位**小时**。
      两列由 util/jira.py 的 rdm_report_issues 从 RDM 的 timeoriginalestimate / timespent
      换算写入;该映射上线前同步的 Sprint 为 NULL,此时返回 null,前端渲染为「待接入」。
    - 故障平均解决时长:取 rdm_bug_avgtime_sprint(工作日口径),与「故障平均解决时长」
      趋势图同源;其中 dev+test 才是完整解决过程(create→test→finish)。
    - 故事完成率:故事类中 status ∈ {已完成, 待验收} 的占比。**待验收计为完成** ——
      开发侧已交付、只差验收动作,若排除会把收口进度系统性低估。
    - 用例数 / 用例数每故事:rdm_testcase 中归属该 Sprint 的用例。该表由「文档导入」
      (doc-import 的测试用例导入)写入,归属口径 = 用例的 story_key(取自文档【需求】列)
      落在本 Sprint 的故事里。
      ⚠ 用例数取 COUNT(DISTINCT case_id):rdm_testcase 的唯一键是 (case_id, story_key),
      一个用例引用多个故事时会落多行,按行计数会把同一个用例重复累计。
      用例数每故事 = 用例数 / 故事数;故事数为 0 时返回 null(无分母,与其余比率同规则)。
    - 用例覆盖率:把 rdm_testcase.story_key 与本 Sprint 的故事类 issue_key 求交,得到
      「至少被一个用例关联过的故事」。分母复用「故事数」口径(issue_type ∈
      {故事, 简单故事},不带 status 过滤),故「已覆盖 + 未覆盖 == 故事总数」恒成立。
      故事数为 0 时返回 null(无分母,与其余比率同规则)。
      「未覆盖」的逐条明细见 /case-uncovered-stories(前端覆盖率卡下钻用),
      那边是同一集合的 NOT EXISTS 写法,两处判定必须成对修改。
    """
    with get_session() as session:
        sprint_row = session.execute(text("""
            SELECT sprint_id, sprint_name, short_sprint_name, startdate, enddate,
                   activated_date, complete_date, state
            FROM rdm_sprint
            WHERE sprint_id = :sprint_id
            LIMIT 1
        """), {"sprint_id": sprint_id}).fetchone()

        # Sprint 不存在(或已被 RDM 侧移除)时返回空对象,前端据此走空态分支
        if not sprint_row:
            return {}

        startdate, enddate = sprint_row[3], sprint_row[4]
        activated_date, complete_date = sprint_row[5], sprint_row[6]

        # ── issue 维度聚合(故事/子任务/故障/工时一次查完)──
        agg = session.execute(text("""
            SELECT
                COALESCE(SUM(issue_type IN ('故事', '简单故事')), 0) AS story_count,
                -- 「完成」= 已完成 + 待验收:待验收的故事开发侧已交付、仅差验收动作,
                -- 计入完成才与「迭代收口进度」的实际语义相符(否则最后一个 Sprint 的
                -- 完成率会被系统性低估)。状态取值见 rdm_issue.status 实际分布。
                COALESCE(SUM(issue_type IN ('故事', '简单故事')
                             AND status IN ('已完成', '待验收')), 0)
                    AS story_done_count,
                COALESCE(SUM(issue_type IN ('故事', '简单故事') AND is_unplaned = 1), 0)
                    AS story_unplanned_count,
                COALESCE(SUM(issue_type = '子任务'), 0) AS task_count,
                COALESCE(SUM(issue_type = '故障'), 0) AS bug_rdm_count,
                SUM(plan_worktime) AS plan_worktime,
                SUM(actual_worktime) AS actual_worktime,
                -- 单独给出「待验收」分量:完成率环已把它计入完成,卡片需把这个构成
                -- 说清楚,否则「故事 8 / 已完成 8」会被误读成全部通过验收。
                COALESCE(SUM(issue_type IN ('故事', '简单故事') AND status = '待验收'), 0)
                    AS story_pending_accept_count
            FROM rdm_issue
            WHERE sprint_id = :sprint_id
        """), {"sprint_id": sprint_id}).fetchone()

        if agg is not None:
            story_count = int(agg[0] or 0)
            story_done_count = int(agg[1] or 0)
            story_unplanned_count = int(agg[2] or 0)
            task_count = int(agg[3] or 0)
            bug_rdm_count = int(agg[4] or 0)
            # 两列全为 NULL 时 SUM 返回 NULL —— 原样传 None,不要兜成 0
            plan_worktime = float(agg[5]) if agg[5] is not None else None
            actual_worktime = float(agg[6]) if agg[6] is not None else None
            story_pending_accept_count = int(agg[7] or 0)

        # 文档类故障:只在 rdm_doc_bug 中,不落 rdm_issue
        doc_bug_count = session.execute(text("""
            SELECT COUNT(*) FROM rdm_doc_bug WHERE sprint_id = :sprint_id
        """), {"sprint_id": sprint_id}).fetchone()[0] or 0

        bug_count = bug_rdm_count + int(doc_bug_count)

        # ── 用例数(rdm_testcase) ──
        # 取 DISTINCT case_id 而非 COUNT(*):唯一键是 (case_id, story_key),一个用例的
        # 【需求】引用多个故事时会落多行,按行计数会把同一用例重复累计。
        case_count = int(session.execute(text("""
            SELECT COUNT(DISTINCT case_id) FROM rdm_testcase
            WHERE sprint_id = :sprint_id
        """), {"sprint_id": sprint_id}).fetchone()[0] or 0)

        # ── 用例覆盖率:本 Sprint 内「被测试用例关联过」的故事数 ──
        # 关联关系就是 rdm_testcase.story_key —— 导入侧写入的每一行都代表「某用例的
        # 【需求】引用了某故事」,故按 story_key join 即可;不附加用例侧的 sprint_id
        # 条件:故事从 A 迭代挪到 B 迭代时,导入侧按用例自身的需求清理旧行,
        # rdm_testcase.sprint_id 会停在导入当时解析出的迭代,带上该条件会让 B 迭代里
        # 这些确实被覆盖的故事被漏掉。
        # 反方向(用例侧多出来的行)由 JOIN rdm_issue 天然夹住:分子只会数到本 Sprint
        # 真实存在的故事,故「分子 ≤ 分母」有保证,覆盖率不可能超过 100%。
        case_covered_story_count = int(session.execute(text("""
            SELECT COUNT(DISTINCT i.issue_key)
            FROM rdm_issue i
            INNER JOIN rdm_testcase t ON t.story_key = i.issue_key
            WHERE i.sprint_id = :sprint_id
            AND i.issue_type IN ('故事', '简单故事')
        """), {"sprint_id": sprint_id}).fetchone()[0] or 0)

        # ── 故障重开数(与 /metrics 同口径)──
        bug_reopen_count = session.execute(text("""
            SELECT COUNT(DISTINCT i.issue_id)
            FROM rdm_issue i
            INNER JOIN rdm_bug_changelog c ON i.issue_id = c.bug_id
            WHERE i.sprint_id = :sprint_id
            AND i.issue_type = '故障'
            AND c.change_detail = '待测试 -> 处理中'
        """), {"sprint_id": sprint_id}).fetchone()[0] or 0

        # ── 团队成员(并集去重,按任务数排序)──
        # 成员范围同 /sprint-members:assignee ∪ developer ∪ tester 去重;
        # 任务数同口径 ——— 该成员作为 assignee 的 issue_type='子任务' 数(子任务
        # 只填 assignee,不存在归属歧义)。
        # 排序:任务数 DESC,姓名 ASC 作 tiebreaker ——— 概览弹窗的「团队成员」卡
        # 最多铺 3 个姓名胶囊,要让排在前面的就是「本迭代做事最多」的几个人,
        # 同任务数时按姓名排序保证结果稳定(否则每次刷新可能换顺序)。
        member_rows = session.execute(text("""
            SELECT m.member
            FROM (
                SELECT DISTINCT x.m AS member
                FROM (
                    SELECT assignee  AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                    UNION
                    SELECT developer AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                    UNION
                    SELECT tester    AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                ) x
                WHERE x.m IS NOT NULL AND x.m <> ''
            ) m
            LEFT JOIN (
                SELECT assignee AS member, COUNT(*) AS task_count
                FROM rdm_issue
                WHERE sprint_id = :sprint_id
                  AND issue_type = '子任务'
                  AND assignee IS NOT NULL AND assignee <> ''
                GROUP BY assignee
            ) t ON t.member = m.member
            ORDER BY COALESCE(t.task_count, 0) DESC, m.member ASC
        """), {"sprint_id": sprint_id}).fetchall()
        members = [r[0] for r in member_rows]

        # ── 故障平均解决时长(工作日口径)──
        avg_bug = session.execute(text("""
            SELECT COALESCE(AVG(dev_seconds), 0),
                   COALESCE(AVG(test_seconds), 0),
                   COALESCE(AVG(finish_seconds), 0)
            FROM rdm_bug_avgtime_sprint
            WHERE sprint_id = :sprint_id
        """), {"sprint_id": sprint_id}).fetchone()

        # ── 工作日数(sys_workday 是工作日的唯一源)──
        # 计划区间与「激活 → 完成」实际区间**各算一份**:两个自然日跨度
        # (duration_days / actual_days)本就分属两个区间,工作日数必须与之一一配对,
        # 否则「实际自然日 + 计划工作日」的混搭会让使用者算出错误的投入强度。
        workday_count = _workday_count(session, startdate, enddate)
        actual_workday_count = _workday_count(session, activated_date, complete_date)

        def _iso(value) -> str | None:
            """datetime → 'YYYY-MM-DD HH:mm:ss';None 原样返回 None。
            前端用 formatDate() 统一做展示层的裁剪(见 utils/datetime.ts 文件头约定),
            故这里不做「只到天」的截断,保持接口返回值的完整信息。"""
            if not value:
                return None
            if isinstance(value, datetime):
                return value.replace(microsecond=0).isoformat(sep=" ")
            return str(value)

        return {
            "sprint_id": int(sprint_row[0]),
            "sprint_name": sprint_row[1] or "",
            "short_sprint_name": sprint_row[2] or sprint_row[1] or "",
            "state": sprint_row[7] or "",

            # 迭代时长
            "start_date": _iso(startdate),
            "end_date": _iso(enddate),
            "activated_date": _iso(activated_date),
            "complete_date": _iso(complete_date),
            "duration_days": _duration_days(startdate, enddate),
            "actual_days": _duration_days(activated_date, complete_date),
            "workday_count": workday_count,
            "actual_workday_count": actual_workday_count,

            # 投入规模
            "member_count": len(members),
            "members": members,
            "plan_worktime": plan_worktime,
            "actual_worktime": actual_worktime,

            # 故事
            "story_count": story_count,
            "story_done_count": story_done_count,
            "story_pending_accept_count": story_pending_accept_count,
            "story_done_rate": _rate(story_done_count, story_count),
            "story_unplanned_count": story_unplanned_count,
            "story_unplanned_rate": _rate(story_unplanned_count, story_count),

            # 任务
            "task_count": task_count,

            # 故障
            "bug_count": bug_count,
            # 拆项:两类故障各多少。bug_count = bug_rdm_count + doc_bug_count,
            # 三者必须同源 —— 前端卡片的副标题直接列这两项,对不上就是自相矛盾。
            "bug_rdm_count": bug_rdm_count,
            "doc_bug_count": int(doc_bug_count),
            "bug_reopen_count": int(bug_reopen_count),
            "bug_reopen_rate": _rate(int(bug_reopen_count), bug_count),
            "avg_bug_dev_seconds": int(avg_bug[0] or 0),
            "avg_bug_test_seconds": int(avg_bug[1] or 0),
            "avg_bug_finish_seconds": int(avg_bug[2] or 0),

            # 用例:归属口径见 docstring(用例引用的故事 ∩ 本 Sprint 故事)
            "case_count": case_count,
            # 分母为 0 → null(「无样本」≠ 0),与其余比率同规则
            "case_per_story": (
                round(case_count / story_count, 2) if story_count else None
            ),
            # 用例覆盖率:已/未被用例关联的故事数 + 占比。分子由 JOIN rdm_issue 保证
            # 不超过分母,故未覆盖数直接用减法,无需再夹一次 0。
            "case_covered_story_count": case_covered_story_count,
            "case_uncovered_story_count": story_count - case_covered_story_count,
            "case_coverage_rate": _rate(case_covered_story_count, story_count),
        }


@router.get("/sprint-members")
async def get_sprint_members(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取指定 Sprint 的成员工作分布:成员名称 / 任务数 / 故障数。

    供「团队成员」卡下钻(TeamMembersDialog)。三个口径在此收口,与 /sprint-summary 对账:
    - 成员范围:assignee ∪ developer ∪ tester 去重,**与 /sprint-summary 的 member_count
      同一段子查询**,故弹窗行数恒等于卡片上的人数。「任务数与故障数都为 0」的行照常返回
      (只在故事上挂了 developer/tester 的人,实测每迭代 0~2 人)—— 行数与卡片一致比表格
      紧凑更重要,否则用户会以为漏了数据。
    - 任务数:该成员作为 assignee 的 issue_type='子任务' 数。子任务只填 assignee
      (实测 developer/tester 在这两列上全空),不存在归属歧义。
    - 故障数:该成员作为 bug_solver(故障修复人)的 issue_type='故障' 数。
      ⚠ 不能改用 assignee:实测故障的 assignee 与 bug_solver **零重合** —— assignee 恒为
      提单的测试人员(如 8068 迭代 17 条全挂在同一人名下),按它统计会让其余成员故障数
      全为 0、一人独吞全部,下钻失去意义;bug_solver 的分布则与子任务 assignee 高度重合
      (同为开发人员),语义上是「这人修复了多少故障」。
      bug_solver 为空串的少量行回落 assignee,避免这些故障在明细里凭空消失。
    - 文档故障(rdm_doc_bug)不参与人员归属:该表只有「产生人 / 提出人」,与其余 issue 的
      人员维度不同源,且当前全表 0 行。故本接口的故障数合计可能略小于 /sprint-summary 的
      bug_count(差量即文档故障数)。
    """
    with get_session() as session:
        rows = session.execute(text("""
            SELECT
                m.member,
                COALESCE(t.task_count, 0) AS task_count,
                COALESCE(b.bug_count, 0)  AS bug_count
            FROM (
                SELECT DISTINCT x.m AS member
                FROM (
                    SELECT assignee  AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                    UNION
                    SELECT developer AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                    UNION
                    SELECT tester    AS m FROM rdm_issue WHERE sprint_id = :sprint_id
                ) x
                WHERE x.m IS NOT NULL AND x.m <> ''
            ) m
            LEFT JOIN (
                SELECT assignee AS member, COUNT(*) AS task_count
                FROM rdm_issue
                WHERE sprint_id = :sprint_id
                  AND issue_type = '子任务'
                  AND assignee IS NOT NULL AND assignee <> ''
                GROUP BY assignee
            ) t ON t.member = m.member
            LEFT JOIN (
                SELECT COALESCE(NULLIF(bug_solver, ''), assignee) AS member,
                       COUNT(*) AS bug_count
                FROM rdm_issue
                WHERE sprint_id = :sprint_id
                  AND issue_type = '故障'
                GROUP BY member
            ) b ON b.member = m.member
            -- 有产出的排前面,0/0 行垫底(保留但不占视线);同档按人名稳定排序
            ORDER BY task_count DESC, bug_count DESC, m.member ASC
        """), {"sprint_id": sprint_id}).fetchall()

        return [
            {
                "member": row[0],
                "task_count": int(row[1] or 0),
                "bug_count": int(row[2] or 0),
            }
            for row in rows
        ]


@router.get("/sprint-reopen-members")
async def get_sprint_reopen_members(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取指定 Sprint 各成员的故障重开分布(「故障重开率」卡下钻)。

    列:成员 / 重开 1 次 / 重开 2 次 / 重开多次(≥3 次)。
    口径与 /bugs/reopen、/project-metrics 的 reopen 计数**严格同源**:
      同 INNER JOIN(rdm_issue × rdm_bug_changelog)、同 WHERE(issue_type='故障'
      且 change_detail='待测试 -> 处理中'),故「某成员三档之和」恒等于该成员被重开的
      故障数,所有成员三档之和恒等于 /sprint-summary 的 bug_reopen_count。
    成员身份取故障修复人 COALESCE(NULLIF(bug_solver,''), assignee),与
      /sprint-members 的故障归属口径一致(实测故障 assignee 与 bug_solver 零重合,
      按 assignee 统计会全挤在提单测试一人名下)。
    ⚠ 「多次」下界 = 3,与 /project-metrics 的 reopen_many 同口径。
      (2026-09-21 起前端不再展示这条边界:重开数卡的副标题已按用户要求删除,
       界面上只留列头「重开多次」,前端那份常量随之删掉 —— 一致性从此只由后端各处判定对齐。)

    只返回「至少有一条重开故障」的成员 —— 内层查询只含被重开的故障,没有重开记录的
    成员自然不出现(满足「没有数据的成员不展示」);若迭代整体无重开故障(该卡仅在
    bug_reopen_count>0 时才能点击,理论上不会走到这里),返回空数组,前端据此不展示列表。
    """
    with get_session() as session:
        rows = session.execute(text("""
            SELECT
                member,
                SUM(CASE WHEN reopen_times = 1 THEN 1 ELSE 0 END) AS reopen_once,
                SUM(CASE WHEN reopen_times = 2 THEN 1 ELSE 0 END) AS reopen_twice,
                SUM(CASE WHEN reopen_times >= 3 THEN 1 ELSE 0 END) AS reopen_many,
                COUNT(*) AS reopen_total
            FROM (
                SELECT
                    COALESCE(NULLIF(i.bug_solver, ''), i.assignee) AS member,
                    COUNT(*) AS reopen_times
                FROM rdm_issue i
                INNER JOIN rdm_bug_changelog c ON i.issue_id = c.bug_id
                WHERE i.sprint_id = :sprint_id
                  AND i.issue_type = '故障'
                  AND c.change_detail = '待测试 -> 处理中'
                GROUP BY i.issue_id, COALESCE(NULLIF(i.bug_solver, ''), i.assignee)
            ) t
            WHERE t.member IS NOT NULL AND t.member <> ''
            GROUP BY t.member
            ORDER BY reopen_total DESC, t.member ASC
        """), {"sprint_id": sprint_id}).fetchall()

        return [
            {
                "member": row[0],
                "reopen_once": int(row[1] or 0),
                "reopen_twice": int(row[2] or 0),
                "reopen_many": int(row[3] or 0),
                "reopen_total": int(row[4] or 0),
            }
            for row in rows
        ]


@router.get("/unplanned-stories")
async def get_unplanned_stories(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取指定 Sprint 的计划外故事列表(按创建时间升序)。
    计划外 = rdm_issue.is_unplaned = 1,即故事在 Sprint 激活之后才创建(中途插入)。
    与 /sprint-summary 的 story_unplanned_count 同源,此处把计数展开为逐条明细,
    供「计划外故事占比」卡下钻查看。"""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                issue_key,
                issue_name,
                status,
                COALESCE(priority, '') AS priority,
                COALESCE(assignee, '') AS assignee,
                created
            FROM rdm_issue
            WHERE sprint_id = :sprint_id
              AND issue_type IN ('故事', '简单故事')
              AND is_unplaned = 1
            ORDER BY created ASC
        """), {"sprint_id": sprint_id}).fetchall()

        return [
            {
                "issue_key": row[0],
                "issue_name": row[1] or '',
                "status": row[2] or '',
                "priority": row[3],
                "assignee": row[4],
                "created": row[5].isoformat(sep=" ") if row[5] else None,
            }
            for row in result
        ]


@router.get("/case-uncovered-stories")
async def get_case_uncovered_stories(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """获取指定 Sprint 中「未被任何测试用例覆盖」的故事列表(按创建时间升序)。

    与 /sprint-summary 的 case_uncovered_story_count **同源互补**:那边用
    INNER JOIN rdm_testcase 数「被引用过的故事」,这里用 NOT EXISTS 取其补集,
    两个判定逐字对偶,故「本接口行数 + 覆盖数 == 故事总数」恒成立 ——
    改任一侧的关联条件都必须同时改另一侧,否则卡片与列表会对不上。

    行结构、排序与 /unplanned-stories 完全一致(前端两张列表共用同一个弹窗),
    故这里也只做「把计数展开成逐条明细」。

    ⚠ 关联只看 rdm_testcase.story_key,**不带该表的 sprint_id 条件**:
      故事从 A 迭代挪到 B 迭代时,导入侧按用例自身的需求清理旧行,
      rdm_testcase.sprint_id 会停在导入当时解析出的迭代,带上它会把 B 迭代里
      确实被用例覆盖的故事误判成「未覆盖」(与 /sprint-summary 的覆盖率口径同源)。"""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                i.issue_key,
                i.issue_name,
                i.status,
                COALESCE(i.priority, '') AS priority,
                COALESCE(i.assignee, '') AS assignee,
                i.created
            FROM rdm_issue i
            WHERE i.sprint_id = :sprint_id
              AND i.issue_type IN ('故事', '简单故事')
              AND NOT EXISTS (
                  SELECT 1 FROM rdm_testcase t WHERE t.story_key = i.issue_key
              )
            ORDER BY i.created ASC
        """), {"sprint_id": sprint_id}).fetchall()

        return [
            {
                "issue_key": row[0],
                "issue_name": row[1] or '',
                "status": row[2] or '',
                "priority": row[3],
                "assignee": row[4],
                "created": row[5].isoformat(sep=" ") if row[5] else None,
            }
            for row in result
        ]


@router.get("/worktime-mismatch")
async def get_worktime_mismatch(
    sprint_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    """某个 Sprint 里**计划工时与投入工时不相等**的条目(两个方向都列)。

    用户 2026-09-17:概览里「工时」卡在投入大于计划时可点击,要看的是「这些数为什么对不上」。

    ⚠⚠ **必须两个方向都列**(既含投入 > 计划,也含投入 < 计划)。
      起初只列了超支方向,用户一眼就发现"明细里的超出和卡片上的对不上" ——
      因为欠报的那部分被丢掉了,清单里「差额」列相加必然大于卡片的净差额
      (实测 botadp-Sprint-11:只列超支 = +28,净差额 = +8)。
      全列之后恒等式成立:
          sum(rows[*].delta) == delta_total
      这也是本接口顺带把 delta_total 回吐的原因 —— 让「清单能不能对上卡片」
      是一条**可断言的等式**(见 tests/unit/test_worktime_mismatch.py),而不是只能靠肉眼。
      ⚠ 别为了"清单好看"再把它过滤回单方向。

    ⚠ 判定用 COALESCE 后比较(两侧的 NULL 都按 0 计):
      · 两侧都为空的行(该表里上百行)不算不一致,不计入;
      · 计划有值而投入为空 ⇒ 差额 = −计划,要列(投入漏填);
      · 计划为空而有投入 ⇒ 差额 = +投入,要列(计划漏填,通常最该先修的那类)。

    逐条看才是可执行的:合计是 SUM 出来的,「某一条多报 20 小时」与「十条各多报 2 小时」
    在卡片上完全同形,而要改数据只能落到具体 issue。
    合计口径与 /sprint-summary 的 plan_worktime / actual_worktime 逐字同源
    (同表、同 sprint_id、不筛 issue_type)。
    """
    with get_session() as session:
        # 整迭代合计:与概览卡片同口径(全表、按 sprint 聚合,不筛 issue_type)
        totals = session.execute(text("""
            SELECT SUM(plan_worktime), SUM(actual_worktime)
            FROM rdm_issue
            WHERE sprint_id = :sprint_id
        """), {"sprint_id": sprint_id}).fetchone()

        rows = session.execute(text("""
            SELECT
                issue_key,
                issue_name,
                COALESCE(issue_type, '') AS issue_type,
                COALESCE(assignee, '') AS assignee,
                COALESCE(status, '') AS status,
                plan_worktime,
                actual_worktime
            FROM rdm_issue
            WHERE sprint_id = :sprint_id
              -- NULL 一律按 0 参与比较:两侧都空的行不算不一致
              AND COALESCE(actual_worktime, 0) <> COALESCE(plan_worktime, 0)
            -- 排序键就是这一列显示的差额(两个符号都在),差额大的在前:
            -- 要动手改的通常是最上面(多报)与最下面(漏填)那几条。
            -- ⚠ 二级键必须给:差额相同的行若顺序不定,两次打开弹窗行序会变,看起来像数据在动。
            ORDER BY (COALESCE(actual_worktime, 0) - COALESCE(plan_worktime, 0)) DESC, issue_key
        """), {"sprint_id": sprint_id}).fetchall()

    # ⚠ 一律 float():这两列在 MySQL 里是 FLOAT,SQLAlchemy 可能回 Decimal,
    #   而 Decimal 与 float 混算会抛 TypeError、FastAPI 也无法直接序列化 Decimal。
    plan_total = float(totals[0]) if totals and totals[0] is not None else None
    actual_total = float(totals[1]) if totals and totals[1] is not None else None

    items = []
    for r in rows:
        plan = float(r[5]) if r[5] is not None else None
        actual = float(r[6]) if r[6] is not None else None
        items.append({
            "issue_key": r[0],
            "issue_name": r[1] or "",
            "issue_type": r[2],
            "assignee": r[3],
            "status": r[4],
            "plan_worktime": plan,
            "actual_worktime": actual,
            # 差额由后端算好:前端各处再算一遍,口径漂了就会自相矛盾(保留两位,浮点求和有尾数)
            "delta": round((actual or 0.0) - (plan or 0.0), 2),
        })

    return {
        "sprint_id": sprint_id,
        # 整迭代合计与净差额(卡片口径)。UI 不展示它们(清单本身已经把净差额加得出来),
        # 回吐是为了让「sum(rows.delta) == delta_total」这条恒等式可被断言。
        "plan_total": plan_total,
        "actual_total": actual_total,
        "delta_total": (
            round(actual_total - plan_total, 2)
            if plan_total is not None and actual_total is not None else None
        ),
        "rows": items,
    }
