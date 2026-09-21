// ECharts 绘制相关的工具函数、类型与色板常量
// 供 Reports.vue / MetricsTrendChart.vue / BugDetailDialog.vue 等组件共用
// 基础色取自 ./chartPalette(图表配色的唯一源,不在 tokens.scss 里)
import { CHART } from './chartPalette'

// ECharts 回调参数类型 - 把原 any 收紧到最小可断言集合
// (ECharts 真实回调的字段集合比这大,但使用方只关心以下子集)
export type EChartTooltipParam = {
  seriesName: string
  value: unknown
  color?: string
  dataIndex: number
  axisValue?: string | number
  name?: string
  data?: Record<string, unknown> | string | number
}

export type EChartAxisLabelParam = { value: number; max: number }

// 工具:把 ECharts value 安全地转成 number,失败返回 0
export function toNumber(v: unknown): number {
  if (typeof v === 'number') return v
  if (typeof v === 'string') {
    const n = Number(v)
    return Number.isFinite(n) ? n : 0
  }
  return 0
}

// 趋势图工具提示:过滤掉「趋势」系列,只展示实体数值系列
export function tooltipFormatter(params: EChartTooltipParam | EChartTooltipParam[]): string {
  const arr: EChartTooltipParam[] = Array.isArray(params) ? params : [params]
  const filtered = arr.filter((p) => !p.seriesName.includes('趋势'))
  let html = `<div style="font-size:13px">${arr[0]?.axisValue || ''}</div>`
  for (const p of filtered) {
    html += `<div style="display:flex;align-items:center;gap:4px;margin-top:4px">
      <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};flex-shrink:0"></span>
      <span>${p.seriesName}: ${p.value}</span>
    </div>`
  }
  return html
}

// RDM 故障详情页地址前缀,拼接故障编码后新开 tab 跳转。
// ⚠ 内网地址不写死:不同环境(开发/测试/生产)的 RDM 域名可能不同,
//   用 VITE_RDM_BROWSE_URL 覆盖;未配置时回落默认内网地址,保持既有行为不变。
export const RDM_BROWSE_URL =
  (import.meta.env.VITE_RDM_BROWSE_URL as string | undefined)
  || 'http://rdm.zvos.zoomlion.com/browse/'

// ── 色板常量 (由 BugDetail 场景抽到此共用) ──────────────────────
// 优先级:按名称键映射上色(数据语义色,不属于品牌 token,保留于此)
export const PRIORITY_COLORS: Record<string, string> = {
  '致命': '#DC2626',
  '严重': '#EA580C',
  '一般': '#F59E0B',
  '轻微': '#22C55E',
  '优化': '#6B7280',
}

// 原因标签:按索引取色
export const TAG_COLORS = [
  CHART.series1, '#8B5CF6', CHART.series3, '#F43F5E',
  CHART.series4, '#06B6D4', '#84CC16', CHART.series2,
  '#64748B', '#A855F7',
]

// 开发:按索引取色
export const DEVELOPER_COLORS = [
  CHART.series1, CHART.series3, CHART.series4, CHART.series2,
  '#8B5CF6', '#F43F5E', '#06B6D4', '#84CC16',
  '#64748B', '#A855F7', '#DC2626', '#EA580C',
  '#F59E0B', '#22C55E', '#3B82F6', '#E11D48',
]

// ── 通用趋势图系列定义 ──────────────────────────────────────────
// 一个数据类型可能同时有 bar + line 两个 series
// ⚠ 对象分支只保留 value:ECharts 的数据点本可挂任意自定义字段,此前这里挂过
//   sprintId(供「点柱子下钻」)。下钻已收口到「Sprint 概览」的指标卡
//   (见 Reports.vue),图表不再承载任何下钻信息,故把该字段从类型里一并去掉 ——
//   留着会让「数据点还能带业务字段」这个错觉继续扩散。
export type ChartSeriesData = number | { value: number }

export interface CoreChartSeries {
  name: string
  type: 'bar' | 'line'
  data: ChartSeriesData[]
  stack?: string
  barWidth?: string
  smooth?: boolean
  itemStyle?: Record<string, unknown>
  lineStyle?: Record<string, unknown>
  areaStyle?: Record<string, unknown>
  label?: Record<string, unknown>
}