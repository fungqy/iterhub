<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { reportsApi, type AvgTimeDeveloperItem, type ProjectOption, type ReopenBugItem, type SprintMemberItem, type SprintMetricsItem, type SprintOption, type UnplannedStoryItem, type WorktimeMismatchResponse } from '@/api/reports'
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
import AvgTimeDevelopersDialog from './components/AvgTimeDevelopersDialog.vue'
import SprintSummaryDialog from './components/SprintSummaryDialog.vue'
import TeamMembersDialog from './components/TeamMembersDialog.vue'
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

// ── 故事数:故事燃尽图 ──
// 入口唯一在「Sprint 概览」弹窗的「故事数」卡(见 SprintSummaryDialog 的 open-burndown)。
// 页面上的趋势图不再可点:图上一根柱子只说「这个迭代有几个故事」,而燃尽曲线与迭代
// 是一对一的 —— 从概览进入,「正在看哪个迭代」不存在歧义。
const burndownDialogVisible = ref(false)

function openBurndown(sprintId: unknown) {
  setActiveSprint(sprintId)
  burndownDialogVisible.value = true
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
// series 装配函数按传入的 metrics 列表构建
//
// 数据点统一用 { value } 形态(而不是裸数字),label / tooltip 回调按对象取值即可。
// ⚠ 这三个函数原先还在数据点上挂了 sprintId,供「点柱子 ⇒ 下钻到该 Sprint」用;
//   下钻已收口到「Sprint 概览」的指标卡(见文件上方「下钻:入口一律在卡 / 表上」),
//   数据点不再需要携带任何下钻信息 —— 图与 sprintId 自此无关,别再把两者绑回去。
function storySeriesOf(metrics: SprintMetricsItem[]): CoreChartSeries[] {
  const yData = metrics.map(s => ({ value: s.story_count }))
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
  const yData = metrics.map(s => ({ value: s.bug_count }))
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
  // 平均时长由秒换算为天,保留一位小数
  const devData = metrics.map(s => ({ value: s.avg_dev_seconds > 0 ? parseFloat((s.avg_dev_seconds / 86400).toFixed(1)) : 0 }))
  const testData = metrics.map(s => ({ value: s.avg_test_seconds > 0 ? parseFloat((s.avg_test_seconds / 86400).toFixed(1)) : 0 }))
  // 点位数值标签:两条曲线各标自己的值(天),颜色取各自系列色 ——
  // 开发线常紧贴测试线之上,若统一用轴标签的灰字,两个数字会分不清属于哪条线。
  // ⚠ 改前只有「测试时长」那条挂了标签,且 formatter 取的是 dev+test 的**合计**:
  //   于是「开发时长」整条线一个数字都没有,而「测试时长」线上的数字其实是总时长,
  //   既缺值又误导(总时长被挂在了两个分量的其中一个上)。合计不在本图展示 ——
  //   它由概览卡的「故障平均解决时长」与明细弹窗的「总时长」列负责,tooltip 里
  //   也分别给出 Dev / Test 两段,需要时相加即可。
  // 数值为 0(该 Sprint 没有时长样本)时不打标签,避免一排「0d」把趋势淹没。
  const dayLabel = (color: string) => ({
    show: true,
    position: 'top',
    color,
    fontSize: 14,
    formatter: (p: EChartTooltipParam) => { const v = toNumber(p.value); return v > 0 ? parseFloat(v.toFixed(1)) + 'd' : '' },
  })
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
      label: dayLabel(CHART.series4),
    },
    {
      name: 'Test',
      type: 'line',
      smooth: true,
      data: testData,
      lineStyle: { color: CHART.series2, width: 3 },
      itemStyle: { color: CHART.series2 },
      areaStyle: { color: chartAreaGradient(chartBarFill(CHART.series2, 0.30)) },
      label: dayLabel(CHART.series2),
    },
  ]
}

const metricsXData = computed(() => metricsLatest.value.map(s => s.sprint_name))

const storySeries = computed(() => storySeriesOf(metricsLatest.value))
const bugSeries = computed(() => bugSeriesOf(metricsLatest.value))
const timeSeries = computed(() => timeSeriesOf(metricsLatest.value))

