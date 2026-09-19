// 图表配色的**唯一源**。
//
// ⚠ 为什么不在 tokens.scss 里定义图表色:ECharts 走 canvas 渲染,读不到 CSS 变量
//   (见 2026-09-12 计划 R3)。tokens.scss 里曾声明 6 个 --ih-chart-* 作"同源"承诺,
//   但没有任何 CSS 规则消费它们、且已与这里实际漂移,故已删除。
//   新增/修改图表配色**只改本文件**。
//
// 分两组:
//   - CHART  系列色(分类色)。是饱和中间调,亮暗两种主题下都可辨,不随主题变化。
//   - CHROME 外框色(轴标签 / tooltip / 描边 / 数值文字)。必须随主题变化 ——
//            亮色下的深色 tooltip 底在暗色主题里会糊成一片。

/** 系列色:分类用色,亮暗通用 */
export const CHART = {
  series1: '#6366F1',
  series2: '#F97316',
  series3: '#EC4899',
  series4: '#14B8A6',
  neutral: '#9CA3AF',
} as const

export type ChartChrome = {
  /** 坐标轴标签文字色 */
  axisLabel: string
  /** tooltip 背景 */
  tooltipBg: string
  /** tooltip 文字 */
  tooltipText: string
  /** 饼图分片描边 —— 取卡片底色,使分片之间形成"间隙"观感 */
  pieBorder: string
  /** 饼图中心大数字的颜色(需与卡片底色形成对比,故随主题变化) */
  valueText: string
}

/** 亮色外框色。pieBorder 保持原值 #F7F6F3 不改,以维持与改造前一致的渲染结果 */
const CHROME_LIGHT: ChartChrome = {
  axisLabel: '#666666',
  tooltipBg: '#1A1A2E',
  tooltipText: '#FFFFFF',
  pieBorder: '#F7F6F3',
  valueText: '#1e232c',
}

/** 暗色外框色。pieBorder 取暗色卡片底色 #1e2128(对应 --ih-surface) */
const CHROME_DARK: ChartChrome = {
  axisLabel: '#a0a6b0',
  tooltipBg: '#2b2f38',
  tooltipText: '#f5f7fa',
  pieBorder: '#1e2128',
  valueText: '#f5f7fa',
}

/** 按主题取外框色。组件须在 isDark 变化时重绘 —— ECharts 不会自动跟随主题。 */
export function chartChrome(isDark: boolean): ChartChrome {
  return isDark ? CHROME_DARK : CHROME_LIGHT
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 柱体填充:hex → 0.35 透明度 */
export const chartBarFill = (hex: string, alpha = 0.35): string => hexToRgba(hex, alpha)

/** 面积折线渐变 */
export const chartAreaGradient = (rgba: string) =>
  ({
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: rgba },
      { offset: 1, color: 'rgba(0,0,0,0)' },
    ],
  }) as const
