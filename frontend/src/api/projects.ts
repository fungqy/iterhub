import { get, post, put, del } from './index'
import type { SprintOption } from './types'

// ⚠ 报告类接口的**实现与类型统一收敛在 @/api/reports**,本模块不再重复定义
//   (历史上这里另有一份 BugDetailResponse / BugListItem / ReopenBugItem 与
//    getBugList,签名还与 reports.ts 的参数顺序相反,属于随时会踩的坑)。
//   这里只保留 re-export,避免打断既有 `from '@/api/projects'` 的引用。
export type { ProjectOption, SprintOption, SprintMetrics } from './types'

export interface ReminderSettings {
  need_story_remind: boolean
  need_task_remind: boolean
  need_sonar_scan_remind: boolean
  need_report_data: boolean
  story_remind_time?: string
  task_remind_time?: string
  sonar_remind_time?: string
}

export interface ProjectConfig {
  id: number
  board_id: string
  board_name: string
  project_id: string
  project_name: string
  gitlab_group_key: string
  sonar_key_prefix: string
  sonar_scan_remind_default_person: string
  robot_key: string
  jira_user: string
  jira_token?: string
  created_at?: string
  updated_at?: string
  need_story_remind?: boolean
  need_task_remind?: boolean
  need_sonar_scan_remind?: boolean
  need_report_data?: boolean
  story_remind_time?: string
  task_remind_time?: string
  sonar_remind_time?: string
  reminder_settings?: ReminderSettings
}

export interface ProjectFormData {
  id?: number
  board_id: string
  board_name: string
  project_id: string
  project_name: string
  gitlab_group_key: string
  sonar_key_prefix: string
  sonar_scan_remind_default_person: string
  robot_key: string
  jira_user: string
  jira_token: string
  need_story_remind: boolean
  need_task_remind: boolean
  need_sonar_scan_remind: boolean
  need_report_data: boolean
  story_remind_time: string
  task_remind_time: string
  sonar_remind_time: string
}

/** 创建/更新项目的请求体:开关字段嵌套在 reminder_settings 中 */
export interface ProjectPayload extends Omit<ProjectFormData, 'need_story_remind' | 'need_task_remind' | 'need_sonar_scan_remind' | 'need_report_data' | 'story_remind_time' | 'task_remind_time' | 'sonar_remind_time'> {
  reminder_settings: ReminderSettings
}

export const projectApi = {
  getList(): Promise<ProjectConfig[]> {
    return get<ProjectConfig[]>('/projects')
  },

  /**
   * 单个项目详情。
   *
   * ⚠ 编辑表单必须走这里而不是复用列表行:列表接口对 robot_key 做了脱敏,
   *   拿列表值填表单再保存会把掩码写回库,真实 webhook key 被覆盖。
   *   详情接口返回明文(含 jira_token),供表单回显。
   */
  getById(id: number): Promise<ProjectConfig> {
    return get<ProjectConfig>(`/projects/${id}`)
  },

  create(data: ProjectPayload): Promise<ProjectConfig> {
    return post<ProjectConfig>('/projects', data)
  },

  update(id: number, data: ProjectPayload): Promise<ProjectConfig> {
    return put<ProjectConfig>(`/projects/${id}`, data)
  },

  delete(id: number): Promise<void> {
    return del<void>(`/projects/${id}`)
  },
}

/**
 * RDM **实时**迭代列表(作业页「手动执行」弹窗的 Sprint 下拉数据源)。
 *
 * ⚠ 与 `@/api/reports` 的 `reportsApi.getSprints` **同名但不同源**,别混用:
 *   - 本模块(这里):`GET /reports/sprints/{id}` —— 直连 RDM 实时拉取,
 *     拉取成功还会全量重写本地 `rdm_sprint`(见后端 reports.py 该端点的副作用说明);
 *     好处是新迭代**首次同步前**也能选到。
 *   - `@/api/reports`: `GET /reports/db-sprints/{id}` —— 只读本地库,不碰 RDM。
 *
 * ⚠ 导出名刻意**不叫** `reportsApi`:同名导出会让编辑器的自动导入选错文件,
 *   而两者一旦选错就是「静默换了数据源」而不是编译报错。
 */
export const sprintApi = {
  getSprints(projectId: number): Promise<SprintOption[]> {
    return get<SprintOption[]>(`/reports/sprints/${projectId}`)
  },
}