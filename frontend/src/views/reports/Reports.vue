<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { reportsApi, type AvgTimeDeveloperItem, type ProjectOption, type ReopenBugItem, type SprintMemberItem, type SprintMetricsItem, type SprintOption, type SprintReopenMemberItem, type UnplannedStoryItem, type WorktimeMismatchResponse } from '@/api/reports'
import { useNotify } from '@/utils/notify'
import { formatDate } from '@/utils/datetime'
import { sprintStateText, sprintStateSeverity, sprintIsActive } from '@/constants/sprintMeta'
import Select from 'primevue/select'
import ProgressSpinner from 'primevue/progressspinner'
import Timeline from 'primevue/timeline'
import Tag from 'primevue/tag'
import MetricsTrendChart from './components/MetricsTrendChart.vue'
import ReopenDistributionCard from './components/ReopenDistributionCard.vue'
import ReportReopenDialog from './components/ReportReopenDialog.vue'
import { type ReopenBucket } from './components/reopenBuckets'
import AvgTimeDevelopersDialog from './components/AvgTimeDevelopersDialog.vue'
import SprintSummaryDialog from './components/SprintSummaryDialog.vue'
import TeamMembersDialog from './components/TeamMembersDialog.vue'
import ReopenMembersDialog from './components/ReopenMembersDialog.vue'
import UnplannedStoriesDialog from './components/UnplannedStoriesDialog.vue'
import WorktimeMismatchDialog from './components/WorktimeMismatchDialog.vue'
import BugDetailDialog from './BugDetailDialog.vue'
import BurndownDialog from './components/BurndownDialog.vue'
import { toNumber, type CoreChartSeries, type EChartTooltipParam } from './components/charts'
import { CHART, chartChrome, chartBarFill, chartAreaGradient } from './components/chartPalette'
import { useTheme } from '@/composables/useTheme'
import { normalizeSprintId, provideSprintScope } from '@/composables/useSprintScope'

const notify = useNotify()
const notifyError = (detail: string) => notify('error', detail)

// ── 当前下钻的 Sprint:全页面唯一一份 ──────────────────────────────
// 下面每个 `openXxx(sprintId)` 都是「某人点了个东西 ⇒ 要展开某 Sprint 的下钻」,
// 它们此前各自持有一个 ref 再逐层透传;现在统一写进这一个,再由 provide 出去,
// 需要它的弹窗(时间轴概览 / 列表 / 统一「故障详情」)自己 inject。
//
// ⛔ 不要给这些下钻弹窗重新加 `sprint-id` prop —— 那等于又开了一条会与这里
// **分叉**的通道(两条通道同时存在时,谁对谁错要靠"记得传对"来决定)。
// 新增下钻弹窗的规矩是:自己的数据自己按 scope 取,不必任何人接线。
const activeSprintId = ref<number | null>(null)
provideSprintScope(() => activeSprintId.value)

/**
 * 记下本次下钻的 Sprint,并回传归一化后的值(供紧随其后的取数用)。
 *
 * 归一化收口在这里:各调用点传进来的既有 number、也有接口原样回吐的字符串
 * ("7506"),把 `Number()` 散落在每个调用点上正是上个版本的写法。
 */
function setActiveSprint(sprintId: unknown): number | null {
  activeSprintId.value = normalizeSprintId(sprintId)
  return activeSprintId.value
}

// 柱子上的数值标签色随主题变化。下面的 *SeriesOf 函数在 computed 求值期间读取
// chrome.value,因此主题切换会让 series 重新计算,进而触发图表重绘。
const { isDark } = useTheme()
const chrome = computed(() => chartChrome(isDark.value))

const projectMetrics = ref<SprintMetricsItem[]>([])
const loadingProjectMetrics = ref(false)

// 趋势图仅展示最近 7 个 sprint
const metricsLatest = computed(() => projectMetrics.value.slice(-7))

const selectedProjectForMetrics = ref<number | null>(null)
const loadingProjectsForMetrics = ref(false)

// 趋势图子组件引用,用于在弹窗全屏后主动重绘
// (「故障重开数」已改为分布表,不再有图表实例,故无对应 ref)
const storyChartRef = ref<InstanceType<typeof MetricsTrendChart> | null>(null)
const bugChartRef = ref<InstanceType<typeof MetricsTrendChart> | null>(null)
const timeChartRef = ref<InstanceType<typeof MetricsTrendChart> | null>(null)

