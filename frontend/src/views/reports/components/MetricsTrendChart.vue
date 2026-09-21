<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import Card from 'primevue/card'
import ProgressSpinner from 'primevue/progressspinner'
import { tooltipFormatter, type CoreChartSeries, type EChartAxisLabelParam } from './charts'
import { chartChrome } from './chartPalette'
import { useTheme } from '@/composables/useTheme'

// 通用「柱 + 线」趋势图卡片,不感知具体业务 —— 只负责把父组件给的数据画出来。
//
// ⚠ 2026-09-21:本组件原先自带下钻(clickable 时点柱子 emit cell-click:
//   故事数→燃尽图、故障数→故障分布、时长→明细),现已移除。下钻入口统一收口到
//   「Sprint 概览」弹窗里的同名指标卡(见 SprintSummaryDialog.vue),质量报表页上
//   这三张趋势图只呈现趋势、不再可点。随之删掉的还有 clickable prop、cell-click
//   事件,以及标题旁的 hint 小字(「| 点击查看…」—— 它唯一的用途就是提示可点)。
//   要恢复某张图的下钻,不是把 @cell-click 接回去就行:父组件还必须决定弹哪个窗,
//   那正是这次要去掉的重复入口。
const props = withDefaults(defineProps<{
  title: string
  legendItems: Array<{ name: string; color: string }>
  xData: string[]
  series: CoreChartSeries[]
  loading?: boolean
  /** 时间单位轴标签格式化串,如 '{value}h'(故障平均时长图用) */
  yAxisFormatter?: string
}>(), {
  loading: false,
  yAxisFormatter: undefined,
})

// 外框色(轴标签/tooltip)随主题变化,须在 isDark 变化时重绘
const { isDark } = useTheme()

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 组装 ECharts 配置,需与原渲染逻辑逐字段保持一致
function buildOption() {
  const chrome = chartChrome(isDark.value)
  // 动态效果:柱状自下而上且自左向右依次生长, 折线/面积平滑绘制。
  // 动画字段由 ECharts 运行时宽松读取,仅用于类型稳定,故 cast 回 CoreChartSeries[]。
  const animatedSeries: CoreChartSeries[] = props.series.map((s) =>
    Object.assign(
      {},
      s,
      {
        animation: true,
        animationDuration: s.type === 'bar' ? 900 : 1200,
        animationEasing: 'cubicOut',
      },
      s.type === 'bar' ? { animationDelay: (idx: number) => idx * 130 } : {},
    ) as CoreChartSeries,
  )
  return {
    animation: true,
    animationDurationUpdate: 500,
    animationEasingUpdate: 'cubicInOut',
    tooltip: {
      trigger: 'axis',
      backgroundColor: chrome.tooltipBg,
      borderColor: 'transparent',
      textStyle: { color: chrome.tooltipText },
      formatter: tooltipFormatter,
    },
    legend: { show: false },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
    xAxis: { type: 'category', data: props.xData, axisLabel: { fontSize: 12, color: chrome.axisLabel } },
    yAxis: props.yAxisFormatter
      ? { type: 'value', axisLabel: { fontSize: 12, color: chrome.axisLabel, formatter: props.yAxisFormatter } }
      : { type: 'value', minInterval: 1, max: (value: EChartAxisLabelParam) => value.max < 5 ? 5 : undefined, axisLabel: { fontSize: 12, color: chrome.axisLabel } },
    series: animatedSeries,
  }
}

function render() {
  const el = chartRef.value
  // 无数据时清空,避免残留上次渲染
  if (!el || props.xData.length === 0) {
    chartInstance?.clear()
    return
  }
  if (!chartInstance) {
    chartInstance = echarts.init(el)
  }
  // 组件系列为扁平 CoreChartSeries[],与 ECharts 强类型不完全对齐,放宽断言后交给 ECharts 运行时解析
  chartInstance.setOption(buildOption() as echarts.EChartsCoreOption)
  nextTick(() => {
    chartInstance?.resize()
  })
}

watch(
  () => [props.xData, props.series, props.yAxisFormatter, isDark.value],
  render,
  { deep: true },
)

function handleResize() {
  chartInstance?.resize()
}

// 侧栏折叠会改变容器宽度,但走的是 CSS transition,不触发 window resize ——
// 原先只监听 window,导致折叠侧栏后图表仍保留旧宽度、与卡片错位。
// 改为 ResizeObserver 直接观察图表容器,侧栏折叠与浏览器缩放都能覆盖。
// 用 rAF 合并抖动:transition 期间 observer 会连触发十余次,不合并会反复重排卡顿。
let resizeObserver: ResizeObserver | null = null
let resizeRaf = 0

onMounted(() => {
  render()
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => {
      cancelAnimationFrame(resizeRaf)
      resizeRaf = requestAnimationFrame(handleResize)
    })
    resizeObserver.observe(chartRef.value)
  }
})

onBeforeUnmount(() => {
  cancelAnimationFrame(resizeRaf)
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
})

// 供父组件在需要时主动触发重绘(ResizeObserver 已覆盖绝大多数场景)
defineExpose({ resize: handleResize })
</script>

<template>
  <Card class="ds-card ds-trend-card">
    <template #title>{{ title }}</template>
    <template #subtitle>
      <div class="flex flex-wrap items-center gap-3">
        <span
          v-for="item in legendItems"
          :key="item.name"
          class="flex items-center gap-2"
        >
          <span
            class="inline-block w-2 h-2 rounded-full"
            :style="{ background: item.color }"
          ></span>
          {{ item.name }}
        </span>
      </div>
    </template>
    <template #content>
      <!-- 加载态改为覆盖层,而不是与图表容器上下堆叠(原先 spinner 与定高空图表同时渲染)。
           图表容器必须常驻:若用 v-if/v-show 隐藏,echarts.init 会拿到 0 尺寸并告警。 -->
      <div class="relative">
        <div
          v-if="loading"
          class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-[var(--ih-surface)]"
        >
          <ProgressSpinner strokeWidth="4" />
          <span class="ds-meta">加载中...</span>
        </div>
        <!-- 画布高度:210px = 原 350px × 0.75 × 0.8。两次用户要求同源、口径都是**画布高**:
             先「4 张趋势图高度减 25%」(350 → 262.5),再「4 个图形卡片高度再压缩五分之一」
             (262.5 → 210)。不含标题与内边距 —— 那两项由全站 token 推导(见 components.scss
             的 .ds-card .p-card-body padding 与 .ds-card .p-card-title),不为单个页面破例。
             故卡盒实测 356.5 → 304(降 14.7%),而不是跟着也降五分之一。
             只改这一处 —— grid 的 top/bottom 是百分比,会跟着容器等比缩放。 -->
        <!-- ds-chart-static:本图已不可点(见 script 顶部说明),该类把光标钉回箭头。
             ⚠ 不挂它的话,鼠标移到柱子 / 折线 / 面积上仍是手型 —— 那是 zrender 图元的
                默认 cursor='pointer',不是我们写的样式(成因见 components.scss 该规则处)。
                日后若恢复下钻,记得把这类摘掉。 -->
        <div ref="chartRef" class="ds-chart-static w-full h-[210px]"></div>
        <div v-if="xData.length === 0 && !loading" class="flex flex-col items-center gap-2 py-4 ds-meta">暂无数据</div>
      </div>
    </template>
  </Card>
</template>
