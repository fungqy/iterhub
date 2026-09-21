// 故障「优先级」的展示口径 —— Tag 配色的**唯一来源**。
//
// 为什么单独立文件(2026-09-21):这份映射此前在 BugListDialog.vue 与
// BugInstanceDetailDialog.vue 里各写了一份(逐字相同的 9 个键)。再加第三处
// (重开故障列表)就等于把「同一口径写三遍」固化成惯例 —— 将来 RDM 加一档
// (如「建议」),改两处漏一处,那一档就会在某个列表里永远显示灰底 secondary,
// 看起来像「没级别」。收成一份后,漏改会直接编译不出来(Record<string, TagSeverity>
// 不限制键,但至少只有一处要改)。
//
// ⚠ 两个来源的**词表本来就不同**,必须都写全(直连 DB 核过):
//   · RDM  故障:致命 / 严重 / 一般 / 轻微 / 优化
//   · 文档故障:极高 / 高 / 中 / 低
//   两套并存是事实,不是笔误 —— 少写一套,那一套的行会整列落灰底。
//
// ⚠ 不放进 constants/taskMeta.ts:那里收的是**任务**的类型/状态/执行方式
//   (task_reminder、running、manual…),与故障优先级没有交集;混在一起会让
//   「新增任务状态要改哪个文件」变得含糊。
import type { TagSeverity } from './taskMeta'

/** 优先级 → Tag 配色。未命中一律回退 secondary(见 prioritySeverity)。 */
export const PRIORITY_SEVERITY: Record<string, TagSeverity> = {
  // RDM 故障
  致命: 'danger',
  严重: 'warn',
  一般: 'info',
  轻微: 'success',
  优化: 'secondary',
  // 文档故障
  极高: 'danger',
  高: 'warn',
  中: 'info',
  低: 'success',
}

/**
 * 取优先级配色。未命中回退 secondary。
 *
 * ⚠ 回退成灰色胶囊(**不是**不渲染):后端出现一个新档位时,界面上应该显示一个
 *   「这个词我不认识」的灰标签,而不是整格空白 —— 空白看起来像字段丢了。
 */
export function prioritySeverity(priority: string): TagSeverity {
  return PRIORITY_SEVERITY[priority] ?? 'secondary'
}
