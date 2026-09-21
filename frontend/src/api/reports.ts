import { get } from './index'
import type { ProjectOption, SprintOption, SprintMetrics } from './types'

export type { ProjectOption, SprintOption, SprintMetrics } from './types'

export interface BugDetailResponse {
  developers: { developer: string; total: number }[]
  priorities: string[]
  tags: string[]
  data: Record<string, Record<string, Record<string, number>>>
}

export interface BugListItem {
  index: number
  issue_key: string
  developer: string
  priority: string
  issue_name: string
  reason_analysis: string
  is_typical: string
  source: string
  tag: string
  /** 文档故障的现场截图张数;RDM 故障恒为 0(它们不存截图) */
  image_count: number
}

/**
 * 一只被重开过的故障(一个 Sprint 一行,来自 /reports/bugs/reopen)。
 *
 * 只有 RDM 故障会出现在这里(重开次数取自 rdm_bug_changelog 的流转),故没有 source 字段。
 */
export interface ReopenBugItem {
  /** 行序号,由后端按「优先级 → 编码」的排序结果给出 */
  index: number
  issue_key: string
  issue_name: string
  /** 开发(修复人):后端取 bug_maker,缺失时回落 reporter,再兜底「其他」 */
  bug_maker: string
  /**
   * 原因及分析。RDM 口径下这就是 rdm_issue.bug_reason 全文 —— 与「故障明细」
   * (/bugs/list)的 reason_analysis 是同一个值(那条查询也是 `bug_reason as reason_text`),
   * 故这里直接复用字段,不再多返回一个同名的 reason_analysis。
   */
  bug_reason: string
  priority: string
  /** 标签:由后端 parse_tag 把「原因」首段归一到规范词,与 /bugs/list 的 tag 同一出口 */
  tag: string
  /** 该故障被重开的次数(≥1):同一只故障 '待测试 -> 处理中' 的流转次数 */
  reopen_times: number
  /** 以下三项接口仍返回,本版重开列表不展示(留给后续列或别处复用) */
  reporter: string
  bug_type: string
  resolution: string
}

export interface SprintMetricsItem {
  sprint_id: number
  sprint_name: string
  /**
   * 后端仍返回该字段,但**前端展示一律用 sprint_name** —— 缩写名在同一项目内会撞名
   * (如 EMBODIED-Sprint1 与 botadp-Sprint-1 都缩成 Sprint1),故不再消费此列。
   */
  short_sprint_name: string
  story_count: number
  bug_count: number
  bug_reopen_count: number
  /**
   * 重开次数分布(只数),供质量报表的「故障重开数」分布表按 Sprint 展示。
   * 口径:同一只故障的 `待测试 -> 处理中` 变更次数 —— 1 次 / 2 次 / ≥3 次。
   * 三者之和恒等于 bug_reopen_count(后端由同一次分组查询派生,不是各查一遍)。
   */
  reopen_once: number
  reopen_twice: number
  reopen_many: number
  avg_dev_seconds: number
  avg_test_seconds: number
}

export interface AvgTimeDeveloperItem {
  index: number
  developer: string
  bug_id: number | null
  issue_key: string
  issue_name: string
  status: string
  dev_seconds: number
  test_seconds: number
  total_seconds: number
}

/** 单条「计划与投入不一致」的工时明细(迭代概览「工时」卡下钻)。 */
export interface WorktimeMismatchRow {
  issue_key: string
  issue_name: string
  /** 故事 / 子任务 / 故障 */
  issue_type: string
  assignee: string
  status: string
  /** null = 该侧未填工时(显示占位「—」,参与差额计算时按 0 计) */
  plan_worktime: number | null
  actual_worktime: number | null
  /** 投入 − 计划(缺失的一侧按 0 计)，由后端算好，前端不重算。**有正有负** */
  delta: number
}

export interface WorktimeMismatchResponse {
  sprint_id: number
  /** 整迭代合计 —— 与迭代概览的工时卡同口径(全表按 sprint 求和) */
  plan_total: number | null
  actual_total: number | null
  /**
   * 整迭代净差额(与卡片同源)。
   * ⚠ 恒等式:`sum(rows[*].delta) === delta_total` —— 清单**两个方向都列**才成立
   *   (只列超支方向时,清单之和必然大于它)。这是"清单能不能对上卡片"的判据,
   *   UI 不展示它(清单本身加得出来),留着是为了让这条等式可被断言。
   */
  delta_total: number | null
  /** 计划与投入不相等的条目,按 delta 从大到小 */
  rows: WorktimeMismatchRow[]
}

export interface UnplannedStoryItem {
  issue_key: string
  issue_name: string
  status: string
  priority: string
  assignee: string
  /** 创建时间(datetime 串或 null);展示层用 formatDate 裁剪 */
  created: string | null
}