const bugDialogVisible = ref(false)

function openBugDetailBySprint(sprintId: unknown) {
  setActiveSprint(sprintId)
  bugDialogVisible.value = true
}

// ── 故事数:点击柱子打开对应 Sprint 的故事燃尽图 ──
const burndownDialogVisible = ref(false)

function onStoryCellClick(data: unknown) {
  // 数据点携带 sprintId(常规/放大视图通用),据此打开对应 Sprint 的燃尽图
  const d = data as { sprintId: number; value: number } | null | undefined
  if (d && d.sprintId) {
    setActiveSprint(d.sprintId)
    burndownDialogVisible.value = true
  }
}

function handleChartsResize() {
  storyChartRef.value?.resize()
  bugChartRef.value?.resize()
  timeChartRef.value?.resize()
}

async function loadProjectMetrics(projectId: number) {
  loadingProjectMetrics.value = true
  try {
    // 一次拉取全量 sprint 指标,视图取最近 7 个
    const res = await reportsApi.getProjectMetrics(projectId, 0)
    projectMetrics.value = res
  } catch {
    notifyError('加载项目指标数据失败')
  } finally {
    loadingProjectMetrics.value = false
  }
}

// ── 各图数据与 series 装配 ─────────────────────────────────────
// 横轴统一使用 sprint_name(完整迭代名,如 botadp-Sprint-1),不用 short_sprint_name
// —— 后者只是「Sprint1」这类缩写,同一项目内会撞名(如 EMBODIED-Sprint1 与
// botadp-Sprint-1 都缩成 Sprint1),横轴上无法区分;且前端所有展示 Sprint 名称的
// 位置口径保持一致,避免同一迭代在不同界面显示成两个名字。
// series 装配函数按传入的 metrics 列表构建,常规(最近7个)与放大(全量)视图共用
//
// 注意:接口返回的 sprint_id 实际是**字符串**(如 "7551")。数据点携带它的目的是
// "点这个柱子 ⇒ 下钻到这个 Sprint",因此这里转成 number —— 后续所有下钻入口
// (setActiveSprint)对传入值都会再归一化一次,多转一次无害,但能让数据点的语义
// 自洽(不要指望下游替上游擦屁股)。
function storySeriesOf(metrics: SprintMetricsItem[]): CoreChartSeries[] {
  // 数据点携带 sprintId 供点击打开燃尽图
  const yData = metrics.map(s => ({ value: s.story_count, sprintId: Number(s.sprint_id) }))
  return [
    {
      name: '故事数',
      type: 'bar',
      data: yData,
      barWidth: '30%',
      itemStyle: { color: chartBarFill(CHART.series1), borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', color: chrome.value.axisLabel, fontSize: 16, formatter: (p: EChartTooltipParam) => { const v = toNumber(p.value); return v > 0 ? String(v) : '' } },
    },
    {
      name: '故事趋势',
      type: 'line',
      data: yData,
      smooth: true,
      lineStyle: { color: CHART.series1, width: 3 },
      itemStyle: { color: CHART.series1 },
    },
  ]
}

function bugSeriesOf(metrics: SprintMetricsItem[]): CoreChartSeries[] {
  const yData = metrics.map(s => ({ value: s.bug_count, sprintId: Number(s.sprint_id) }))
  return [
    {
      name: '故障趋势',
      type: 'line',
      data: yData,
      smooth: true,
      lineStyle: { color: CHART.series2, width: 3 },
      itemStyle: { color: CHART.series2 },
    },
    {
      name: '故障数',
      type: 'bar',
      data: yData,
      barWidth: '30%',
      itemStyle: { color: chartBarFill(CHART.series2), borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', color: chrome.value.axisLabel, fontSize: 16, formatter: (p: EChartTooltipParam) => { const v = toNumber(p.value); return v > 0 ? String(v) : '' } },
    },
  ]
}

function timeSeriesOf(metrics: SprintMetricsItem[]): CoreChartSeries[] {
  // 平均时长由秒换算为天,保留一位小数;数据点携带 sprintId 供点击跳转
  const devData = metrics.map(s => ({ value: s.avg_dev_seconds > 0 ? parseFloat((s.avg_dev_seconds / 86400).toFixed(1)) : 0, sprintId: Number(s.sprint_id) }))
  const testData = metrics.map(s => ({ value: s.avg_test_seconds > 0 ? parseFloat((s.avg_test_seconds / 86400).toFixed(1)) : 0, sprintId: Number(s.sprint_id) }))
  // 面积折线渐变:透明度随 y 递减,使时长趋势更直观(实现见 chartPalette.ts)
  return [
    {
      name: 'Dev',
      type: 'line',
      smooth: true,
      data: devData,
      lineStyle: { color: CHART.series4, width: 3 },
      itemStyle: { color: CHART.series4 },
      areaStyle: { color: chartAreaGradient(chartBarFill(CHART.series4, 0.30)) },
    },
    {
      name: 'Test',
      type: 'line',
      smooth: true,
      data: testData,
      lineStyle: { color: CHART.series2, width: 3 },
      itemStyle: { color: CHART.series2 },
      areaStyle: { color: chartAreaGradient(chartBarFill(CHART.series2, 0.30)) },
      label: { show: true, position: 'top', color: chrome.value.axisLabel, fontSize: 14, formatter: (p: EChartTooltipParam) => { const v = toNumber(devData[p.dataIndex]?.value) + toNumber(testData[p.dataIndex]?.value); return v > 0 ? parseFloat(v.toFixed(1)) + 'd' : '' } },
    },
  ]
}

const metricsXData = computed(() => metricsLatest.value.map(s => s.sprint_name))

const storySeries = computed(() => storySeriesOf(metricsLatest.value))
const bugSeries = computed(() => bugSeriesOf(metricsLatest.value))
const timeSeries = computed(() => timeSeriesOf(metricsLatest.value))

// ── 故障重开数:已由趋势图改为分布表 ─────────────────────────────
// 原来这里装配的是「柱 + 线」的 reopenSeries(字段 bug_reopen_count)。换掉的理由是那条
// 图只能表达「有几只故障被重开过」,重开 1 次与 5 次在图上都是 +1;表格才能把次数拆开。
// 数据仍是同一批 metricsLatest(与其余三张图同窗),只是字段换成 reopen_once/twice/many
// —— 后端就是由同一个分组查询派生 bug_reopen_count 的,故表格「合计」= 原来图上那个值。
// 下钻沿用 ReportReopenDialog:点行(或「合计」数字)打开该 Sprint 的重开明细。

// 图表单元格点击由子组件上抛(故事数→燃尽图、故障数→分布、时长→明细);
// 重开数已改表格,走 ReopenDistributionCard 的 select 事件 ——
// 事件带档位(点哪一格看哪一档,点「合计」/整行 = 'all'),父组件只负责把它转交给弹窗。
function onBugCellClick(data: unknown) {
  const d = data as { sprintId: number; value: number } | null | undefined
  if (d && d.value > 0) {
    openBugDetailBySprint(d.sprintId)
  }
}

const reopenDialogVisible = ref(false)
const reopenBugs = ref<ReopenBugItem[]>([])
const loadingReopenBugs = ref(false)
// 弹窗当前档位。卡片点「重开 1 次 / 2 次 / 多次」某一格带入对应档位,点「合计」或整行带入
// 'all'(全部)。状态放在这里而不是弹窗内部:弹窗内的分段控件要能改它,而同一档位在两次
// 点击之间「值未变」,自存状态会导致弹窗停留在上次手动切过的档位上(见弹窗内注释)。
const reopenBucket = ref<ReopenBucket>('all')

async function openReopenBySprint(sprintId: unknown, bucket: ReopenBucket = 'all') {
  const sid = setActiveSprint(sprintId)
  reopenBucket.value = bucket
  reopenDialogVisible.value = true
  if (sid == null) return
  loadingReopenBugs.value = true
  try {
    const res = await reportsApi.getReopenBugs(sid)
    reopenBugs.value = res
  } catch {
    notifyError('加载故障重开列表失败')
  } finally {
    loadingReopenBugs.value = false
  }
}

// ── 故障平均时长:点击柱子打开对应 Sprint 各开发人员的时长明细 ──
const avgTimeDialogVisible = ref(false)
const avgTimeDevelopers = ref<AvgTimeDeveloperItem[]>([])
const loadingAvgTimeDevelopers = ref(false)

function onTimeCellClick(data: unknown) {
  // 数据点携带 sprintId,据此打开对应 Sprint 的时长明细
  const d = data as { sprintId: number; value: number } | null | undefined
  if (d && d.sprintId) {
    openAvgTimeDevelopers(d.sprintId)
  }
}

async function openAvgTimeDevelopers(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  avgTimeDialogVisible.value = true
  if (sid == null) return
  loadingAvgTimeDevelopers.value = true
  try {
    const res = await reportsApi.getBugAvgTimeByDevelopers(sid)
    avgTimeDevelopers.value = res
  } catch {
    notifyError('加载开发人员故障时长失败')
  } finally {
    loadingAvgTimeDevelopers.value = false
  }
}

// ── 计划外故事:点击「计划外故事占比」卡打开该 Sprint 的计划外故事列表 ──
const unplannedDialogVisible = ref(false)
const unplannedStories = ref<UnplannedStoryItem[]>([])
const loadingUnplanned = ref(false)

async function openUnplannedStories(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  unplannedDialogVisible.value = true
  if (sid == null) return
  loadingUnplanned.value = true
  try {
    const res = await reportsApi.getUnplannedStories(sid)
    unplannedStories.value = res
  } catch {
    notifyError('加载计划外故事失败')
  } finally {
    loadingUnplanned.value = false
  }
}

// ── 工时不一致:点击概览「工时」卡(仅当投入 > 计划时该卡才可点)打开该 Sprint
//    里「投入 > 计划」的条目清单,用于回源头修数据 ──
// ⚠ 整份响应存一个 ref(而不是把 rows 与合计拆成几个 ref):它们是一次查询的快照,
//   「清单里的差额之和 == 卡片净差额」这条恒等式依赖它们同源;拆开只会多出几处可能漏赋值的地方。
const worktimeDialogVisible = ref(false)
const worktimeData = ref<WorktimeMismatchResponse | null>(null)
const loadingWorktime = ref(false)

async function openWorktimeMismatch(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  worktimeDialogVisible.value = true
  if (sid == null) return
  loadingWorktime.value = true
  try {
    worktimeData.value = await reportsApi.getWorktimeMismatch(sid)
  } catch {
    notifyError('加载工时不一致明细失败')
  } finally {
    loadingWorktime.value = false
  }
}

// ── 团队成员:点击概览「团队成员」卡打开该 Sprint 的成员工作分布(任务数 / 故障数) ──
const teamMembersDialogVisible = ref(false)
const teamMembers = ref<SprintMemberItem[]>([])
const loadingTeamMembers = ref(false)

async function openTeamMembers(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  teamMembersDialogVisible.value = true
  if (sid == null) return
  loadingTeamMembers.value = true
  try {
    const res = await reportsApi.getSprintMembers(sid)
    teamMembers.value = res
  } catch {
    notifyError('加载团队成员明细失败')
  } finally {
    loadingTeamMembers.value = false
  }
}

// ── 故障重开分布(按成员):点击概览「故障重开率」卡打开该 Sprint 各成员的重开分布 ──
const reopenMembersDialogVisible = ref(false)
const reopenMembers = ref<SprintReopenMemberItem[]>([])
const loadingReopenMembers = ref(false)

async function openReopenMembers(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  reopenMembersDialogVisible.value = true
  if (sid == null) return
  loadingReopenMembers.value = true
  try {
    const res = await reportsApi.getSprintReopenMembers(sid)
    reopenMembers.value = res
  } catch {
    notifyError('加载故障重开成员分布失败')
  } finally {
    loadingReopenMembers.value = false
  }
}

const projects = ref<ProjectOption[]>([])

async function loadProjectsForMetrics() {
  loadingProjectsForMetrics.value = true
  try {
    const res = await reportsApi.getProjects()
    projects.value = res
    if (res.length > 0) {
      selectedProjectForMetrics.value = res[0].id
    }
  } catch {
    notifyError('加载项目列表失败')
  } finally {
    loadingProjectsForMetrics.value = false
  }
}

watch(selectedProjectForMetrics, (newVal) => {
  if (newVal) {
    loadProjectMetrics(newVal)
    loadSprintTimeline(newVal)
  }
})

// ── Sprint 时间轴:点位为 activated_date,展示项目全部已激活 Sprint ──
const sprintTimeline = ref<SprintOption[]>([])
const loadingSprintTimeline = ref(false)

async function loadSprintTimeline(projectId: number) {
  loadingSprintTimeline.value = true
  try {
    sprintTimeline.value = await reportsApi.getSprints(projectId)
  } catch {
    sprintTimeline.value = []
  } finally {
    loadingSprintTimeline.value = false
  }
}

// 过滤 activated_date 为空的 Sprint,按激活时间升序
const timelinePoints = computed(() => {
  return sprintTimeline.value
    .filter(s => s.activated_date)
    .map(s => ({ ...s, ts: new Date((s.activated_date as string).replace(' ', 'T')).getTime() }))
    .filter(s => !Number.isNaN(s.ts))
    .sort((a, b) => a.ts - b.ts)
})

// 横向时间轴默认停在最右端:轴上按激活时间升序,最左边是最早的迭代、最右边才是最近/进行中的,
// 项目 Sprint 一多,默认停在开头就得每次手动拖到底才能看到当前状态。
// 滚动条已隐藏(见 .ds-timeline-scroll),横向滚动改由两端的两枚按钮驱动:
// 内容确实溢出时才出现,滚到哪一端就隐藏那一端的按钮。
const timelineScroller = ref<HTMLElement | null>(null)
// 「当前仍停在末端」。程序滚动到末端同样会触发 scroll 事件,所以这一个标志既覆盖
// 「刚加载完/刚滚到末端」,也覆盖「用户自己拖走了」—— 宽度变化时据此决定要不要跟着贴回末端。
const timelineAtEnd = ref(true)
const timelineAtStart = ref(true)
// 内容是否溢出可视窗 —— 决定两端要不要摆滚动按钮。
const timelineScrollable = ref(false)

// 三个状态都出自同一次测量,故合成一个函数:拆开写会出现在途状态
// (例如「按钮已入场,但 atEnd 还是按入场前的宽度算的」)。
function syncTimelineScrollState() {
  const el = timelineScroller.value
  if (!el) return
  const maxScrollLeft = el.scrollWidth - el.clientWidth
  timelineScrollable.value = maxScrollLeft > 1
  timelineAtStart.value = el.scrollLeft <= 1
  timelineAtEnd.value = el.scrollLeft >= maxScrollLeft - 1
}

function scrollTimelineToEnd() {
  const el = timelineScroller.value
  if (el) el.scrollLeft = el.scrollWidth - el.clientWidth
}

// 点一次滚一屏的 80%:留 20% 重叠当视觉锚点(与轮播翻页的惯例一致);
// 两端不必自己夹取 —— 目标值超出时浏览器会把 scrollLeft 收敛到 0 / maxScrollLeft。
// 系统开启「减少动态效果」时改走瞬移(与 .is-live 脉冲的降级口径一致)。
function scrollTimelineBy(dir: -1 | 1) {
  const el = timelineScroller.value
  if (!el) return
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: reduced ? 'auto' : 'smooth' })
}

