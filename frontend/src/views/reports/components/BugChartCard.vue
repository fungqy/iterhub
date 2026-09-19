<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import Card from 'primevue/card'
import { CHART, chartChrome } from './chartPalette'
import { useTheme } from '@/composables/useTheme'

interface ChartDataItem { name: string; value: number }

// 通用环形饼图卡片:顶部标题 + 图 body + legend 列表
// 取色方式二选一:colorMap 按名称键上色(orPRIORITY),colorList 按索引上色(TAG/DEVELOPER)
const props = withDefaults(defineProps<{
  title: string
  data: ChartDataItem[]
  colorMap?: Record<string, string>
  colorList?: string[]
  /** 中心大数字字号,级别分布用 40,其余用 50 */
  centerFontSize?: number
  /** legend 列表展示条数,默认全部;>0 时仅展示前 N 项(如人员分布仅展示前 5) */
  legendCount?: number
}>(), {
  colorMap: undefined,
  colorList: undefined,
  centerFontSize: 50,
  legendCount: 0,
})

// 外框色(tooltip / 描边 / 中心数字)随主题变化,须在 isDark 变化时重绘
const { isDark } = useTheme()

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// legend 列表
const legendItems = computed(() => {
  if (props.legendCount > 0) return props.data.slice(0, props.legendCount)
  return props.data
})

// legend 圆点与饼图分片取色:colorMap 按名称键,colorList 按索引
function resolveColor(name: string, index: number): string {
  if (props.colorMap) return props.colorMap[name] || CHART.neutral
  if (props.colorList && props.colorList.length > 0) {
    return props.colorList[index % props.colorList.length]
  }
  return CHART.neutral
}

// ── 环图几何:单一推导源 ────────────────────────────────────────────
// 需求:① 环的外沿顶边与卡片标题**顶边**齐平(标题已由 .ds-chart-card 取出文档流,
//        与图表容器同处 body 内容区顶部,见 components.scss);
//      ② 收窄卡片高度时环的直径不变。
// ECharts 饼图的 radius/center 百分比以 min(容器宽,高)/2 为基准 —— 容器宽扁(宽 > 高),
// 故基准恒为容器高的一半:圆心纵坐标取「环外半径」,环顶边便恰好落在容器顶边。
// 三个百分比全部由下面几个像素常量推出,只调 RING_BOX_H 即可整体收放,不会两处失配。
// ⚠ 前提是容器宽 ≥ 高;容器一旦窄于高,基准变为宽度,环会内缩、与标题顶边的对齐也失效。
// 该前提现由 RING_PLOT_W 固定保证(192 > 184),不再随卡片宽度浮动 —— 2026-09-15 前
// 容器宽 = 卡片内容宽,卡片被压窄到 184 以下就会静默走偏,现在这条路被堵死了。
const RING_OUTER_PX = 88    // 环外半径:沿用 220px 容器 + '80%' 的既有取值(0.8 × 220/2),直径 176px
const RING_INNER_PX = 60.5  // 环内半径:沿用既有 55/80 的厚度比
const RING_TEXT_GAP_PX = 22 // 中心数字盒顶边高于圆心 22px(沿用既有 '30%' × 220px 的取值)
// 容器高 = 环直径 + 8:那 8px 是 emphasis.scaleSize,hover 时环向外放大 8px,不预留会被画布裁掉。
const RING_BOX_H = RING_OUTER_PX * 2 + 8
// 容器宽:半宽要 ≥ 外半径88 + 描边外溢1.5 + emphasis.scaleSize 8 = 97.5。
//   · hover 只加**外半径**、圆心不动(见 echarts/lib/chart/pie/PieView.js 的
//     `r: layout.r + scaleSize`),即四向外扩 —— 容器差一点就把 hover 态裁平;
//   · 那个 1.5 是 itemStyle.borderWidth 3 的一半:描边以路径为中心向两侧画,
//     故环的**墨迹**半径是 89.5 而不是 88(实测墨迹直径 179 而非 176),漏算就差 2px。
// 原先容器宽 = 卡片内容宽(≈395),横向余量一百多像素,怎么写都裁不到;改成
// 「环 + 右侧图例」两列后必须自己保证,取 200(半宽 100,余 2.5px)。
// 另:旧前提「容器宽 ≥ 高」由此恒成立(200 > 184)—— 饼图 radius/center 的百分比
// 基准是 min(宽,高)/2,本容器恒为 184/2=92,与改动前同值。
const RING_PLOT_W = 200
const RING_RADIUS: [string, string] = [
  `${(RING_INNER_PX / (RING_BOX_H / 2) * 100).toFixed(2)}%`,
  `${(RING_OUTER_PX / (RING_BOX_H / 2) * 100).toFixed(2)}%`,
]
// 圆心纵坐标 = 环外半径 —— 环顶边因此落在容器顶边(＝标题顶边)。
const RING_CENTER_Y = `${(RING_OUTER_PX / RING_BOX_H * 100).toFixed(2)}%`
// graphic 的 top 是**文字盒顶边**而非视觉中心,故取圆心再上移 RING_TEXT_GAP_PX。
const RING_TEXT_TOP = `${((RING_OUTER_PX - RING_TEXT_GAP_PX) / RING_BOX_H * 100).toFixed(2)}%`