/**
 * 单个成员在某 Sprint 内的工作分布(「团队成员」卡下钻用)。
 *
 * 口径(与后端 /reports/sprint-members 的 docstring 一致):
 * - 行集 = 概览「团队成员」的成员集合(assignee ∪ developer ∪ tester 去重),
 *   故行数恒等于卡片上的 member_count;任务数与故障数都为 0 的成员照常返回。
 * - task_count:该成员作为经办人的子任务数
 * - bug_count:该成员作为**故障修复人**修复的故障数(而非故障的经办人 ——
 *   实测故障经办人恒为提单的测试人员,按它统计会全挤在一人名下)
 */
export interface SprintMemberItem {
  member: string
  task_count: number
  bug_count: number
}

/**
 * 单个成员在某 Sprint 内的故障重开分布。
 *
 * ⚠ 自 2026-09-21 起前端已无消费方:原先它是「故障重开率」卡的下钻(ReopenMembersDialog),
 *   该卡的点击现在打开「故障重开列表」(ReportReopenDialog),而按成员的分布在那份列表里
 *   由「开发」+「重开次数」两列直接可读。接口 /reports/sprint-reopen-members 仍在后端保留,
 *   故类型也一并留着 —— 要用回那张表时把类型与 api 方法接上即可。
 */
export interface SprintReopenMemberItem {
  member: string
  /** 该成员被重开恰好 1 次的故障数 */
  reopen_once: number
  /** 该成员被重开恰好 2 次的故障数 */
  reopen_twice: number
  /** 该成员被重开 ≥3 次的故障数(「多次」下界 = 3,与后端 /sprint-reopen-members 的判定同源) */
  reopen_many: number
  /** 该成员被重开的故障总数(= reopen_once + reopen_twice + reopen_many) */
  reopen_total: number
}

export interface BugChangelogItem {
  index: number
  issue_key: string
  change_type: string
  change_time: string
  change_detail: string
  /** 相对上一步的工作日耗时(秒) */
  elapsed_seconds: number
}

/**
 * 单只 RDM 故障的详情(统一「故障详情」弹窗用,对应 GET /reports/bugs/one)。
 *
 * 字段直接沿用 DB 列名 —— 展示口径(哪些字段、以什么顺序、怎么格式化)留在组件里,
 * 后端只负责把这一行原样回吐。`changelog` 是**内联**进来的变更记录:
 * 它天然属于「这只故障的详情」,量又极小,拆成第二个请求只会让弹窗多等一次往返。
 *
 * ⚠ `issue_key` 在 rdm_issue 里**不是唯一键**:同一只故障可能被多个 Sprint 各拉一行
 * (实测 JSST-560 同时属于 JSST-1.0-Sprint-1/6845 与 JSST-1.0-Sprint-3/6954,
 * 两行 issue_id 相同、只有 sprint 快照不同)。故取详情时最好把当前列表的 sprintId 一并传入。
 */
export interface RdmBugDetail {
  source: 'RDM'
  issue_id: string | null
  issue_key: string | null
  issue_type: string | null
  issue_name: string | null
  status: string | null
  resolution: string | null
  priority: string | null
  reporter: string | null
  assignee: string | null
  developer: string | null
  tester: string | null
  bug_maker: string | null
  bug_solver: string | null
  created: string | null
  updated: string | null
  duedate: string | null
  module: string | null
  bug_story: string | null
  bug_type: string | null
  bug_flag: string | null
  bug_reason: string | null
  callback: number | null
  is_unplaned: number | null
  sprint_id: string | null
  sprint_name: string | null
  description: string | null
  changelog: BugChangelogItem[]
}

/**
 * 单个 Sprint 的迭代概览(点击时间轴点位弹窗的数据)。
 *
 * 空值语义:null 一律表示「该指标当前无数据」,而非 0 ——
 *   - plan_worktime / actual_worktime:rdm_issue 的两列由同步逻辑从 RDM 的
 *     timeoriginalestimate / timespent 回填,映射上线前的历史 Sprint 为 null,
 *     弹窗渲染为「待同步」预留卡片;
 *   - case_per_story / case_coverage_rate:故事数为 0 时没有分母,返回 null
 *     (用例数为 0 是真实值,照实返回)。
 * 比率类字段为 0~1 的小数;分母为 0 时后端返回 null(而非 0)。
 */
export interface SprintSummary {
  sprint_id: number
  sprint_name: string
  /** 后端仍返回,但**前端展示一律用 sprint_name**(概览弹窗标题同此口径) */
  short_sprint_name: string
  state: string

