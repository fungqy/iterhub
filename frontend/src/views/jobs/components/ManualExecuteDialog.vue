<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { jobApi, type ManualReportDataSkipped } from '@/api/jobs'
import { sprintApi, type ProjectConfig, type SprintOption } from '@/api/projects'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import Dialog from 'primevue/dialog'
import Select from 'primevue/select'
import MultiSelect from 'primevue/multiselect'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import { TASK_TYPE_LABELS, TASK_TYPE_OPTIONS } from '@/constants/taskMeta'
import { useNotify } from '@/utils/notify'

const toast = useToast() // 仍需原生实例:报表轮询用 group + 自定义 life
const confirm = useConfirm()
const notify = useNotify()

// 手动执行弹窗:选择任务类型 / 项目 / Sprint,并负责实际的报表数据轮询与各 manualXxxReminder 接口调用。
// Sprint 是否展示 + 是否加载,完全由当前任务类型决定(目前仅 report_data 需要)——切换任务类型即时刷新。
const props = defineProps<{
  visible: boolean
  projects: ProjectConfig[]
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  // 执行成功后通知父组件刷新日志
  (e: 'confirm'): void
}>()

const taskType = ref('')
const projectId = ref<number | null>(null)
// 支持多选:一次可勾选多个 Sprint,后端排队串行执行(见 scheduler.py 的 manual/report-data)
const sprintIds = ref<string[]>([])
const sprints = ref<SprintOption[]>([])
const dialogLoading = ref(false)
// Sprint 下拉的独立加载态:见 loadSprints,它走的是会先探 RDM 的接口,可能慢
const sprintLoading = ref(false)

// 任务类型下拉:去掉"全部"空选项
const taskTypeOptions = computed(() => TASK_TYPE_OPTIONS.filter(o => o.value !== ''))

// 当前任务类型是否需要选择 Sprint(目前仅报表数据)
const needsSprint = computed(() => taskType.value === 'report_data')

// 过滤可选项目:按当前任务类型对应的开关字段
const filteredProjects = computed(() => {
  if (!taskType.value) return props.projects
  switch (taskType.value) {
    case 'story_reminder':
      return props.projects.filter(p => p.need_story_remind)
    case 'task_reminder':
      return props.projects.filter(p => p.need_task_remind)
    case 'sonar_reminder':
      return props.projects.filter(p => p.need_sonar_scan_remind)
    case 'report_data':
      return props.projects.filter(p => p.need_report_data)
    default:
      return props.projects
  }
})

const projectOptions = computed(() =>
  filteredProjects.value.map(p => ({ label: p.project_name, value: p.id })),
)

const sprintOptions = computed(() =>
  sprints.value.map(s => ({
    label: s.sprint_name,
    value: String(s.sprint_id),
    hasData: s.has_report_data ?? false,
  })),
)

/** sprint_id → 展示名;查不到时退化为 id,保证提示里总有可读标识 */
function sprintLabel(id: string) {
  return sprints.value.find(s => String(s.sprint_id) === id)?.sprint_name ?? id
}

// 请求序号:快速切项目/切任务类型会并发多个请求,只允许「最后一次」的结果落地,
// 否则先发的慢请求(尤其是失败的那种)后返回,会把新列表覆盖回空。
let sprintReqSeq = 0

/** 作废在途的 Sprint 请求,并清空列表与已勾选项 —— 项目或任务类型一变,旧的都不可信 */
function resetSprints() {
  sprintReqSeq++
  sprintLoading.value = false
  sprints.value = []
  sprintIds.value = []
}

async function loadSprints(projectConfigId: number) {
  const seq = ++sprintReqSeq
  sprintLoading.value = true
  try {
    // 走 RDM 实时接口:本地 rdm_sprint 里还没有的「新迭代」也要能在这个下拉里选到
    const list = await sprintApi.getSprints(projectConfigId)
    if (seq === sprintReqSeq) sprints.value = list
  } catch {
    // 刻意不清空 sprints:清空职责归 resetSprints,这里若清空,
    // 后到的失败请求会把已拿到的数据抹成空 —— 表现为选项闪一下又没了。
    // 错误提示由请求拦截器统一弹出,这里不再重复。
  } finally {
    if (seq === sprintReqSeq) sprintLoading.value = false
  }
}

function onProjectSelectChange(value: number | null) {
  // 项目换了,旧列表属于上一个项目,无论随后是否加载成功都必须先清掉
  resetSprints()
  if (value && needsSprint.value) {
    loadSprints(value)
  }
}

// 任务类型切换:报表数据需在已选项目的前提下加载 Sprint;其它类型清空 Sprint 选择
watch(taskType, (val) => {
  resetSprints()
  if (val === 'report_data' && projectId.value) {
    loadSprints(projectId.value)
  }
})

