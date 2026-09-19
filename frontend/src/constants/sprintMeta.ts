// Sprint 状态的展示口径(文案 + 标签配色)。
//
// 后端 getSprints 返回的 state 是英文原值(如 closed / active / future),
// 此前 Reports 页的时间轴直接把它拼进文案,界面上出现「Sprint12(closed)」这类中英混排。
// 未命中时:文案回退原值、配色回退 secondary,以免后端新增状态时界面空白或报错。
//
// ⚠ TagSeverity 描述的是 PrimeVue Tag 组件的取值集,唯一来源在 taskMeta.ts,
// 这里用 type-only 复用而不是再声明一份联合类型 —— 复制会让两处随组件升级各自漂移。
import type { TagSeverity } from './taskMeta'

/** 「进行中」的状态原值。单独导出:时间轴要让当前迭代的点位脉冲,判定口径必须与下表同源。 */
export const SPRINT_STATE_ACTIVE = 'active'

/** Sprint 状态 → 中文名 + Tag 配色。进行中的用 warn(橙)、已关闭的用 success。
 *  ⚠ 进行中原本是 info(蓝),2026-09-15 按需求改为 warn(橙):
 *  时间轴上「当前迭代」的点位也同步改成橙色(见 components.scss 的 ds-timeline-live-pulse),
 *  这里只负责标签那一半 —— 两处必须同色系,改一处要连着改另一处。 */
export const SPRINT_STATE: Record<string, { text: string; severity: TagSeverity }> = {
  [SPRINT_STATE_ACTIVE]: { text: '进行中', severity: 'warn' },
  closed: { text: '已关闭', severity: 'success' },
  future: { text: '未开始', severity: 'secondary' },
}

export function sprintStateText(state: string | null | undefined): string {
  if (!state) return ''
  return SPRINT_STATE[state]?.text || state
}

export function sprintStateSeverity(state: string | null | undefined): TagSeverity {
  if (!state) return 'secondary'
  return SPRINT_STATE[state]?.severity ?? 'secondary'
}

/** 是否「进行中」。时间轴用它决定哪些点位要脉冲(见 components.scss 的 ds-timeline-live-pulse)。 */
export function sprintIsActive(state: string | null | undefined): boolean {
  return state === SPRINT_STATE_ACTIVE
}
