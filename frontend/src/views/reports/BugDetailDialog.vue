<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { reportsApi, type BugDetailResponse, type BugListItem } from '@/api/reports'
import { useNotify } from '@/utils/notify'
import { useSprintScope } from '@/composables/useSprintScope'
import Dialog from 'primevue/dialog'
import ProgressSpinner from 'primevue/progressspinner'
import BugChartCard from './components/BugChartCard.vue'
import BugDetailTable from './components/BugDetailTable.vue'
import BugListDialog from './components/BugListDialog.vue'
import { PRIORITY_COLORS, TAG_COLORS, DEVELOPER_COLORS } from './components/charts'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'

const notify = useNotify()
const notifyError = (detail: string) => notify('error', detail)

const props = defineProps<{
  visible: boolean
}>()

/**
 * 当前下钻的 Sprint —— 由页面 provide、本弹窗自己取(见 useSprintScope)。
 * 改前它是个 prop,由 Reports.vue 的 currentSprintForBug 传进来;现在没有这条通道了:
 * 下钻的 Sprint 只有页面那一份,谁都别再造第二条。
 */
const sprintScope = useSprintScope()
const sprintId = computed(() => sprintScope?.value ?? null)

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'charts-resize': []
}>()

const bugDetail = ref<BugDetailResponse | null>(null)
const loadingBugDetail = ref(false)

async function loadBugDetails() {
  const sid = sprintId.value
  if (sid == null) return
  loadingBugDetail.value = true
  try {
    const res = await reportsApi.getBugDetails(sid)
    bugDetail.value = res
  } catch {
    notifyError('加载故障详情失败')
  } finally {
    loadingBugDetail.value = false
  }
}

// 弹窗打开期间监听窗口 resize,并向父组件发出 charts-resize,由外部报表图自行重排
function handleChartsResize() {
  emit('charts-resize')
}

const priorityChartData = computed(() => {
  if (!bugDetail.value) return []
  const result: { name: string; value: number }[] = []
  for (const priority of bugDetail.value.priorities) {
    let total = 0
    for (const developer of bugDetail.value.developers) {
      const devData = bugDetail.value.data[developer.developer]
      if (devData && devData[priority]) {
        for (const tag of Object.keys(devData[priority])) {
          total += devData[priority][tag]
        }
      }
    }
    if (total > 0) {
      result.push({ name: priority, value: total })
    }
  }
  return result
})

const tagChartData = computed(() => {
  if (!bugDetail.value) return []
  const result: { name: string; value: number }[] = []
  for (const tag of bugDetail.value.tags) {
    let total = 0
    for (const developer of bugDetail.value.developers) {
      const devData = bugDetail.value.data[developer.developer]
      if (!devData) continue
      for (const priority of Object.keys(devData)) {
        if (devData[priority] && devData[priority][tag]) {
          total += devData[priority][tag]
        }
      }
    }
    if (total > 0) {
      result.push({ name: tag, value: total })
    }
  }
  return result
})

const developerChartData = computed(() => {
  if (!bugDetail.value) return []
  return bugDetail.value.developers
    .map((dev) => ({ name: dev.developer, value: dev.total }))
    .filter(item => item.value > 0)
    .sort((a, b) => b.value - a.value)
})

function onBugDialogClose() {
  window.removeEventListener('resize', handleChartsResize)
  bugDetail.value = null
}

const bugListDialogVisible = ref(false)
const bugList = ref<BugListItem[]>([])
const loadingBugList = ref(false)
const bugListTitle = ref('')

async function openBugList(developer: string, priority: string, tag: string) {
  const sid = sprintId.value
  if (sid == null) return
  bugListTitle.value = `${developer} - ${priority} - ${tag}`
  bugListDialogVisible.value = true
  loadingBugList.value = true
  try {
    const res = await reportsApi.getBugList(sid, developer, priority, tag)
    bugList.value = res
  } catch {
    notifyError('加载故障明细失败')
  } finally {
    loadingBugList.value = false
  }
}