// ── 报表数据轮询 ─────────────────────────────────────────────────
let pollingTimer: ReturnType<typeof setInterval> | null = null
const POLL_INTERVAL = 2000
// 单个 Sprint 的等待上限(5 分钟)。多选是**串行**排队执行,总时长要按数量放大 ——
// 否则排在后面的 Sprint 必然被判超时,而那只是排队久,并非真的卡死。
const POLL_MAX_TIMES_PER_SPRINT = 150
const POLL_GROUP = 'report-polling'

function stopPolling() {
  if (pollingTimer !== null) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
  // ⚠ 常驻提示必须一并撤掉:轮询途中卸载组件时 onUnmounted 只走到这里,
  //   若不清 group,会留下一条约 5 分钟、且 closable:false 的「执行中」幽灵提示。
  toast.removeGroup(POLL_GROUP)
}

/** 收尾:清定时器 + 撤常驻提示,并通知父组件刷新日志 */
function finishPolling(timer: ReturnType<typeof setInterval>) {
  clearInterval(timer)
  if (pollingTimer === timer) pollingTimer = null
  toast.removeGroup(POLL_GROUP)
  emit('confirm')
}

/**
 * 轮询一批报表任务直到全部到达终态,并汇总提示。
 *
 * 只轮询后端真正入队的 id —— 被跳过的 Sprint(已在执行 / RDM 未找到)根本不会产生
 * 状态,一并轮询会永远等不到终态。
 */
function pollReportDataStatus(ids: string[]) {
  // 防御:先终止已有轮询,避免旧定时器泄漏后反复弹出成功提示
  stopPolling()
  if (!ids.length) return

  const waiting = new Set(ids)
  const succeeded: string[] = []
  const failed: { id: string; reason: string }[] = []
  const maxTimes = POLL_MAX_TIMES_PER_SPRINT * ids.length
  let count = 0

  // 常驻提示(独立 group,结束时 removeGroup 清掉)
  toast.add({
    severity: 'info',
    summary: '提示',
    detail: ids.length > 1
      ? `报表数据执行中（共 ${ids.length} 个迭代，排队依次执行），请稍候...`
      : '报表数据执行中，请稍候...',
    group: POLL_GROUP,
    life: maxTimes * POLL_INTERVAL + 10000,
    closable: false,
  })

  // 每个轮询持有自己的定时器引用,终态时自我清理,不依赖模块级变量
  const timer = setInterval(async () => {
    count++
    if (count > maxTimes) {
      finishPolling(timer)
      notify('warn', '任务执行超时，请到执行日志查看结果')
      return
    }

    // 并发查仍在执行的那些:Sprint 之间互不影响,串行查只会白等
    const results = await Promise.all(
      [...waiting].map(async (id) => {
        try {
          return { id, res: await jobApi.getReportDataStatus(id) }
        } catch {
          return null // 网络抖动,下一轮再查
        }
      }),
    )

    for (const item of results) {
      if (!item) continue
      const { id, res } = item
      if (res.status === 'pending' || res.status === 'running') continue
      waiting.delete(id)
      if (res.status === 'success') {
        succeeded.push(id)
      } else if (res.status === 'failed') {
        failed.push({ id, reason: res.error || '未知原因' })
      } else {
        // 后端重启等原因导致状态丢失,任务已不在执行
        failed.push({ id, reason: '任务状态已丢失' })
      }
    }

    if (waiting.size > 0) return
    // 全部到达终态立即自毁,防止定时器泄漏导致重复提示
    finishPolling(timer)
    notifyReportDataResult(succeeded, failed)
  }, POLL_INTERVAL)
  pollingTimer = timer
}

/** 按「全成功 / 部分成功 / 全失败」三档汇总提示;失败项带迭代名与原因 */
function notifyReportDataResult(
  succeeded: string[],
  failed: { id: string; reason: string }[],
) {
  if (!failed.length) {
    notify(
      'success',
      succeeded.length > 1 ? `${succeeded.length} 个迭代报表数据执行成功` : '任务执行成功',
    )
    return
  }

  // 失败项可能很多,只列前 3 个,其余折叠成数量 —— toast 里塞不下十几个名字
  const shownCount = Math.min(failed.length, 3)
  const detail = failed
    .slice(0, shownCount)
    .map(f => `${sprintLabel(f.id)}（${f.reason}）`)
    .join('；')
  const suffix = failed.length > shownCount ? ` 等 ${failed.length} 个迭代` : ''

  if (!succeeded.length) {
    notify('error', `${failed.length} 个迭代执行失败：${detail}${suffix}`)
  } else {
    notify('warn', `${succeeded.length} 个成功，${failed.length} 个失败：${detail}${suffix}`)
  }
}

onUnmounted(stopPolling)