// 「贴末端 + 复量状态」要来回两轮:按钮是否入场,由第一轮量出的溢出量决定;
// 而按钮一入场就会占掉可视窗宽度、把末端右移,所以第二轮必须再贴一次、再量一次。
// 收敛性(这是本文件唯一有循环风险的地方,值得写清):溢出量只会因「按钮占位」而变大,
// 不会反过来变小 —— 令 C = 内容所需宽度、W = 未摆按钮时的可视窗宽,则按钮入场后
// 视窗为 W−56,溢出量从 C−W 变成 C−W+56。于是「初量溢出 > 0」⇒ 之后恒 > 0;
// 「初量溢出 ≤ 0」⇒ 按钮不入场、量值不变。两种情形都是不动点,不存在抖动循环。
async function settleTimelineScroll(stickToEnd: boolean) {
  await nextTick()
  if (stickToEnd) scrollTimelineToEnd()
  syncTimelineScrollState()
  await nextTick()
  if (stickToEnd) scrollTimelineToEnd()
  syncTimelineScrollState()
}

watch(timelinePoints, async () => {
  // 容器是 v-if 渲染的,且 sprintTimeline 与 loadingSprintTimeline 在同一次微任务里赋值完,
  // 所以必须等这次更新渲染结束再量:flush:'post' 已保证在渲染之后,nextTick 只是把
  // 「读到真实 scrollWidth」这件事写得与 Vue 的调度顺序无关。
  await settleTimelineScroll(true)
}, { flush: 'post' })