async function openBugListByRow(developer: string) {
  const sid = sprintId.value
  if (sid == null || !bugDetail.value) return
  bugListTitle.value = `${developer} - 全部`
  bugListDialogVisible.value = true
  loadingBugList.value = true
  try {
    const res = await reportsApi.getBugList(sid, developer)
    res.forEach((item, idx) => item.index = idx + 1)
    bugList.value = res
  } catch {
    notifyError('加载故障明细失败')
  } finally {
    loadingBugList.value = false
  }
}

async function openBugListBySummary(priority: string, tag: string) {
  const sid = sprintId.value
  if (sid == null) return
  bugListTitle.value = `合计 - ${priority} - ${tag}`
  bugListDialogVisible.value = true
  loadingBugList.value = true
  try {
    const res = await reportsApi.getBugList(sid, undefined, priority, tag)
    res.forEach((item, idx) => item.index = idx + 1)
    bugList.value = res
  } catch {
    notifyError('加载故障明细失败')
  } finally {
    loadingBugList.value = false
  }
}

async function openBugListAll() {
  const sid = sprintId.value
  if (sid == null || !bugDetail.value) return
  bugListTitle.value = `全部故障`
  bugListDialogVisible.value = true
  loadingBugList.value = true
  try {
    const res = await reportsApi.getBugList(sid)
    res.forEach((item, idx) => item.index = idx + 1)
    bugList.value = res
  } catch {
    notifyError('加载故障明细失败')
  } finally {
    loadingBugList.value = false
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    window.addEventListener('resize', handleChartsResize)
    loadBugDetails()
  } else {
    onBugDialogClose()
  }
})

// ⚠ 组件在「可见状态下被卸载」(切路由 / 父组件销毁) 时,visible 的 watch 不会再触发,
//   监听器会留在 window 上继续持有本组件 —— 既是内存泄漏,也会在销毁后对被卸载的
//   组件回调。onBugDialogClose 只会由 watch 触发,覆盖不到这条路径。
onUnmounted(() => {
  window.removeEventListener('resize', handleChartsResize)
})
</script>

<template>
  <Dialog
    :visible="visible"
    header="故障分布统计"
    class="ds-dialog-xl"
    modal
    :pt="MAXIMIZED_DIALOG_PT"
    @update:visible="emit('update:visible', $event)"
  >
    <div class="flex flex-col gap-4">
      <div v-if="loadingBugDetail" class="flex flex-col items-center gap-2 py-8">
        <ProgressSpinner strokeWidth="4" />
      </div>
      <template v-else-if="bugDetail">
      <!-- 列数自适应(不再是 lg:grid-cols-3):必须保证每张卡内容宽 ≥ 386,
           否则「环 + 右侧图例」会换行成上下两排 —— 推导见 components.scss 的 .ds-ring-card-grid -->
      <div v-if="priorityChartData.length > 0 || tagChartData.length > 0 || developerChartData.length > 0" class="ds-ring-card-grid">
        <BugChartCard
          title="级别分布"
          :data="priorityChartData"
          :color-map="PRIORITY_COLORS"
          :center-font-size="40"
        />
        <BugChartCard
          title="原因分布"
          :data="tagChartData"
          :color-list="TAG_COLORS"
        />
        <BugChartCard
          title="人员分布"
          :data="developerChartData"
          :color-list="DEVELOPER_COLORS"
          :legend-count="5"
        />
      </div>

      <BugDetailTable
        :detail="bugDetail"
        @cell-click="openBugList"
        @row-click="openBugListByRow"
        @summary-click="openBugListBySummary"
        @summary-all-click="openBugListAll"
      />
      </template>
      <div v-else class="ds-empty">
        暂无故障数据
      </div>
    </div>

    <BugListDialog
      v-model:visible="bugListDialogVisible"
      :title="bugListTitle"
      :data="bugList"
      :loading="loadingBugList"
    />
  </Dialog>
</template>