// ── 下钻:入口一律在「卡 / 表」之外的那张概览弹窗上 ──────────────────
// 页面上原来的四处下钻(三张趋势图 + 「故障重开数」分布表)已全部改为纯展示;
// 对应的明细统一由 SprintSummaryDialog 的指标卡派发(见模板里那几行 @open-*):
//   故事数卡 → 故事燃尽图(BurndownDialog)              ← openBurndown
//   故障数卡 → 故障分布统计(BugDetailDialog)            ← openBugDetailBySprint
//   故障平均解决时长卡 → 时长明细(AvgTimeDevelopersDialog) ← openAvgTimeDevelopers
//   故障重开率卡 → 故障重开列表(ReportReopenDialog)      ← openReopenBugs
// 一句话:页面负责「趋势 / 分布」,弹窗负责「明细」,同一份明细不再有第二条入口。

// ── 故障重开数:已由趋势图改为分布表(纯展示)──────────────────────
// 原来这里装配的是「柱 + 线」的 reopenSeries(字段 bug_reopen_count)。换掉的理由是那条
// 图只能表达「有几只故障被重开过」,重开 1 次与 5 次在图上都是 +1;表格才能把次数拆开。
// 数据仍是同一批 metricsLatest(与其余三张图同窗),只是字段换成 reopen_once/twice/many
// —— 后端就是由同一个分组查询派生 bug_reopen_count 的,故表格「合计」= 原来图上那个值。
// ⚠ 2026-09-21:该表不再可点(原先点档位数字 / 整行会打开重开明细)。明细改由概览的
//   「故障重开率」卡打开(见下方 openReopenBugs)——「Sprint 概览」也是「正在看哪个迭代」
//   的唯一来源,从那里点进去不存在「点错迭代」的可能。

// ── 故障重开列表:概览「故障重开率」卡的下钻 ──
const reopenDialogVisible = ref(false)
const reopenBugs = ref<ReopenBugItem[]>([])
const loadingReopenBugs = ref(false)

async function openReopenBugs(sprintId: unknown) {
  const sid = setActiveSprint(sprintId)
  reopenDialogVisible.value = true
  if (sid == null) return
  loadingReopenBugs.value = true
  try {
    // 该 Sprint 的**全部**重开故障(每只一条,由后端按重开次数聚合)。
    // 分档筛选已随「重开数」卡的下钻一起移除:重开次数现在就是列表里的一列。
    reopenBugs.value = await reportsApi.getReopenBugs(sid)
  } catch {
    notifyError('加载故障重开列表失败')
  } finally {
    loadingReopenBugs.value = false
  }
}

// ── 故障平均时长:打开对应 Sprint 各开发人员的时长明细 ──
const avgTimeDialogVisible = ref(false)
const avgTimeDevelopers = ref<AvgTimeDeveloperItem[]>([])
const loadingAvgTimeDevelopers = ref(false)

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

// ⚠ 「故障重开分布(按成员)」的下钻已于 2026-09-21 移除:它原先挂在概览的「故障重开率」卡上,
//   该卡现在打开的是「故障重开列表」——列表里带「开发」与「重开次数」两列,按成员看分布
//   在那份列表里直接可读,不需要再来一张只按成员聚合的表。ReopenMembersDialog 组件与
//   它对应的 api 调用一并删除;后端 /reports/sprint-reopen-members 仍注册着(见 api/reports.ts
//   该方法的注释),要用回那张表时把组件与这一段接线恢复即可。

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
// 记录「当前挂了 scroll 监听的那个元素」,便于在元素更替/组件卸载时精确摘除。
let timelineScrollEl: HTMLElement | null = null

watch(timelineScroller, (el) => {
  timelineResizeObserver?.disconnect()
  timelineResizeObserver = null
  // ⚠ 只 disconnect observer 是不够的:scroll 监听挂在元素上,元素被 v-if 换掉后
  //   旧监听仍活着(且随每次切换累积),组件销毁后还会继续回调。
  if (timelineScrollEl) {
    timelineScrollEl.removeEventListener('scroll', syncTimelineScrollState)
    timelineScrollEl = null
  }
  if (!el) return
  timelineScrollEl = el
  el.addEventListener('scroll', syncTimelineScrollState, { passive: true })
  timelineResizeObserver = new ResizeObserver(() => {
    void settleTimelineScroll(timelineAtEnd.value)
  })
  timelineResizeObserver.observe(el)
})

