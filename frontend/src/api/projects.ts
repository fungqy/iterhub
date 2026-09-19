import { get, post, put, del } from './index'
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
}

export interface ReopenBugItem {
  index: number
  issue_key: string
  issue_name: string
  bug_maker: string
  reporter: string
  bug_type: string
  priority: string
  bug_reason: string
  resolution: string
}

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

export const reportsApi = {
  getProjects(): Promise<ProjectOption[]> {
    return get<ProjectOption[]>('/reports/projects')
  },

  getSprints(projectId: number): Promise<SprintOption[]> {
    return get<SprintOption[]>(`/reports/sprints/${projectId}`)
  },

  getMetrics(sprintId: number): Promise<SprintMetrics> {
    return get<SprintMetrics>('/reports/metrics', { sprint_id: sprintId })
  },

  getBugDetails(sprintId: number): Promise<BugDetailResponse> {
    return get<BugDetailResponse>('/reports/bugs/detail', { sprint_id: sprintId })
  },

  getBugList(sprintId: number, priority: string, tag: string, developer?: string): Promise<BugListItem[]> {
    return get<BugListItem[]>('/reports/bugs/list', {
      sprint_id: sprintId,
      developer: developer || '',
      priority,
      tag,
    })
  },

  getBugAvgTime(sprintId: number): Promise<{ avg_dev_seconds: number; avg_test_seconds: number }> {
    return get<{ avg_dev_seconds: number; avg_test_seconds: number }>('/reports/bugs/avg-time', {
      sprint_id: sprintId,
    })
  },

  getReopenBugs(sprintId: number): Promise<ReopenBugItem[]> {
    return get<ReopenBugItem[]>('/reports/bugs/reopen', { sprint_id: sprintId })
  },
}