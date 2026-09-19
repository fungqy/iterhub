/**
 * 跨模块复用的公共接口与类型
 * 作为 ProjectOption / SprintOption / SprintMetrics 等接口的唯一来源,
 * 各 api 模块从这里 re-export,避免在 projects/reports 重复定义。
 */

export interface ProjectOption {
  id: number
  project_id: string
  project_name: string
  board_name: string
}

export interface SprintOption {
  sprint_id: number
  sprint_name: string
  start_date: string | null
  end_date: string | null
  /** Sprint 激活时间(YYYY-MM-DD HH:mm:ss)，未激活为 null */
  activated_date: string | null
  state: string | null
  has_report_data?: boolean
}

export interface SprintMetrics {
  story_count: number
  bug_count: number
  bug_reopen_count: number
}