onUnmounted(() => {
  timelineResizeObserver?.disconnect()
  if (timelineScrollEl) {
    timelineScrollEl.removeEventListener('scroll', syncTimelineScrollState)
    timelineScrollEl = null
  }
})

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

    <!-- 四张卡(三张趋势图 + 「故障重开数」分布表)**纯展示、不可点**(2026-09-21 用户要求)。
         原先点柱子 / 点数字分别打开燃尽图 / 故障分布 / 时长明细 / 重开明细,与「Sprint 概览」
         弹窗里的同名指标卡是两条重复入口;现在只留概览那一处(见下方 SprintSummaryDialog
         的 @open-*)。 -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <MetricsTrendChart
        ref="storyChartRef"
        title="故事数"
        :legend-items="[{ name: '故事数 (个)', color: CHART.series1 }]"
        :x-data="metricsXData"
        :series="storySeries"
        :loading="loadingProjectMetrics"
      />
      <MetricsTrendChart
        ref="bugChartRef"
        title="故障数"
        :legend-items="[{ name: '故障数 (个)', color: CHART.series2 }]"
        :x-data="metricsXData"
        :series="bugSeries"
        :loading="loadingProjectMetrics"
      />
      <!-- 故障重开数:表格而非趋势图。列的三个档位(1 次 / 2 次 / 多次)由后端按
           每只故障的重开次数分桶给出。⚠ 纯展示,不再可点(明细入口见概览的「故障重开率」卡)。 -->
      <ReopenDistributionCard
        :metrics="metricsLatest"
        :loading="loadingProjectMetrics"
      />
      <MetricsTrendChart
        ref="timeChartRef"
        title="故障平均解决时长"
        :legend-items="[{ name: '开发时长 (天)', color: CHART.series4 }, { name: '测试时长 (天)', color: CHART.series2 }]"
        :x-data="metricsXData"
        :series="timeSeries"
        :loading="loadingProjectMetrics"
        y-axis-formatter="{value}d"
      />
    </div>

    <!-- Bug Detail Dialog -->
    <BugDetailDialog
      v-model:visible="bugDialogVisible"
      @charts-resize="handleChartsResize"
    />

    <!-- Story Burndown Dialog -->
    <BurndownDialog v-model:visible="burndownDialogVisible" />

    <!-- Reopen Bugs Dialog（概览「故障重开率」卡下钻：该 Sprint 全部重开故障,行点击开抽屉）-->
    <ReportReopenDialog
      v-model:visible="reopenDialogVisible"
      :reopen-bugs="reopenBugs"
      :loading="loadingReopenBugs"
    />

    <!-- Avg Time By Developers Dialog -->
    <AvgTimeDevelopersDialog
      v-model:visible="avgTimeDialogVisible"
      :developers="avgTimeDevelopers"
      :loading="loadingAvgTimeDevelopers"
    />

    <!-- Sprint Summary Dialog(时间轴点位点击)—— 以下四种下钻的**唯一入口**:
         故事数 → 燃尽图、故障数 → 故障分布、故障平均解决时长 → 时长明细、
         故障重开率 → 故障重开列表。
         质量报表页上的对应趋势图 / 分布表已全部不再可点(见上方那几张卡的注释)。 -->
    <SprintSummaryDialog
      v-model:visible="summaryDialogVisible"
      @open-burndown="openBurndown"
      @open-bug-detail="openBugDetailBySprint"
      @open-avg-time="openAvgTimeDevelopers"
      @open-unplanned-stories="openUnplannedStories"
      @open-team-members="openTeamMembers"
      @open-reopen-bugs="openReopenBugs"
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

    <!-- Worktime Mismatch Dialog（工时卡下钻：仅当投入 > 计划时可点开）-->
    <WorktimeMismatchDialog
      v-model:visible="worktimeDialogVisible"
      :data="worktimeData"
      :loading="loadingWorktime"
    />
  </div>
</template>
