<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { reportsApi, type SprintSummary } from '@/api/reports'
import { formatDate } from '@/utils/datetime'
import { sprintStateText, sprintStateSeverity } from '@/constants/sprintMeta'
import { useSprintScope } from '@/composables/useSprintScope'
import Dialog from 'primevue/dialog'
import ProgressSpinner from 'primevue/progressspinner'
import Tag from 'primevue/tag'
import MetricHelp from './MetricHelp.vue'

// 每张指标卡的解释文案。键与下方模板里各 .ds-metric-label 的取值一一对应,
// 鼠标移到标签后的「?」图标上时由 MetricHelp 的 Tooltip 展示。文案尽量点出
// 口径与易误读处(哪些计入完成、分母是哪、null 表示什么),与组件内各卡的注释同义。
const METRIC_HELP: Record<string, string> = {
  member: '参与本次迭代的成员数量。\n\n点击可查看每个成员的 任务数 / 故障数。',
  range: '本次迭代的实际跨度天数(激活日 → 完成日,自然日含首尾)。\n\n副标题的「工作日」是同一实际区间内落在工作日历上的天数(不含周末与节假日);\n「计划 N 天(M 工作日)」则是计划区间(起止日期)的自然日跨度与其工作日数。',
  worktime: '计划工时与投入工时的对比。\n\n投入大于计划时，点击可查看计划与投入不一致的条目。',
  story: '本次迭代的故事数量。\n\n点击可查看该迭代的故事燃尽图。',
  doneRate: '已完成故事(含待验收)占故事总数的比例。',
  task: '本次迭代的子任务数量。',
  bug: '本次迭代的故障数量。',
  avgBug: '故障从开发到测试完成的平均工作日时长。',
  reopen: '被重开过的故障数与故障总数的比例。\n\n点击可查看该迭代被重开的故障列表。',
  unplanned: 'Sprint激活后新增的故事数量与故事总数的比例。',
  caseCount: '本次迭代的用例总数。',
  caseCoverage: '本次迭代中有用例关联的故事占比。\n\n用来衡量需求与验证之间是否建立了可追溯的闭环，是敏捷团队工程实践成熟度和交付质量保障能力的重要过程指标。',
  casePerStory: '用例数量与故事数量的比例,衡量每个故事的平均用例密度。',
}

// Sprint 迭代概览弹窗:在质量报表的 Sprint 时间轴上点击任一激活点位打开。
//
// 设计要点:
// 1. 指标按「形态」分配视觉载体(见 components.scss 的 .ds-metric 区块注释),
//    十余张同构的大数字卡会互相淹没,比例型指标也读不出含义。
// 2. 无数据 ≠ 0。计划/实际工时在后端为 null 时说明该 Sprint 尚未同步到工时字段,
//    此时渲染预留卡片(is-reserved),数值位置留「—」而不是 0,避免被当成真实值读走。
//    用例数/用例数每故事原为同样的预留态,现已接入 rdm_testcase 改为真实数据;
//    其中「用例数 / 故事」在故事数为 0(没有分母)时仍退回「—」。
//    用例覆盖率同源,故事数为 0 时整卡走预留态。
// 3. 卡片顺序:投入规模(人/时长/工时)→ 产出(故事/任务/用例)→ 质量(故障/重开/时长)。
//    (2026-09-21 按用户要求下线「故事平均完成时长」卡;它依赖的 avg_story_seconds /
//     story_sample_count 是**只服务于该卡**的字段,故后端 /sprint-summary 也一并删掉这
//     两个字段与那句 rdm_story_duration 查询 —— 留一个没人读的字段比删掉更容易误导。
//     rdm_story_duration 表与其 RDM 同步任务不受影响,后续要拿它做趋势图再按需取数。
//     同日一并下线「故障数 / 成员」(bug_per_member):该比值与同屏的「故障数」
//     「团队成员」两张卡完全共料,读者一眼就能相除,单独占一格的价值不足。)
// 4. 可下钻的卡一律把意图 emit 给父级,本组件不持有任何弹窗(同一个弹窗挂两份实例会
//    出现两套互不相干的加载状态)。2026-09-21 起本弹窗还是四种下钻的**唯一入口**:
//      故事数 → 燃尽图、故障数 → 故障分布统计、故障平均解决时长 → 时长明细、
//      故障重开率 → 故障重开列表。
//    质量报表页上那三张同名趋势图与「故障重开数」分布表都已改为纯展示(见 Reports.vue),
//    别再让页面上的图 / 表也能点开同一份明细。
const props = defineProps<{
  visible: boolean
}>()

/** 当前下钻的 Sprint —— 由页面 provide、本弹窗自己取(见 useSprintScope) */
const sprintScope = useSprintScope()
const sprintId = computed(() => sprintScope?.value ?? null)

