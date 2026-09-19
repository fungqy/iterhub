// 时间格式化的唯一实现。
//
// 历史上存在三份输出不一致的实现:
//   - jobsConstants.ts  走的 toLocaleString('zh-CN') → 产出「2026/09/14 10:25:37」(斜杠)
//   - Dashboard.vue     手写 options 且不含年份    → 产出「09/14 10:25」
//   - DocBugImport.vue  字符串替换 + 切片          → 产出「2026-09-14 10:25:37」
// 同一份数据在两个页面显示成不同格式,用户会以为是不同的字段。统一收敛到这里,
// 分隔符一律用「-」。
//
// 新增时间展示需求时:**只改本文件**,不要在页面里再写 toLocaleString。

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * 完整时间:2026-09-14 10:25:37
 * 用于日志表格等需要精确定位的历史记录 —— 跨天/跨年时年份是必要信息。
 *
 * @param opts.seconds 是否显示秒,默认 true。时间轴等空间受限处可设为 false。
 */
export function formatDateTime(
  value: string | Date | null | undefined,
  opts: { seconds?: boolean } = {},
): string {
  const d = toDate(value)
  if (!d) return '—'
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const time = opts.seconds === false ? hm : `${hm}:${pad(d.getSeconds())}`
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
}

/**
 * 短时间:09-14 10:25
 * 仅用于「当日」语境(如工作台的今日任务),此时年份是冗余信息。
 * 不要用在可能跨越年份的历史列表里。
 */
export function formatDateTimeShort(value: string | Date | null | undefined): string {
  const d = toDate(value)
  if (!d) return '—'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 纯日期:2026-09-14 */
export function formatDate(value: string | Date | null | undefined): string {
  const d = toDate(value)
  if (!d) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 长日期:2026年9月14日星期一 —— 用于工作台顶部的「今天」提示 */
export function formatDateLong(value: string | Date | null | undefined = new Date()): string {
  const d = toDate(value)
  if (!d) return '—'
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  })
}

/**
 * 后端返回的「不带时区的本地时间串」转 Date。
 *
 * 背景:Safari 对 `new Date('2026-09-14 10:25:37')` 这类非 ISO 串会返回 Invalid Date,
 * 而 ISO 串(带 T)若不带时区又会按 UTC 解析,导致显示的钟点偏移。
 * 需要精确还原「后端记录的墙上时间」时,用本函数而不是 new Date()。
 */
export function parseLocalDateTime(value: string | null | undefined): Date | null {
  if (!value) return null
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) return toDate(value)
  const [, y, mo, d, h, mi, s] = m
  return new Date(
    Number(y),
    Number(mo) - 1,
    Number(d),
    Number(h),
    Number(mi),
    Number(s ?? '0'),
  )
}