// 容器宽度变化(窗口缩放、侧边栏折叠)会移动末端位置:仍停在末端就跟着贴回末端,
// 否则保持用户自己拖到的位置 —— 不抢用户的滚动条。
// 宽度变化同样会改变溢出量(可能恰好从「装不下」翻成「装得下」),故走同一套两轮结算。
// 监听挂在 watch(timelineScroller) 上而不是 onMounted:容器是 v-if 渲染的,
// 首次挂载时它还不存在,且切换项目会让它整体卸载重建。
let timelineResizeObserver: ResizeObserver | null = null

watch(timelineScroller, (el) => {
  timelineResizeObserver?.disconnect()
  timelineResizeObserver = null
  if (!el) return
  el.addEventListener('scroll', syncTimelineScrollState, { passive: true })
  timelineResizeObserver = new ResizeObserver(() => {
    void settleTimelineScroll(timelineAtEnd.value)
  })
  timelineResizeObserver.observe(el)
})

onUnmounted(() => timelineResizeObserver?.disconnect())

// ── 迭代概览:点击时间轴上的点位/名称,展示该 Sprint 的指标卡片 ──
const summaryDialogVisible = ref(false)

function openSprintSummary(sprintId: unknown) {
  // sprint_id 来自 SprintOption,接口返回的是字符串(如 "7551")—— 归一化收口在
  // setActiveSprint 里(见文件上方),此处与其余下钻入口写法一致。
  setActiveSprint(sprintId)
  summaryDialogVisible.value = true
}

