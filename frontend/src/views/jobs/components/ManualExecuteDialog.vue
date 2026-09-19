<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { jobApi } from '@/api/jobs'
import { reportsApi, type ProjectConfig, type SprintOption } from '@/api/projects'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import Dialog from 'primevue/dialog'
import Select from 'primevue/select'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
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
const sprintId = ref<string>('')
const sprints = ref<SprintOption[]>([])
const dialogLoading = ref(false)

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

async function loadSprints(projectConfigId: number) {
  try {
    sprints.value = await reportsApi.getSprints(projectConfigId)
  } catch {
    sprints.value = []
  }
}

function onProjectSelectChange(value: number | null) {
  sprintId.value = ''
  if (value && needsSprint.value) {
    loadSprints(value)
  } else {
    sprints.value = []
  }
}

// 任务类型切换:报表数据需在已选项目的前提下加载 Sprint;其它类型清空 Sprint 选择
watch(taskType, (val) => {
  sprintId.value = ''
  if (val === 'report_data' && projectId.value) {
    loadSprints(projectId.value)
  } else {
    sprints.value = []
  }
})

// ── 报表数据轮询 ─────────────────────────────────────────────────
let pollingTimer: ReturnType<typeof setInterval> | null = null
const POLL_INTERVAL = 2000
const POLL_MAX_TIMES = 150 // 5 分钟兜底
const POLL_GROUP = 'report-polling'

function stopPolling() {
  if (pollingTimer !== null) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
}

function pollReportDataStatus(sprint: string) {
  // 防御:先终止已有轮询,避免旧定时器泄漏后反复弹出成功提示
  stopPolling()
  let count = 0
  // 常驻提示(独立 group,结束时 removeGroup 清掉)
  toast.add({
    severity: 'info',
    summary: '提示',
    detail: '报表数据执行中，请稍候...',
    group: POLL_GROUP,
    life: POLL_MAX_TIMES * POLL_INTERVAL + 10000,
    closable: false,
  })
  // 每个轮询持有自己的定时器引用,终态时自我清理,不依赖模块级变量
  const timer = setInterval(async () => {
    count++
    if (count > POLL_MAX_TIMES) {
      clearInterval(timer)
      if (pollingTimer === timer) pollingTimer = null
      toast.removeGroup(POLL_GROUP)
      notify('warn', '任务执行超时(5分钟)，请到执行日志查看结果')
      emit('confirm')
      return
    }
    try {
      const res = await jobApi.getReportDataStatus(sprint)
      if (res.status === 'success' || res.status === 'failed' || res.status === 'unknown') {
        // 到达终态立即自毁,防止定时器泄漏导致重复提示
        clearInterval(timer)
        if (pollingTimer === timer) pollingTimer = null
        toast.removeGroup(POLL_GROUP)
        if (res.status === 'success') {
          notify('success', '任务执行成功')
        } else if (res.status === 'failed') {
          notify('error', res.error || '任务执行失败')
        } else {
          // 后端重启等原因导致状态丢失,任务已不在执行
          notify('warn', '任务状态已丢失，请到执行日志查看结果')
        }
        emit('confirm')
      }
    } catch {
      // 网络抖动,继续轮询
    }
  }, POLL_INTERVAL)
  pollingTimer = timer
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
    if (!sprintId.value) {
      notify('warn', '请选择 Sprint')
      return
    }

    try {
      const { exists } = await jobApi.checkReportDataExists(
        projectId.value,
        sprintId.value,
      )
      if (exists) {
        const ok = await new Promise<boolean>((resolve) => {
          confirm.require({
            message: '该 Sprint 的相关表中已有数据，继续执行数据将被覆盖，是否继续？',
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
    } catch {
      return
    }

    // 报表数据走后台任务模式: 立即入队, 不阻塞 dialog
    try {
      await jobApi.manualReportData({
        project_config_id: projectId.value,
        sprint_id: sprintId.value,
      })
    } catch {
      return // 409 等由 interceptor 处理
    }
    emit('update:visible', false)
    pollReportDataStatus(sprintId.value)
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
    sprintId.value = ''
    sprints.value = []
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
      <Message severity="info" :closable="false">请选择任务类型、项目（报表数据需额外选择 Sprint）</Message>
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
        <label class="ds-meta" for="manual-sprint">选择 Sprint *</label>
        <Select
          v-model="sprintId"
          inputId="manual-sprint"
          :options="sprintOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="请选择 Sprint"
          fluid
          :disabled="!projectId"
        >
          <template #option="{ option }">
            <div>
              <span>{{ option.label }}</span>
              <Tag v-if="option.hasData" severity="success" value="已有数据" />
            </div>
          </template>
        </Select>
      </div>
    </div>
    <template #footer>
      <Button label="取消" severity="secondary" @click="emit('update:visible', false)" />
      <Button label="确认执行" icon="pi pi-play" :loading="dialogLoading" @click="confirmExecute" />
    </template>
  </Dialog>
</template>