const emit = defineEmits<{
  'update:visible': [value: boolean]
  /** 请求打开「故事燃尽图」弹窗(由父级复用既有 BurndownDialog) */
  'open-burndown': [sprintId: number]
  /** 请求打开「故障分布统计」弹窗(由父级复用既有 BugDetailDialog) */
  'open-bug-detail': [sprintId: number]
  /** 请求打开「故障平均解决时长(工作日口径)」弹窗(由父级复用既有 AvgTimeDevelopersDialog) */
  'open-avg-time': [sprintId: number]
  /** 请求打开「计划外故事列表」弹窗(由父级复用既有 UnplannedStoriesDialog) */
  'open-unplanned-stories': [sprintId: number]
  /** 请求打开「团队成员明细」弹窗(由父级复用既有 TeamMembersDialog) */
  'open-team-members': [sprintId: number]
  /** 请求打开「故障重开列表」弹窗(由父级复用既有 ReportReopenDialog) */
  'open-reopen-bugs': [sprintId: number]
  /** 请求打开「工时不一致明细」弹窗(由父级复用 WorktimeMismatchDialog) */
  'open-worktime-mismatch': [sprintId: number]
}>()

const summary = ref<SprintSummary | null>(null)
const loading = ref(false)

async function loadSummary() {
  const sid = sprintId.value
  if (sid == null) return
  loading.value = true
  summary.value = null
  try {
    const res = await reportsApi.getSprintSummary(sid)
    // 后端在 Sprint 不存在时返回 {} —— 统一收敛成 null,模板只需判一个空值。
    // 以 sprint_id 是否存在作为判据:它是后端必填字段,不会误判成「有数据但值为 0」。
    summary.value = res && res.sprint_id ? res : null
  } catch {
    summary.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (val) => {
    if (val) {
      loadSummary()
    } else {
      // 关闭即清空:下次打开时先看到 loading,不会闪上一次的旧数据
      summary.value = null
    }
  },
)

// 弹窗保持打开、下钻的 Sprint 被换掉(理论上不会发生,但切项目后时间轴会重建)时重新拉取。
// 改前这里 watch 的是 props.sprintId;现在 sprint 来自 provide 的 scope,
// 改 watch scope 的 computed —— 依赖源变了,但"换了 Sprint 要重拉"这条语义没变。
watch(
  sprintId,
  () => {
    if (props.visible) loadSummary()
  },
)

const sprintTitle = computed(
  () => summary.value?.sprint_name || '迭代概览',
)

// 计划区间 + 激活/完成时刻。激活时刻是时间轴点位的取值来源,放在这里便于与轴上的点对账。
const rangeText = computed(() => {
  const s = summary.value
  if (!s) return ''
  const parts: string[] = []
  if (s.start_date || s.end_date) {
    parts.push(`${formatDate(s.start_date)} ~ ${formatDate(s.end_date)}`)
  }
  if (s.activated_date) parts.push(`激活 ${formatDate(s.activated_date)}`)
  if (s.complete_date) parts.push(`完成 ${formatDate(s.complete_date)}`)
  return parts.join(' · ')
})

// 「迭代时长」卡的副标题:实际工作日 → 计划跨度(附计划工作日)。
// ⚠ 第一项必须与主数值**同区间**:主数值是「激活 → 完成」的实际自然日跨度,
//    所以这里的工作日数取 actual_workday_count。改前取的是 workday_count(计划区间),
//    于是拖期迭代会出现「实际 25 天 / 工作日 8 天」这种跨区间的混搭,两数无从比较。
//    计划口径的两个数(自然日 + 工作日)成对放在后半段,各自都有配对项。
const rangeSubText = computed(() => {
  const s = summary.value
  if (!s) return ''
  const parts = [`工作日 ${s.actual_workday_count ?? '—'} 天`]
  if (s.duration_days !== null) {
    const planWorkday = s.workday_count !== null ? `(${s.workday_count} 工作日)` : ''
    parts.push(`计划 ${s.duration_days} 天${planWorkday}`)
  }
  return parts.join(' · ')
})

// ── 数值格式化 ───────────────────────────────────────────────
/** 秒 → 天(保留一位小数)。工作日口径,与 /reports 其余接口一致。 */
function secondsToDays(seconds: number): string {
  return (seconds / 86400).toFixed(1)
}

/** 比率(0~1)→ 百分比文本;null 表示无样本,显示「—」 */
function rateToPercent(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`
}

/** 进度条宽度:比率 null 时为 0;超过 100% 的(如投入工时超计划)封顶在 100%,
 *  否则条会溢出容器。真实数值仍由旁边的百分比文本给出,不丢信息。 */
function rateToBarWidth(rate: number | null): string {
  if (rate === null) return '0%'
  return `${Math.min(Math.max(rate, 0), 1) * 100}%`
}

/** 数值文本:整数不带小数点(6 → "6"),非整数保留一位(1211588 → 1.5) */
function hoursText(hours: number | null): string {
  if (hours === null) return '—'
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1)
}

// ── 团队成员姓名 ──────────────────────────────────────────────
// 后端 members 数组已按「任务数 DESC、姓名 ASC」排序 —— 卡片要展示的就是「本迭代
// 做事最多的前几个人」,前端的 slice 就是「取排序后的前 3 个」。
// 上限 3 是因为姓名是变宽内容(2~4 个中文字):3 个姓名 + 「+N」在最窄的一档
// (lg 四列)仍是一行,再多就会换行把卡片撑高、挤压同排其他卡。
const MAX_MEMBER_NAMES = 3
const visibleMembers = computed(() => (summary.value?.members ?? []).slice(0, MAX_MEMBER_NAMES))
const hiddenMembers = computed(() => (summary.value?.members ?? []).slice(MAX_MEMBER_NAMES))
const hiddenMembersTitle = computed(() => hiddenMembers.value.join('、'))

// ── 派生指标 ─────────────────────────────────────────────────
/** 投入工时 / 计划工时。任一缺失或计划为 0 时返回 null(无意义,不显示条) */
const worktimeUtilRate = computed(() => {
  const s = summary.value
  if (!s || s.plan_worktime === null || s.actual_worktime === null || s.plan_worktime <= 0) {
    return null
  }
  return s.actual_worktime / s.plan_worktime
})

/** 计划/投入工时是否各自已同步(rdm_issue.plan/actual_worktime 回填)。
 *  合并卡里两半区独立判断:某一侧为 null 时该半区显示「—」,不影响另一侧。 */
const planWorktimeSynced = computed(() => !!summary.value && summary.value.plan_worktime !== null)
const actualWorktimeSynced = computed(() => !!summary.value && summary.value.actual_worktime !== null)
/** 两侧都未同步 → 整卡预留(虚线 + 待同步),与合并前「计划工时」的待同步态一致 */
const worktimeFullyReserved = computed(() => !planWorktimeSynced.value && !actualWorktimeSynced.value)

/**
 * 投入 > 计划 —— 只有这种时候「怎么超的」才是个真问题,卡片才可下钻。
 *
 * ⚠ 必须两侧都有值才判:计划为 null(未同步/未填)时无法比较大小,此时卡片保持不可点。
 *   注意这与「后端清单里会包含『计划未填但有投入』的条目」不冲突:那类条目只有在
 *   整迭代合计也超计划时才会被看到,而那时计划侧必然已有值。
 * ⚠ 用严格大于:相等(=100%)不算不一致,不该给一个点开只有空态的入口。
 */
const worktimeOverPlan = computed(() => {
  const s = summary.value
  return (
    !!s &&
    s.plan_worktime !== null &&
    s.actual_worktime !== null &&
    s.actual_worktime > s.plan_worktime
  )
})

/** 故障解决总时长(工作日秒)= 开发 + 测试 */
const bugTotalSeconds = computed(() => {
  const s = summary.value
  if (!s) return 0
  return s.avg_bug_dev_seconds + s.avg_bug_test_seconds
})

const bugDevShare = computed(() =>
  bugTotalSeconds.value > 0 ? summary.value!.avg_bug_dev_seconds / bugTotalSeconds.value : 0,
)

/** 「故障数」卡副标题的来源构成:RDM 故障 / 文档故障各多少,**为 0 的那类不列**(用户 2026-09-17)。
 *  两个数由后端同一处口径给出(rdm_issue 的 issue_type='故障' / rdm_doc_bug),之和即卡片上的
 *  bug_count —— 故 bug_count > 0 时这里必然至少有一段,不会是空串。 */
const bugSourceText = computed(() => {
  const s = summary.value
  if (!s) return ''
  const parts: string[] = []
  if (s.bug_rdm_count > 0) parts.push(`RDM ${s.bug_rdm_count}`)
  if (s.doc_bug_count > 0) parts.push(`文档 ${s.doc_bug_count}`)
  return parts.join(' · ')
})

/** 完成率环的 tone:100% 绿、≥60% 黄、其余红 —— 让「收口质量」一眼可辨 */
const doneRateTone = computed(() => {
  const rate = summary.value?.story_done_rate
  if (rate === null || rate === undefined) return ''
  if (rate >= 1) return 'tone-success'
  if (rate >= 0.6) return 'tone-warn'
  return 'tone-danger'
})

/** 用例覆盖率的分档:与完成率同规则(100% 绿、≥60% 黄、其余红)。
 *  覆盖率同样「越高越好」,复用同一套阈值可让两张卡的色义保持一致;
 *  无故事时 rate 为 null,整卡走预留态,不参与配色。 */
const caseCoverageTone = computed(() => {
  const rate = summary.value?.case_coverage_rate
  if (rate === null || rate === undefined) return ''
  if (rate >= 1) return 'tone-success'
  if (rate >= 0.6) return 'tone-warn'
  return 'tone-danger'
})

/** 故事数卡的副标题。完成率把「待验收」计为完成,这里必须点出该分量 ——
    否则「故事 8 / 已完成 8」会被读成全部通过验收。无待验收时保持原措辞。 */
const storyDoneSub = computed(() => {
  const done = summary.value?.story_done_count ?? 0
  const pending = summary.value?.story_pending_accept_count ?? 0
  return pending > 0 ? `已完成 ${done} 个（含待验收 ${pending}）` : `已完成 ${done} 个`
})

/** 进度环的 conic-gradient 断点。传字符串而非数字,避免模板里做算术。 */
function ringStyle(rate: number | null) {
  const pct = rate === null ? 0 : Math.round(Math.min(Math.max(rate, 0), 1) * 100)
  return { '--pct': `${pct}%` }
}

// ── 下钻 ─────────────────────────────────────────────────────
// 下面每个 emit 都把本弹窗**已确认拿到**的 sprint_id 一起递上去(取自拉回来的 summary,
// 而不是自己在 scope 里读一遍再递)。父级收到后会用同一个值覆盖下钻上下文
// (见 Reports.vue 的 setActiveSprint)—— 于是"页面上正在下钻哪个 Sprint"
// 始终有一个明确的写入者,而不是靠两边各读一次、碰巧一致。
/** 故事数卡 → 「故事燃尽图」弹窗(父级复用 BurndownDialog)。
 *  与 openBugDetail 同构:本组件不持有弹窗,只递意图上去;
 *  无故事(story_count 为 0)时不下钻 —— 那时卡片退回 div,本就不是可点控件,
 *  点开也只会看到「暂无燃尽数据」。
 *  ⚠ 判据必须与卡片能否渲染成 button 完全同源(都以 story_count > 0 为准)。 */
function openBurndown() {
  const s = summary.value
  if (s && s.story_count > 0) emit('open-burndown', s.sprint_id)
}

/** 故障数卡 → 「故障分布统计」弹窗。
 *  弹窗本身由父级复用既有的 BugDetailDialog ——
 *  若在本组件内再挂一个实例,同一个弹窗就会有两份互不相干的加载状态。
 *  无故障时不派发:该卡此时不是可点控件,弹窗也只会显示「暂无故障数据」。 */
function openBugDetail() {
  const s = summary.value
  if (s && s.bug_count > 0) emit('open-bug-detail', s.sprint_id)
}

/** 故障平均解决时长卡 → 「故障平均解决时长(工作日口径)」弹窗(父级复用 AvgTimeDevelopersDialog)。
 *  与 openBugDetail 同构:本组件不持有弹窗,只递意图上去;无样本(总时长为 0)时不下钻。 */
function openAvgTime() {
  const s = summary.value
  if (s && bugTotalSeconds.value > 0) emit('open-avg-time', s.sprint_id)
}

/** 计划外故事占比卡 → 「计划外故事列表」弹窗(父级复用 UnplannedStoriesDialog)。
 *  与 openBugDetail 同构:本组件不持有弹窗,只递意图上去;无计划外故事(count 为 0)时不下钻。 */
function openUnplannedStories() {
  const s = summary.value
  if (s && s.story_unplanned_count > 0) emit('open-unplanned-stories', s.sprint_id)
}

/** 团队成员卡 → 「团队成员明细」弹窗(父级复用 TeamMembersDialog),展示成员的
 *  任务数与故障数。与 openBugDetail 同构:本组件不持有弹窗,只递意图上去;
 *  无成员(该迭代无关联人员)时不下钻 —— 那时卡片退回 div,本就不是可点控件。 */
function openTeamMembers() {
  const s = summary.value
  if (s && s.member_count > 0) emit('open-team-members', s.sprint_id)
}

/** 故障重开率卡 → 「故障重开列表」弹窗(父级复用 ReportReopenDialog)。
 *  与 openBugDetail 同构:本组件不持有弹窗,只递意图上去;
 *  无重开故障(count 为 0)时不下钻 —— 那时卡片退回 div,本就不是可点控件,
 *  点开也只会看到「该迭代暂无重开故障」。
 *  (2026-09-21 前这里指向「故障重开分布(按成员)」,那份明细已无入口:
 *   重开列表本身带「开发」与「重开次数」两列,按成员的分布在其中即可读出来。) */
function openReopenBugs() {
  const s = summary.value
  if (s && s.bug_reopen_count > 0) emit('open-reopen-bugs', s.sprint_id)
}

/** 工时卡 → 「工时不一致明细」弹窗(父级复用 WorktimeMismatchDialog)。
 *  与 openBugDetail 同构:本组件不持有弹窗,只递意图上去。
 *  ⚠ 判据与卡片能否渲染成 button 完全同源(都以 worktimeOverPlan 为准):
 *    投入未超计划时卡片本就是 div,点了也不该发事件 —— 那会弹出一个必然空态的弹窗。 */
function openWorktimeMismatch() {
  const s = summary.value
  if (s && worktimeOverPlan.value) emit('open-worktime-mismatch', s.sprint_id)
}
</script>

<template>
  <Dialog
    :visible="visible"
    class="ds-dialog-lg"
    modal
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="flex flex-col gap-1">
        <!-- 状态与日期都做成小胶囊(用户 2026-09-17),形状同「团队成员」的姓名胶囊(.ds-metric-name):
             全圆、28px、0.75rem/600。⚠ 状态那颗只挂 .ds-pill(形状),**不挂 is-muted** ——
             颜色要留给 Tag 自己的 severity;日期是非状态信息,才用中性底那档。 -->
        <span class="flex items-center gap-2">
          <span>{{ sprintTitle }} 概览</span>
          <Tag
            v-if="summary?.state"
            class="ds-pill"
            :value="sprintStateText(summary.state)"
            :severity="sprintStateSeverity(summary.state)"
          />
          <span v-if="rangeText" class="ds-pill is-muted">{{ rangeText }}</span>
        </span>

      </div>
    </template>

    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <div v-else-if="!summary" class="ds-empty">暂无该迭代的概览数据</div>

    <div v-else class="flex flex-col gap-4">
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <!-- 团队成员:人数 + 姓名胶囊(最多 3 个,其余折叠成「+N」)。人员的「构成」
             比数字本身更有信息量,而姓名比「姓的首字」更能认出人(用户 2026-09-17)。
             这 3 个姓名是后端按「任务数 DESC、姓名 ASC」排好序的 —— 即「本迭代做事最多」
             的前三个人(用户 2026-09-18),同名同任务数时按姓名稳定排序。
             有人时整卡是可下钻控件(button),下钻到「团队成员明细」(成员 /
             任务数 / 故障数);无成员时退回 div —— 结构与「故障数」卡同构,
             用 button 而非给 div 挂 role,这样 Tab/Enter 天然可用。 -->
        <component
          :is="summary.member_count > 0 ? 'button' : 'div'"
          v-bind="summary.member_count > 0 ? { type: 'button' } : {}"
          class="ds-metric is-team"
          :class="summary.member_count > 0 ? 'is-clickable' : ''"
          @click="openTeamMembers"
        >
          <span class="ds-metric-label">团队成员<MetricHelp :help="METRIC_HELP.member" /></span>
          <span class="ds-metric-value">
            {{ summary.member_count }}<span class="ds-metric-unit">人</span>
          </span>
          <div v-if="visibleMembers.length > 0" class="ds-metric-names">
            <span
              v-for="m in visibleMembers"
              :key="m"
              class="ds-metric-name"
              :title="m"
            >{{ m }}</span>
            <span
              v-if="hiddenMembers.length > 0"
              class="ds-metric-name is-more"
              :title="hiddenMembersTitle"
            >+{{ hiddenMembers.length }}</span>
          </div>
          <span v-else class="ds-metric-sub">该迭代无关联人员</span>
        </component>

        <!-- 迭代时长:主数值取「实际跨度」(激活 → 完成,自然日含首尾)——计划区间是名义周期,
             实际常与之严重脱节(拖期收尾、跨迭代遗留),用计划口径会低估真实投入时长。
             未完结的迭代没有 complete_date,无从计算,主数值显示「—」;
             此时计划跨度退到副标题,信息不丢。
             区间文本仍保持计划起止:它是迭代的定义周期,数值上与副标题的「计划 X 天」必然相等,
             两处可互相对上号;若把区间也换成实际起止,进行中的迭代会缺一半日期。
             ⚠ 副标题的两半各有配对:前半段「工作日 N 天」与主数值同取实际区间
                (见 rangeSubText 的注释),后半段「计划 X 天(Y 工作日)」同取计划区间 ——
                跨区间的数字放在一行里没有可比性,别再把它们拆开重组。 -->
        <div class="ds-metric is-range">
          <span class="ds-metric-label">迭代时长<MetricHelp :help="METRIC_HELP.range" /></span>
          <span class="ds-metric-value">
            {{ summary.actual_days ?? '—'
            }}<span v-if="summary.actual_days !== null" class="ds-metric-unit">天</span>
          </span>
          <span class="ds-metric-sub">{{ rangeSubText }}</span>
        </div>

        <!-- 工时:计划 / 投入 左右分隔(合并原「计划工时」「投入工时」两张卡)。
             两半区独立判据:某一侧为 null 时该半区显示「—」,不影响另一侧;
             利用率进度条沿用原「投入工时」的「投入 / 计划」派生信息。
             两侧都未同步(计划、投入均为 null)时整卡预留,与合并前「计划工时」的待同步态一致。
             ⚠ **投入 > 计划时整卡可下钻**:合计只说「超了」,要动数据得知道超在哪些条目上 ——
                点开后是「工时不一致明细」(父级持有该弹窗,本组件只递意图,与 openTeamMembers
                同构)。未超出时退回 div:那会儿没有「怎么超的」这个问题可问,不该留一个
                点开只有空态的假可点(判定与 openWorktimeMismatch 完全同源)。 -->
        <component
          :is="worktimeOverPlan ? 'button' : 'div'"
          v-bind="worktimeOverPlan ? { type: 'button' } : {}"
          class="ds-metric"
          :class="[
            worktimeFullyReserved ? 'is-reserved tone-info' : 'tone-info',
            worktimeOverPlan ? 'is-clickable' : '',
          ]"
          @click="openWorktimeMismatch"
        >
          <span class="ds-metric-label">工时<MetricHelp :help="METRIC_HELP.worktime" /></span>
          <div v-if="!worktimeFullyReserved" class="ds-metric-dual">
            <div class="ds-metric-half">
              <span class="ds-metric-half-label">计划</span>
              <span class="ds-metric-value">
                {{ hoursText(summary.plan_worktime)
                }}<span v-if="summary.plan_worktime !== null" class="ds-metric-unit">小时</span>
              </span>
            </div>
            <div class="ds-metric-divider"></div>
            <div class="ds-metric-half">
              <span class="ds-metric-half-label">投入</span>
              <span class="ds-metric-value">
                {{ hoursText(summary.actual_worktime)
                }}<span v-if="summary.actual_worktime !== null" class="ds-metric-unit">小时</span>
              </span>
            </div>
          </div>
          <template v-if="worktimeUtilRate !== null">
            <div class="ds-metric-bar">
              <span :style="{ width: rateToBarWidth(worktimeUtilRate) }"></span>
            </div>
            <span class="ds-metric-sub">投入 / 计划 {{ rateToPercent(worktimeUtilRate) }}</span>
          </template>
          <span v-else-if="worktimeFullyReserved" class="ds-metric-badge">待同步</span>
        </component>

        <!-- 故事数:全弹窗唯一的强调卡(渐变底),同时是「故事燃尽图」的下钻入口。
             有故事(story_count > 0)时才渲染成 button;为 0 时退回 div —— 没有可烧的
             曲线,留个可点却空转的控件只会误导(判据与 openBurndown 同源)。
             ⚠ 它是弹窗里唯一一颗 is-hero,而 .is-clickable 的悬停样式会把渐变底换成
                浅底、让反白字消失 —— 该组合由 components.scss 的
                `.ds-metric.is-hero.is-clickable:hover` 单独接管,别删那条规则。 -->
        <component
          :is="summary.story_count > 0 ? 'button' : 'div'"
          v-bind="summary.story_count > 0 ? { type: 'button' } : {}"
          class="ds-metric is-hero"
          :class="summary.story_count > 0 ? 'is-clickable' : ''"
          @click="openBurndown"
        >
          <span class="ds-metric-label">故事数<MetricHelp :help="METRIC_HELP.story" /></span>
          <span class="ds-metric-value">
            {{ summary.story_count }}<span class="ds-metric-unit">个</span>
          </span>
          <span class="ds-metric-sub">
            {{ storyDoneSub }}<template v-if="summary.story_count > 0"> · 点击查看燃尽图</template>
          </span>
        </component>

        <!-- 故事完成率:进度环 -->
        <div class="ds-metric is-ring" :class="doneRateTone">
          <span class="ds-metric-label">故事完成率<MetricHelp :help="METRIC_HELP.doneRate" /></span>
          <div class="ds-metric-ring" :style="ringStyle(summary.story_done_rate)">
            <span>{{ rateToPercent(summary.story_done_rate) }}</span>
          </div>
        </div>

        <!-- 任务数:口径与「任务到期提醒」一致(issue_type = 子任务) -->
        <div class="ds-metric is-plain tone-info">
          <span class="ds-metric-label">任务数<MetricHelp :help="METRIC_HELP.task" /></span>
          <span class="ds-metric-value">
            {{ summary.task_count }}<span class="ds-metric-unit">个</span>
          </span>
          <span class="ds-metric-sub">按子任务口径统计</span>
        </div>

        <!-- 故障数:有故障才用告警色,为 0 时保持中性(与工作台统计卡同一原则)。
             有故障时整卡是可下钻控件 —— 用 button 而非给 div 挂 role,
             这样 Tab/Enter 天然可用;对应的 UA 外观清零见 .ds-metric.is-clickable。
             为 0 时退回 div:没有分布可看,留个可点但空转的控件只会误导。
             副标题给出**来源构成**(RDM 故障 / 文档故障,为 0 的那类不列,见 bugSourceText),
             「· 点击查看分布」的口径与其余可下钻卡一致(如「故障重开率」的「· 点击查看成员分布」)。 -->
        <component
          :is="summary.bug_count > 0 ? 'button' : 'div'"
          v-bind="summary.bug_count > 0 ? { type: 'button' } : {}"
          class="ds-metric"
          :class="summary.bug_count > 0 ? 'is-plain tone-danger is-clickable' : 'is-plain'"
          @click="openBugDetail"
        >
          <span class="ds-metric-label">故障数<MetricHelp :help="METRIC_HELP.bug" /></span>
          <span class="ds-metric-value">
            {{ summary.bug_count }}<span class="ds-metric-unit">个</span>
          </span>
          <span class="ds-metric-sub">
            <template v-if="summary.bug_count > 0">{{ bugSourceText }} · 点击查看分布</template>
          </span>
        </component>

        <!-- 故障平均解决时长:开发 + 测试两段构成。有样本时整卡是可下钻控件(button),
             下钻到「故障平均解决时长(工作日口径)」明细;无样本(总时长为 0)退回 div,
             避免留下一个可点却空转的控件。结构与「故障数」卡同构。 -->
        <component
          :is="bugTotalSeconds > 0 ? 'button' : 'div'"
          v-bind="bugTotalSeconds > 0 ? { type: 'button' } : {}"
          class="ds-metric"
          :class="bugTotalSeconds > 0 ? 'is-split is-clickable' : 'is-split'"
          @click="openAvgTime"
        >
          <span class="ds-metric-label">故障平均解决时长<MetricHelp :help="METRIC_HELP.avgBug" /></span>
          <span class="ds-metric-value">
            {{ bugTotalSeconds > 0 ? secondsToDays(bugTotalSeconds) : '—'
            }}<span v-if="bugTotalSeconds > 0" class="ds-metric-unit">天</span>
          </span>
          <template v-if="bugTotalSeconds > 0">
            <div class="ds-metric-split">
              <i
                :style="{ width: `${bugDevShare * 100}%`, background: 'var(--ih-accent)' }"
              ></i>
              <i
                :style="{
                  width: `${(1 - bugDevShare) * 100}%`,
                  background: 'var(--ih-status-warn)',
                }"
              ></i>
            </div>
            <div class="ds-metric-legend">
              <span><i :style="{ background: 'var(--ih-accent)' }"></i>开发 {{ secondsToDays(summary.avg_bug_dev_seconds) }} 天</span>
              <span><i :style="{ background: 'var(--ih-status-warn)' }"></i>测试 {{ secondsToDays(summary.avg_bug_test_seconds) }} 天</span>
            </div>
          </template>
          <span v-else class="ds-metric-badge">无故障时长样本</span>
        </component>

        <!-- 故障重开率:有重开故障(count>0)时整卡是可下钻控件(button),
             下钻到「故障重开列表」(该迭代重开过的故障,带重开次数);无重开故障(count=0)
             或该卡为预留态时退回 div,避免留下一个可点却空转的控件。
             结构与「计划外故事占比」卡同构。 -->
        <component
          :is="summary.bug_reopen_count > 0 ? 'button' : 'div'"
          v-bind="summary.bug_reopen_count > 0 ? { type: 'button' } : {}"
          class="ds-metric"
          :class="summary.bug_reopen_rate === null ? 'is-reserved' : (summary.bug_reopen_count > 0 ? 'is-bar tone-danger is-clickable' : 'is-bar tone-danger')"
          @click="openReopenBugs"
        >
          <span class="ds-metric-label">故障重开率<MetricHelp :help="METRIC_HELP.reopen" /></span>
          <span class="ds-metric-value">{{ rateToPercent(summary.bug_reopen_rate) }}</span>
          <template v-if="summary.bug_reopen_rate !== null">
            <div class="ds-metric-bar">
              <span :style="{ width: rateToBarWidth(summary.bug_reopen_rate) }"></span>
            </div>
            <span class="ds-metric-sub">
              重开 {{ summary.bug_reopen_count }} / 故障 {{ summary.bug_count }}<template v-if="summary.bug_reopen_count > 0"> · 点击查看重开故障列表</template>
            </span>
          </template>
          <span v-else class="ds-metric-badge">该迭代无故障</span>
        </component>

        <!-- 计划外故事占比:衡量需求插入程度。有计划外故事(count>0)时整卡是可下钻控件(button),
             下钻到「计划外故事列表」;无计划外故事(count=0)或该卡为预留态时退回 div,避免留下
             一个可点却空转的控件。结构与「故障数」卡同构。 -->
        <component
          :is="summary.story_unplanned_count > 0 ? 'button' : 'div'"
          v-bind="summary.story_unplanned_count > 0 ? { type: 'button' } : {}"
          class="ds-metric"
          :class="summary.story_unplanned_rate === null ? 'is-reserved' : (summary.story_unplanned_count > 0 ? 'is-bar tone-warn is-clickable' : 'is-bar tone-warn')"
          @click="openUnplannedStories"
        >
          <span class="ds-metric-label">计划外故事占比<MetricHelp :help="METRIC_HELP.unplanned" /></span>
          <span class="ds-metric-value">{{ rateToPercent(summary.story_unplanned_rate) }}</span>
          <template v-if="summary.story_unplanned_rate !== null">
            <div class="ds-metric-bar">
              <span :style="{ width: rateToBarWidth(summary.story_unplanned_rate) }"></span>
            </div>
            <span class="ds-metric-sub">
              计划外 {{ summary.story_unplanned_count }} / 故事 {{ summary.story_count }}<template v-if="summary.story_unplanned_count > 0"> · 点击查看列表</template>
            </span>
          </template>
          <span v-else class="ds-metric-badge">该迭代无故事</span>
        </component>

        <!-- 用例数:归属口径 = 用例引用的故事 ∩ 本 Sprint 故事(见后端 docstring)。
             与「任务数」同为计数卡,故形态沿用 is-plain + 口径副标题。 -->
        <div class="ds-metric is-plain tone-info">
          <span class="ds-metric-label">用例数<MetricHelp :help="METRIC_HELP.caseCount" /></span>
          <span class="ds-metric-value">
            {{ summary.case_count }}<span class="ds-metric-unit">条</span>
          </span>
          <span class="ds-metric-sub">按用例关联的故事归属</span>
        </div>

        <!-- 用例覆盖率:本 Sprint 内「至少被一个用例关联过」的故事占比,与「用例数」
             同源(rdm_testcase.story_key 就是被用例引用到的故事 key)。
             载体选进度条卡而非环图:除比率外还要同时交代已覆盖/未覆盖两个故事数,
             环内只放得下一个百分比。分档沿用故事完成率的阈值,低覆盖一眼可辨。
             无故事时 rate 为 null → 整卡预留(与「计划外故事占比」同规则)。 -->
        <div
          class="ds-metric"
          :class="summary.case_coverage_rate === null
            ? 'is-reserved'
            : ['is-bar', caseCoverageTone]"
        >
          <span class="ds-metric-label">用例覆盖率<MetricHelp :help="METRIC_HELP.caseCoverage" /></span>
          <span class="ds-metric-value">{{ rateToPercent(summary.case_coverage_rate) }}</span>
          <template v-if="summary.case_coverage_rate !== null">
            <div class="ds-metric-bar">
              <span :style="{ width: rateToBarWidth(summary.case_coverage_rate) }"></span>
            </div>
            <span class="ds-metric-sub">
              已覆盖 {{ summary.case_covered_story_count }} / 故事 {{ summary.story_count }}<template v-if="summary.case_uncovered_story_count > 0"> · 未覆盖 {{ summary.case_uncovered_story_count }}</template>
            </span>
          </template>
          <span v-else class="ds-metric-badge">该迭代无故事</span>
        </div>

        <!-- 用例数/故事:分母做成胶囊,避免把比值读成绝对值(本弹窗现存的唯一 is-ratio 卡;
             原先同构的「故障数 / 成员」已于 2026-09-21 下线)。
             故事数为 0 时没有分母,值为「—」(与其余比率卡同规则)。 -->
        <div class="ds-metric is-ratio">
          <span class="ds-metric-label">用例数 / 故事<MetricHelp :help="METRIC_HELP.casePerStory" /></span>
          <span class="ds-metric-value">
            {{ summary.case_per_story === null ? '—' : summary.case_per_story }}
          </span>
          <span class="ds-metric-chip">
            {{ summary.case_count }} 条 / {{ summary.story_count }} 个故事
          </span>
        </div>
      </div>
    </div>
  </Dialog>
</template>