  /** 计划区间起止(后端为 datetime 串,展示层用 formatDate 裁剪) */
  start_date: string | null
  end_date: string | null
  /** Sprint 激活 / 完成时刻 */
  activated_date: string | null
  complete_date: string | null
  /** 计划跨度(自然日,含首尾)与区间内工作日数 */
  duration_days: number | null
  workday_count: number | null
  /** 实际跨度:激活 → 完成(自然日);未完成时为 null */
  actual_days: number | null

  member_count: number
  /**
   * 成员列表(姓名数组),后端按「任务数 DESC、姓名 ASC」排序 —— 概览弹窗的
   * 「团队成员」卡最多铺前 3 个姓名胶囊,要让排在前面的就是「本迭代做事最多」
   * 的几个人,同任务数时按姓名稳定排序。
   * 任务数同 /sprint-members 口径(assignee 的 issue_type='子任务' 数),
   * 没分到子任务的人(只挂在 developer / tester)会出现 0 任务,仍出现在列表里。
   */
  members: string[]

  /** 单位:小时。null = 尚未同步到工时数据 */
  plan_worktime: number | null
  actual_worktime: number | null

  story_count: number
  /** 已完成故事数,含「待验收」(待验收视为已交付,只差验收动作) */
  story_done_count: number
  /** 上述完成数中处于「待验收」的分量,用于在卡片上说明构成 */
  story_pending_accept_count: number
  /** 已完成故事 / 故事总数,0~1(分子含待验收) */
  story_done_rate: number | null
  story_unplanned_count: number
  /** 计划外故事 / 故事总数,0~1 */
  story_unplanned_rate: number | null
  /** 故事平均完成时长(工作日秒);无样本为 null */
  avg_story_seconds: number | null
  story_sample_count: number

  /** issue_type = '子任务'(与「任务到期提醒」同口径) */
  task_count: number

  bug_count: number
  /** 故障按来源拆项:RDM 故障 = rdm_issue 中 issue_type='故障' 的行。
   *  与 doc_bug_count 之和**恒等于** bug_count(「故障数」卡按这两项列来源构成) */
  bug_rdm_count: number
  /** 故障按来源拆项:文档故障 = rdm_doc_bug,只落这张表、不进 rdm_issue */
  doc_bug_count: number
  bug_reopen_count: number
  /** 重开故障 / 故障总数,0~1 */
  bug_reopen_rate: number | null
  /** 故障数 / 成员数 */
  bug_per_member: number | null
  /** 故障平均解决时长(工作日秒)。dev+test 才是完整「创建 → 关闭」过程 */
  avg_bug_dev_seconds: number
  avg_bug_test_seconds: number
  avg_bug_finish_seconds: number

  /** 归属本 Sprint 的用例数(用例引用的故事 ∩ 本 Sprint 故事,按 case_id 去重) */
  case_count: number
  /** 用例数 / 故事数;故事数为 0 时无分母 → null */
  case_per_story: number | null
  /** 被至少一个用例关联过的故事数(rdm_testcase.story_key ∩ 本 Sprint 故事) */
  case_covered_story_count: number
  /** 故事总数中未被任何用例关联的部分 = story_count - case_covered_story_count */
  case_uncovered_story_count: number
  /** 用例覆盖率 = 已覆盖故事 / 故事总数,0~1;故事数为 0 时无分母 → null */
  case_coverage_rate: number | null
}

export interface BurndownResponse {
  sprint_id: number
  sprint_name: string
  start_date: string | null
  end_date: string | null
  total: number
  /** 横轴日期(MM-DD) */
  dates: string[]
  /** 实际剩余故事数(按天) */
  actual: number[]
  /** 理想剩余故事数(线性递减) */
  ideal: number[]
}