async function confirmExecute() {
  if (!taskType.value) {
    notify('warn', '请选择任务类型')
    return
  }

  if (!projectId.value) {
    notify('warn', '请选择项目')
    return
  }

  if (taskType.value === 'report_data') {
    if (!sprintIds.value.length) {
      notify('warn', '请选择 Sprint')
      return
    }

    // 一次批量检查(后端单次 IN 查询),已有数据的迭代要在覆盖前逐个列出来
    let existing: string[] = []
    try {
      existing = (await jobApi.checkReportDataExists(sprintIds.value)).existing
    } catch {
      return
    }
    if (existing.length) {
      const ok = await new Promise<boolean>((resolve) => {
        confirm.require({
          message:
            `以下迭代的相关表中已有数据，继续执行数据将被覆盖：${existing
              .map(id => sprintLabel(id))
              .join('、')}。是否继续？`,
          header: '确认覆盖',
          icon: 'pi pi-exclamation-triangle',
          acceptLabel: '继续执行',
          rejectLabel: '取消',
          accept: () => resolve(true),
          reject: () => resolve(false),
        })
      })
      if (!ok) return
    }

    // 报表数据走后台任务模式: 立即入队, 不阻塞 dialog
    let taskIds: string[] = []
    let skipped: ManualReportDataSkipped[] = []
    try {
      const res = await jobApi.manualReportData({
        project_config_id: projectId.value,
        sprint_ids: sprintIds.value,
      })
      taskIds = res.task_ids
      skipped = res.skipped
    } catch {
      return // 409 等由 interceptor 处理
    }
    emit('update:visible', false)
    // 被跳过的迭代不会产生任务状态,必须当场告知,否则用户以为全都跑了
    if (skipped.length) {
      notify(
        'warn',
        `${skipped.length} 个迭代未执行：${skipped
          .map(s => `${sprintLabel(s.sprint_id)}（${s.reason}）`)
          .join('；')}`,
      )
    }
    pollReportDataStatus(taskIds)
    return
  }

  dialogLoading.value = true
  try {
    switch (taskType.value) {
      case 'story_reminder':
        await jobApi.manualStoryReminder({ project_config_id: projectId.value })
        break
      case 'task_reminder':
        await jobApi.manualTaskReminder({ project_config_id: projectId.value })
        break
      case 'sonar_reminder':
        await jobApi.manualSonarReminder({ project_config_id: projectId.value })
        break
    }
    notify('success', '任务执行成功')
    emit('update:visible', false)
    emit('confirm')
  } catch {
    // handled by interceptor
  } finally {
    dialogLoading.value = false
  }
}

// 每次打开时重置表单状态
watch(() => props.visible, (val) => {
  if (val) {
    taskType.value = ''
    projectId.value = null
    // 关窗时请求可能还在途,重开必须作废它并复位加载态/勾选,否则会在新会话里落地旧数据
    resetSprints()
  }
})
</script>

<template>
  <Dialog
    :visible="visible"
    :header="taskType ? '手动执行 - ' + (TASK_TYPE_LABELS[taskType] || taskType) : '手动执行'"
    class="ds-dialog-sm"
    modal
    :dismissableMask="false"
    :closable="!dialogLoading"
    @update:visible="emit('update:visible', $event)"
  >
    <div class="flex flex-col gap-4">
      <div class="flex flex-col gap-2">
        <label class="ds-meta" for="manual-task-type">任务类型 *</label>
        <Select
          v-model="taskType"
          inputId="manual-task-type"
          :options="taskTypeOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="请选择任务类型"
          fluid
        />
      </div>

      <div class="flex flex-col gap-2">
        <label class="ds-meta" for="manual-project">选择项目 *</label>
        <Select
          v-model="projectId"
          inputId="manual-project"
          :options="projectOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="请选择项目"
          fluid
          @change="onProjectSelectChange($event.value)"
        />
      </div>

      <div v-if="needsSprint" class="flex flex-col gap-2">
        <label class="ds-meta" for="manual-sprint">选择 Sprint *（可多选，按勾选顺序依次执行）</label>
        <MultiSelect
          v-model="sprintIds"
          inputId="manual-sprint"
          :options="sprintOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="请选择 Sprint（可多选）"
          fluid
          filter
          display="chip"
          :maxSelectedLabels="3"
          :showToggleAll="false"
          :loading="sprintLoading"
          :disabled="!projectId"
        >
          <template #option="{ option }">
            <div>
              <span>{{ option.label }}</span>
              <Tag v-if="option.hasData" severity="success" value="已有数据" />
            </div>
          </template>
          <!-- 覆盖 primevueLocale.ts 的全局空态文案:加载中与确实无数据必须能区分开 -->
          <template #empty>
            <span>{{ sprintLoading ? '正在加载迭代列表…' : '暂无可选迭代' }}</span>
          </template>
        </MultiSelect>
      </div>
    </div>
    <template #footer>
      <Button label="取消" severity="secondary" @click="emit('update:visible', false)" />
      <Button label="确认执行" icon="pi pi-play" :loading="dialogLoading" @click="confirmExecute" />
    </template>
  </Dialog>
</template>
