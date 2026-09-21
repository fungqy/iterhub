<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { reportsApi, type BurndownResponse } from '@/api/reports'
import Dialog from 'primevue/dialog'
import ProgressSpinner from 'primevue/progressspinner'
import { CHART, chartChrome, chartBarFill } from './chartPalette'
import { useTheme } from '@/composables/useTheme'
import { useSprintScope } from '@/composables/useSprintScope'

// 故事燃尽图弹窗:展示指定 Sprint 按天剩余故事数(实际线)与理想线
const props = defineProps<{
  visible: boolean
}>()

/** 当前下钻的 Sprint —— 由页面 provide、本弹窗自己取(见 useSprintScope) */
const sprintScope = useSprintScope()
const sprintId = computed(() => sprintScope?.value ?? null)

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const burndown = ref<BurndownResponse | null>(null)
const loadingBurndown = ref(false)
const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 外框色随主题变化;ECharts 不会自动跟随,故在 isDark 变化时重绘
const { isDark } = useTheme()

async function loadBurndown() {
  const sid = sprintId.value
  if (sid == null) return
  loadingBurndown.value = true
  try {
    burndown.value = await reportsApi.getBurndown(sid)
    nextTick(renderChart)
  } catch {
    burndown.value = null
  } finally {
    loadingBurndown.value = false
  }
}

// 组装燃尽图 ECharts 配置:实际剩余(面积线) + 理想剩余(虚线)
function renderChart() {
  const data = burndown.value
  const el = chartRef.value
  if (!el || !data || data.dates.length === 0) return
  if (!chartInstance) {
    chartInstance = echarts.init(el)
  }
  const chrome = chartChrome(isDark.value)
  const areaGradient = {
    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: chartBarFill(CHART.series1, 0.30) },
      { offset: 1, color: 'rgba(0,0,0,0)' },
    ],
  }
  chartInstance.setOption({
    animation: true,
    tooltip: {
      trigger: 'axis',
      backgroundColor: chrome.tooltipBg,
      borderColor: 'transparent',
      textStyle: { color: chrome.tooltipText },
    },
    legend: {
      show: true,
      top: 0,
      textStyle: { color: chrome.axisLabel, fontSize: 12 },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.dates,
      axisLabel: { fontSize: 12, color: chrome.axisLabel },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 12, color: chrome.axisLabel },
    },
    series: [
      {
        name: '剩余故事数',
        type: 'line',
        data: data.actual,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: CHART.series1, width: 3 },
        itemStyle: { color: CHART.series1 },
        areaStyle: { color: areaGradient },
      },
      {
        name: '理想剩余',
        type: 'line',
        data: data.ideal,
        symbol: 'none',
        lineStyle: { color: CHART.neutral, width: 2, type: 'dashed' },
        itemStyle: { color: CHART.neutral },
      },
    ],
  } as echarts.EChartsCoreOption)
  chartInstance.resize()
  ensureObserver()
}

let resizeObserver: ResizeObserver | null = null
let resizeRaf = 0

function handleResize() {
  chartInstance?.resize()
}

// 图表容器由 v-if 控制(数据到达后才出现),故每次渲染后都尝试建立观察器(幂等)。
function ensureObserver() {
  if (resizeObserver || !chartRef.value) return
  resizeObserver = new ResizeObserver(() => {
    cancelAnimationFrame(resizeRaf)
    resizeRaf = requestAnimationFrame(handleResize)
  })
  resizeObserver.observe(chartRef.value)
}

function teardown() {
  cancelAnimationFrame(resizeRaf)
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
  burndown.value = null
}

watch(() => props.visible, (val) => {
  if (val) {
    loadBurndown()
  } else {
    teardown()
  }
})

// 弹窗打开期间切换主题时,重绘以套用新的外框色
watch(isDark, () => {
  if (props.visible && burndown.value) renderChart()
})

onBeforeUnmount(teardown)
</script>

<template>
  <Dialog
    :visible="visible"
    header="故事燃尽图"
    class="ds-dialog-lg"
    modal
    @update:visible="emit('update:visible', $event)"
  >
    <div class="flex flex-col gap-4">
      <div v-if="loadingBurndown" class="flex flex-col items-center gap-2 py-8">
        <ProgressSpinner strokeWidth="4" />
      </div>
      <template v-else-if="burndown">
        <p class="ds-meta flex flex-wrap items-center gap-3">
          <span>{{ burndown.sprint_name }}</span>
          <span>{{ burndown.start_date }} ~ {{ burndown.end_date }}</span>
          <span>故事总数 {{ burndown.total }} 个</span>
        </p>
        <!-- ds-chart-static:燃尽图同样只读(无任何点击),把光标钉回箭头 ——
             否则 zrender 图元默认 cursor='pointer',悬停折线仍变手型(成因见 components.scss)。 -->
        <div v-if="burndown.dates.length > 0" ref="chartRef" class="ds-chart-static w-full h-[460px]"></div>
        <div v-else class="ds-empty">暂无燃尽数据</div>
      </template>
      <div v-else class="ds-empty">暂无燃尽数据</div>
    </div>
  </Dialog>
</template>