export const reportsApi = {
  getProjects(): Promise<ProjectOption[]> {
    return get<ProjectOption[]>('/reports/projects')
  },

  /**
   * 质量报表专用:仅读数据库存量 Sprint(`/reports/db-sprints`),不触发 RDM 实时拉取。
   *
   * ⚠ 作业页「手动执行」弹窗的 Sprint 下拉**不用这个** —— 它需要选到本地库还没同步的
   *   新迭代,走的是 `@/api/projects` 的 `sprintApi.getSprints`(`/reports/sprints`,
   *   RDM 实时且会回写 rdm_sprint)。两者同名不同源,改动前先确认调用方。
   */
  getSprints(projectId: number): Promise<SprintOption[]> {
    return get<SprintOption[]>(`/reports/db-sprints/${projectId}`)
  },

  getMetrics(sprintId: number): Promise<SprintMetrics> {
    return get<SprintMetrics>('/reports/metrics', { sprint_id: sprintId })
  },

  /** 获取Sprint故事燃尽图数据(实际剩余线 + 理想线) */
  getBurndown(sprintId: number): Promise<BurndownResponse> {
    return get<BurndownResponse>('/reports/burndown', { sprint_id: sprintId })
  },

  getBugDetails(sprintId: number): Promise<BugDetailResponse> {
    return get<BugDetailResponse>('/reports/bugs/detail', { sprint_id: sprintId })
  },

  getBugList(sprintId: number, developer?: string, priority?: string, tag?: string): Promise<BugListItem[]> {
    return get<BugListItem[]>('/reports/bugs/list', {
      sprint_id: sprintId,
      developer: developer || '',
      priority: priority || '',
      tag: tag || '',
    })
  },

  getBugAvgTime(sprintId: number): Promise<{ avg_dev_seconds: number; avg_test_seconds: number }> {
    return get<{ avg_dev_seconds: number; avg_test_seconds: number }>('/reports/bugs/avg-time', {
      sprint_id: sprintId,
    })
  },

  getBugAvgTimeByDevelopers(sprintId: number): Promise<AvgTimeDeveloperItem[]> {
    return get<AvgTimeDeveloperItem[]>('/reports/bugs/avg-time/developers', { sprint_id: sprintId })
  },

  getBugChangelog(bugId: number): Promise<BugChangelogItem[]> {
    return get<BugChangelogItem[]>('/reports/bugs/changelog', { bug_id: bugId })
  },

  /**
   * 单只 RDM 故障的详情(字段 + 内联变更记录)。
   *
   * sprintId 可选但**建议传**:issue_key 在 rdm_issue 里不唯一(同一故障被多个 Sprint
   * 各拉一行),传了才能精确到当前列表对应的那一次拉取;不传则后端按 updated 取一行。
   * 不传时**必须整体省略该参数** —— 传空串会被 FastAPI 判成 422(它声明的是 int|None)。
   */
  getBugOne(issueKey: string, sprintId?: number | null): Promise<RdmBugDetail> {
    return get<RdmBugDetail>('/reports/bugs/one', {
      issue_key: issueKey,
      ...(sprintId != null ? { sprint_id: sprintId } : {}),
    })
  },

  getReopenBugs(sprintId: number): Promise<ReopenBugItem[]> {
    return get<ReopenBugItem[]>('/reports/bugs/reopen', { sprint_id: sprintId })
  },

  /** limit>0 时仅返回最近 N 个 sprint,limit=0 返回全部(放大视图用) */
  getProjectMetrics(projectId: number, limit = 7): Promise<SprintMetricsItem[]> {
    return get<SprintMetricsItem[]>(`/reports/project-metrics/${projectId}`, { limit })
  },

  /** 单个 Sprint 的迭代概览(点击时间轴点位弹窗用)。Sprint 不存在时后端返回 {} */
  getSprintSummary(sprintId: number): Promise<SprintSummary> {
    return get<SprintSummary>('/reports/sprint-summary', { sprint_id: sprintId })
  },

  /** 指定 Sprint 的计划外故事列表(「计划外故事占比」卡下钻用)。无计划外故事时返回空数组 */
  getUnplannedStories(sprintId: number): Promise<UnplannedStoryItem[]> {
    return get<UnplannedStoryItem[]>('/reports/unplanned-stories', { sprint_id: sprintId })
  },

  /** 指定 Sprint 的成员工作分布(「团队成员」卡下钻用)。行数 = 概览成员数 */
  getSprintMembers(sprintId: number): Promise<SprintMemberItem[]> {
    return get<SprintMemberItem[]>('/reports/sprint-members', { sprint_id: sprintId })
  },

  /**
   * 指定 Sprint 各成员的故障重开分布。仅含有重开记录的成员。
   *
   * ⚠ 2026-09-21 起**暂无调用方**:「故障重开率」卡改为下钻「故障重开列表」
   *   (getReopenBugs + ReportReopenDialog),不再打开「按成员分布」那张表。
   *   保留此方法与上面的类型,是为了和后端仍注册着的 /reports/sprint-reopen-members
   *   保持一一对应(api/ 层就是后端契约的镜像);要恢复那张表,才需要重新写组件。
   */
  getSprintReopenMembers(sprintId: number): Promise<SprintReopenMemberItem[]> {
    return get<SprintReopenMemberItem[]>('/reports/sprint-reopen-members', { sprint_id: sprintId })
  },

  /**
   * 指定 Sprint 里「投入 > 计划」的工时条目(「工时」卡下钻用)。
   * 只在投入大于计划时才可下钻;返回里带该 Sprint 的计划/投入合计,便于弹窗自证口径。
   */
  getWorktimeMismatch(sprintId: number): Promise<WorktimeMismatchResponse> {
    return get<WorktimeMismatchResponse>('/reports/worktime-mismatch', { sprint_id: sprintId })
  },
}
