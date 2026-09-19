// 任务类型与执行状态的唯一口径源。
//
// 所有页面(工作台/任务调度/项目信息)的标签、配色、下拉选项都必须从这里取,
// 禁止各自再定义 map —— 历史上 Dashboard.vue 与 jobsConstants.ts 各写一份,
// 导致同一状态出现「待执行 / 等待中」两种说法,且 Dashboard 缺 sonar_reminder
// 与 running 两项,界面上直接露出英文原值。
//
// 新增任务类型或状态时:**只改本文件**。

/** PrimeVue Tag 允许的 severity 取值 */
export type TagSeverity = 'success' | 'info' | 'warn' | 'danger' | 'contrast' | 'secondary'

/** 任务类型 → 中文名。叫法统一为「代码扫描」,对齐主导航。 */
export const TASK_TYPE_LABELS: Record<string, string> = {
  story_reminder: '进度提醒',
  task_reminder: '任务提醒',
  sonar_reminder: '代码扫描',
  report_data: '报表数据',
}

/** 任务类型筛选下拉。空值项代表「全部」,由 Select 的 showClear 触发。 */
export const TASK_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: '全部' },
  { value: 'story_reminder', label: '进度提醒' },
  { value: 'task_reminder', label: '任务提醒' },
  { value: 'sonar_reminder', label: '代码扫描' },
  { value: 'report_data', label: '报表数据' },
]

/** 任务类型 → Tag 配色 */
export const TASK_TYPE_SEVERITY: Record<string, TagSeverity> = {
  story_reminder: 'info',
  task_reminder: 'success',
  sonar_reminder: 'warn',
  report_data: 'contrast',
}

/** 执行状态 → 中文名 + Tag 配色。pending 统一为「待执行」。 */
export const TASK_STATUS: Record<string, { text: string; severity: TagSeverity }> = {
  running: { text: '执行中', severity: 'info' },
  pending: { text: '待执行', severity: 'warn' },
  success: { text: '成功', severity: 'success' },
  failed: { text: '失败', severity: 'danger' },
  expired: { text: '已过期', severity: 'secondary' },
}

/** 执行方式 → 中文名 */
export const EXEC_TYPE_LABELS: Record<string, string> = {
  automatic: '自动',
  manual: '手动',
}

/** 执行方式 → Tag 配色 */
export const EXEC_TYPE_SEVERITY: Record<string, TagSeverity> = {
  manual: 'warn',
  automatic: 'secondary',
}

/**
 * 取任务类型中文名。未命中时回退原值,避免后端新增枚举时界面空白。
 * 注意:回退值是英文原始 key,一旦在界面上看到,说明本文件缺映射。
 */
export function taskTypeLabel(type: string): string {
  return TASK_TYPE_LABELS[type] || type
}

/** 取执行状态中文名(同上,未命中回退原值) */
export function taskStatusText(status: string): string {
  return TASK_STATUS[status]?.text || status
}

/** 取执行状态配色,未命中回退 secondary */
export function taskStatusSeverity(status: string): TagSeverity {
  return TASK_STATUS[status]?.severity ?? 'secondary'
}