onMounted(() => {
  loadProjectsForMetrics()
})
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>质量报表</h1>
      </div>
    </div>

    <div class="ds-card p-3 flex flex-col gap-2">
      <div class="flex flex-wrap items-end gap-4">
        <!-- 「选择项目」标签与下拉框同一行(用户要求):改前是 flex-col 竖排。
             三处尺寸声明各司其职,缺一条就会以另一种方式坏掉:
             · 标签 flex-none + whitespace-nowrap —— 标签**不参与**压缩、不换行,
               否则窄屏下它会被压成两行(比竖排更糟)。
             · 下拉框 w-[260px] —— 改前标签在上时,下拉框被 flex-col 的
               align-items:stretch 拉满到 260px(实测值)。这里必须用**确定宽度**,
               不能用 flex-basis:实测 flex-basis 只定起始尺寸,内容短则缩、长则涨,
               改选不同项目时宽度会在 98 ~ 354px 之间跳动(见 .workbuddy/verify-ui/
               cdp-drive48.mjs);确定宽度才会成为该元素的 max-content 贡献值,
               把「标签 + 间距 + 下拉框」这个组合的宽度定死在 56+8+260 = 324px。
             · 组合与下拉框都 min-w-0 —— 允许被压缩。组合的自动最小尺寸是
               min-content(会被上面那个 260 抬到 324),不显式归零的话窄屏**仍会
               顶出卡片**(实测改前 ≤420 视口出卡)。压缩顺序是先把下拉框收窄
               (标签 flex-none 收不动),这正是想要的。
             间距 gap-2(0.5rem)与全站 label/控件间距同源(ExecutionLogTable、
             ProjectList 等处同为 gap-2),此处只是把方向由纵向改为横向。 -->
        <div class="flex items-center gap-2 min-w-0">
          <label class="ds-meta flex-none whitespace-nowrap" for="report-project">选择项目</label>
          <Select
            v-model="selectedProjectForMetrics"
            inputId="report-project"
            class="w-[260px] min-w-0"
            :options="projects"
            optionLabel="project_name"
            optionValue="id"
            placeholder="请选择项目"
            :loading="loadingProjectsForMetrics"
          />
        </div>
        <ProgressSpinner v-if="loadingSprintTimeline" strokeWidth="4" class="w-8 h-8" />
      </div>

      <!-- 时间轴整块(标签 + 轴)套一层 .ds-panel:标题与内容有共同底色,看起来是一组,
           而不是漂在白卡面上(底色 = --ih-surface-sunken,亮暗各自翻转)。
           原先此处的 pt-2(8px)由面板自带的 padding-top(1rem)取代,间距不再叠加。 -->
      <div v-if="!loadingSprintTimeline && timelinePoints.length > 0" class="ds-panel">
        <!-- mb-3.5 = 0.875rem:base.scss 已在 reset 层把 <p> 的 UA 外边距归零,
             这里显式补回「标签 → 时间轴」原先由 UA 1em 提供的 14px 间距
             (详见 base.scss 顶部「最小 UA 重置」第 2 条)。 -->
        <p class="ds-meta mb-3.5">Sprint 时间轴 · 点击点位或名称查看迭代概览</p>
        <!-- 横向渲染项目全部已激活 Sprint,数量多时会溢出卡片。
             给一层横向滚动容器,并让内层宽度随点位数量增长(每点约 150px),
             而不是压缩点位或撑破卡片。滚动条由 .ds-timeline-scroll 隐藏 ——
             横向滚动改由左右两枚按钮驱动(见下方注释)。 -->
        <div class="ds-timeline-viewport">
          <!-- 只在内容溢出时出现(v-if,不是 v-show):不溢出时白占 ~56px 轨道宽度。
               一旦出现就**始终占位** —— 到端的一侧只切 visibility,而不是撤出布局:
               按钮整个撤出会让视窗变宽、把溢出量抹掉,连另一侧按钮也可能跟着消失,
               于是"还能往回滚"的那段内容就再也点不到了(功能性回退)。 -->
          <button
            v-if="timelineScrollable"
            type="button"
            class="ds-timeline-nav"
            :class="{ 'is-hidden': timelineAtStart }"
            aria-label="向左滚动时间轴"
            title="向左滚动"
            @click="scrollTimelineBy(-1)"
          >
            <i class="pi pi-chevron-left" aria-hidden="true"></i>
          </button>
          <div ref="timelineScroller" class="ds-timeline-scroll overflow-x-auto pb-2">
            <div :style="{ minWidth: `${Math.max(timelinePoints.length * 150, 100)}px` }">
              <Timeline
                :value="timelinePoints"
                layout="horizontal"
                class="ds-timeline"
              >
                <!-- 进行中的点位加 is-live → CSS 让它的外阴影持续扩散(脉冲)。
                     这里用 marker 插槽自己渲染一个同名类的元素,而不是走 PrimeVue 的 pt:
                     主题对 marker 的样式全是类选择器(已核对产物 CSS,无 [data-p] 作用域),
                     自己渲染等价;而主题已占用 marker 的 ::before(内点)与 ::after(内阴影),
                     脉冲只能做在元素自身的 box-shadow 上,不能借伪元素。 -->
                <template #marker="slotProps">
                  <div
                    class="p-timeline-event-marker"
                    :class="{ 'is-live': sprintIsActive(slotProps.item.state) }"
                    @click="openSprintSummary(slotProps.item.sprint_id)"
                  ></div>
                </template>
                <!-- 只到日期:点位是同一天的激活时刻,时分没有信息量,
                     且「YYYY-MM-DD HH:mm」在侧栏收窄后的单元格里会折行。
                     用 formatDate 而不是手写切片(见 utils/datetime.ts 文件头约定)。 -->
                <template #opposite="slotProps">
                  {{ formatDate(slotProps.item.activated_date) }}
                </template>
                <template #content="slotProps">
                  <!-- 状态从「与 Sprint 名同一段文本」改为名下方的独立 Tag:
                       两者是不同层级的信息,此前串在一个文本流里,长名换行后状态会被
                       挤到名中间,也看不出那是状态。用 span 显式包住名称 —— 列向 flex
                       里显式盒的宽度才有确定的 fit-content 口径,居中由 items-center 决定。
                       最外层是 button(迭代概览的点击目标):键盘可 Tab/Enter,
                       样式由 .ds-timeline-hit 清零默认外观,不改变内容盒宽度。 -->
                  <button
                    type="button"
                    class="ds-timeline-hit"
                    title="查看迭代概览"
                    @click="openSprintSummary(slotProps.item.sprint_id)"
                  >
                    <div class="flex flex-col items-center gap-1.5">
                      <span>{{ slotProps.item.sprint_name }}</span>
                      <!-- 状态也套胶囊(用户 2026-09-17):形状与字号取页头那颗同一套(.ds-pill),
                           颜色仍由 severity 给出 —— 与「Sprint 概览」页头保持同一口径。 -->
                      <Tag
                        v-if="slotProps.item.state"
                        class="ds-pill"
                        :value="sprintStateText(slotProps.item.state)"
                        :severity="sprintStateSeverity(slotProps.item.state)"
                      />
                    </div>
                  </button>
                </template>
              </Timeline>
            </div>
          </div>
          <button
            v-if="timelineScrollable"
            type="button"
            class="ds-timeline-nav"
            :class="{ 'is-hidden': timelineAtEnd }"
            aria-label="向右滚动时间轴"
            title="向右滚动"
            @click="scrollTimelineBy(1)"
          >
            <i class="pi pi-chevron-right" aria-hidden="true"></i>
          </button>
        </div>
      </div>
      <p v-else-if="!loadingSprintTimeline" class="ds-meta">暂无已激活的 Sprint</p>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <MetricsTrendChart
        ref="storyChartRef"
        title="故事数"
        hint=" | 点击查看燃尽图"
        :legend-items="[{ name: '故事数 (个)', color: CHART.series1 }]"
        :x-data="metricsXData"
        :series="storySeries"
        :loading="loadingProjectMetrics"
        clickable
        @cell-click="onStoryCellClick"
      />
      <MetricsTrendChart
        ref="bugChartRef"
        title="故障数"
        hint=" | 点击查看分布"
        :legend-items="[{ name: '故障数 (个)', color: CHART.series2 }]"
        :x-data="metricsXData"
        :series="bugSeries"
        :loading="loadingProjectMetrics"
        clickable
        @cell-click="onBugCellClick"
      />
      <!-- 故障重开数:表格而非趋势图。列的三个档位(1 次 / 2 次 / 多次)由后端按
           每只故障的重开次数分桶给出;点某一格的数字 → 弹窗只列该档的故障,
           点「合计」或整行 → 该 Sprint 的全部重开故障。 -->
      <ReopenDistributionCard
        :metrics="metricsLatest"
        :loading="loadingProjectMetrics"
        @select="openReopenBySprint"
      />
      <MetricsTrendChart
        ref="timeChartRef"
        title="故障平均解决时长"
        hint=" | 点击查看明细"
        :legend-items="[{ name: '开发时长 (天)', color: CHART.series4 }, { name: '测试时长 (天)', color: CHART.series2 }]"
        :x-data="metricsXData"
        :series="timeSeries"
        :loading="loadingProjectMetrics"
        y-axis-formatter="{value}d"
        clickable
        @cell-click="onTimeCellClick"
      />
    </div>

    <!-- Bug Detail Dialog -->
    <BugDetailDialog
      v-model:visible="bugDialogVisible"
      @charts-resize="handleChartsResize"
    />

    <!-- Story Burndown Dialog -->
    <BurndownDialog v-model:visible="burndownDialogVisible" />

    <!-- Reopen Bugs Dialog（档位由卡片上被点的格子带入,弹窗内亦可切换）-->
    <ReportReopenDialog
      v-model:visible="reopenDialogVisible"
      v-model:bucket="reopenBucket"
      :reopen-bugs="reopenBugs"
      :loading="loadingReopenBugs"
    />

    <!-- Avg Time By Developers Dialog -->
    <AvgTimeDevelopersDialog
      v-model:visible="avgTimeDialogVisible"
      :developers="avgTimeDevelopers"
      :loading="loadingAvgTimeDevelopers"
    />

    <!-- Sprint Summary Dialog（时间轴点位点击）-->
    <SprintSummaryDialog
      v-model:visible="summaryDialogVisible"
      @open-bug-detail="openBugDetailBySprint"
      @open-avg-time="openAvgTimeDevelopers"
      @open-unplanned-stories="openUnplannedStories"
      @open-team-members="openTeamMembers"
      @open-reopen-members="openReopenMembers"
      @open-worktime-mismatch="openWorktimeMismatch"
    />

    <!-- Unplanned Stories Dialog（计划外故事占比卡下钻）-->
    <UnplannedStoriesDialog
      v-model:visible="unplannedDialogVisible"
      :stories="unplannedStories"
      :loading="loadingUnplanned"
    />

    <!-- Team Members Dialog（团队成员卡下钻）-->
    <TeamMembersDialog
      v-model:visible="teamMembersDialogVisible"
      :members="teamMembers"
      :loading="loadingTeamMembers"
    />

    <!-- Reopen Members Dialog（故障重开率卡下钻）-->
    <ReopenMembersDialog
      v-model:visible="reopenMembersDialogVisible"
      :members="reopenMembers"
      :loading="loadingReopenMembers"
    />

    <!-- Worktime Mismatch Dialog（工时卡下钻：仅当投入 > 计划时可点开）-->
    <WorktimeMismatchDialog
      v-model:visible="worktimeDialogVisible"
      :data="worktimeData"
      :loading="loadingWorktime"
    />
  </div>
</template>