function render() {
  const el = chartRef.value
  if (!el || props.data.length === 0) {
    chartInstance?.clear()
    return
  }
  if (!chartInstance) {
    chartInstance = echarts.init(el)
  }
  const total = props.data.reduce((sum, item) => sum + item.value, 0)
  const chrome = chartChrome(isDark.value)
  chartInstance.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: chrome.tooltipBg,
      borderColor: 'transparent',
      padding: [10, 16],
      textStyle: { color: chrome.tooltipText, fontSize: 20 },
      formatter: '{b}: {c} ({d}%)',
    },
    legend: { show: false },
    series: [{
      type: 'pie',
      radius: RING_RADIUS,
      center: ['50%', RING_CENTER_Y],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 8, borderColor: chrome.pieBorder, borderWidth: 3 },
      label: { show: false },
      emphasis: { scale: true, scaleSize: 8, label: { show: false } },
      data: props.data.map((item, idx) => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: resolveColor(item.name, idx) },
      })),
    }],
    graphic: [{
      type: 'text',
      left: 'center',
      top: RING_TEXT_TOP,
      style: {
        text: `${total}`,
        fontSize: props.centerFontSize,
        fontWeight: 700,
        fill: chrome.valueText,
        textAlign: 'center',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", Arial, sans-serif',
      },
    }],
  })
  nextTick(() => {
    chartInstance?.resize()
  })
}

// 卡片整体由 v-if="data.length > 0" 控制,数据到达前 chartRef 并不存在 ——
// 故观察器需在每次数据更新、DOM 就绪后再尝试建立(ensureObserver 幂等)。
let resizeObserver: ResizeObserver | null = null
let resizeRaf = 0

function ensureObserver() {
  if (resizeObserver || !chartRef.value) return
  resizeObserver = new ResizeObserver(() => {
    cancelAnimationFrame(resizeRaf)
    resizeRaf = requestAnimationFrame(handleResize)
  })
  resizeObserver.observe(chartRef.value)
}

watch(() => [props.data, isDark.value], () => {
  nextTick(() => {
    render()
    ensureObserver()
  })
}, { deep: true })

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  render()
  ensureObserver()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(resizeRaf)
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <!-- ds-chart-card:标题取出文档流、与图表容器同处 body 顶部,
       使环图外沿顶边与标题顶边齐平(见 components.scss) -->
  <Card v-if="data.length > 0" class="ds-card ds-chart-card">
    <template #title>{{ title }}</template>
    <template #content>
      <!-- 「环 + 右侧竖排图例」两列(2026-09-15):图例由环**下方**移到环**右侧**竖排,
           消掉「环容器 184 + 图例行 28」的纵向叠加;图例条数再多也只占右列,
           不再把卡片顶高。布局与左移偏移的推导见 components.scss 的 .ds-ring-layout 段。 -->
      <div class="ds-ring-layout">
        <!-- 宽高都由 RING_* 常量绑定而非 Tailwind 字面量:它们与上面那几个 ECharts
             百分比同源,写成两处会悄悄失配(环被裁 or 旁边多出空白带);
             固定尺寸还让饼图 radius 的基准 min(宽,高)/2 不随卡片宽度浮动。 -->
        <div
          ref="chartRef"
          class="ds-ring-plot"
          :style="{ width: RING_PLOT_W + 'px', height: RING_BOX_H + 'px' }"
        ></div>
        <div class="ds-ring-legend">
          <div
            v-for="(item, idx) in legendItems"
            :key="item.name"
            class="flex items-center gap-2 ds-meta"
          >
            <span
              class="ds-ring-dot inline-block w-2 h-2 rounded-full"
              :style="{ background: resolveColor(item.name, idx) }"
            ></span>
            <span>{{ item.name }}: {{ item.value }}</span>
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>
