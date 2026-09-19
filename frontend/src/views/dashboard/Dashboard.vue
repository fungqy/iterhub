<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { projectApi } from '@/api/projects'
import { jobApi, type TodayTask } from '@/api/jobs'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Paginator, { type PageState } from 'primevue/paginator'
import Skeleton from 'primevue/skeleton'
import { TASK_TYPE_LABELS, TASK_TYPE_SEVERITY, taskStatusText, taskStatusSeverity } from '@/constants/taskMeta'
import { formatDateTimeShort, formatDateLong } from '@/utils/datetime'
import { TH } from '@/constants/tableHeaders'

const projects = ref<any[]>([])
const todayTasks = ref<TodayTask[]>([])
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(10)

const jobCurrentPage = ref(1)
const jobPageSize = ref(10)

onMounted(async () => {
  loading.value = true
  try {
    const [projectsRes, tasksRes] = await Promise.all([
      projectApi.getList(),
      jobApi.getTodayTasks(),
    ])
    projects.value = projectsRes
    todayTasks.value = tasksRes
  } finally {
    loading.value = false
  }
})

// 任务类型/执行状态的口径统一在 @/constants/taskMeta,时间格式统一在 @/utils/datetime。
// 本页原先自建了 taskTypeMap / taskSeverityMap / statusMap 三份 map,且缺 sonar_reminder
// 与 running 两项 —— 导致这两类数据在表格里直接显示英文原始值,已移除。
const todayLabel = formatDateLong()

// 「已开启提醒」的项目:原先分页数据、总页数、Paginator 的 totalRecords 三处各写了一遍
// 同样的过滤条件,任一处漏改就会分页错乱 —— 收敛为单一 computed。
const remindEnabledProjects = computed(() =>
  projects.value.filter(p =>
    p.need_story_remind || p.need_task_remind || p.need_sonar_scan_remind || p.need_report_data
  )
)

const paginatedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return remindEnabledProjects.value.slice(start, start + pageSize.value)
})

const paginatedJobs = computed(() => {
  const start = (jobCurrentPage.value - 1) * jobPageSize.value
  return todayTasks.value.slice(start, start + jobPageSize.value)
})

const totalPages = computed(() => Math.ceil(remindEnabledProjects.value.length / pageSize.value))

const jobTotalPages = computed(() => Math.ceil(todayTasks.value.length / jobPageSize.value))

// 骨架屏仅用于「首次加载且尚无任何数据」——首屏是空表格闪一下才出数据,观感较差。
// 翻页/刷新等已有数据的场景继续用 DataTable 自身的 loading 遮罩,避免骨架反复闪烁。
const initialLoading = computed(
  () => loading.value && todayTasks.value.length === 0 && projects.value.length === 0
)

const pendingTasks = computed(() => todayTasks.value.filter(t => t.status === 'pending').length)
const successTasks = computed(() => todayTasks.value.filter(t => t.status === 'success').length)
const failedTasks = computed(() => todayTasks.value.filter(t => t.status === 'failed').length)

const stats = computed(() => [
  { label: '今日任务', value: todayTasks.value.length, tone: 'total' },
  { label: '待执行', value: pendingTasks.value, tone: 'pending' },
  { label: '已完成', value: successTasks.value, tone: 'success' },
  { label: '失败', value: failedTasks.value, tone: 'failed' },
] as Array<{ label: string; value: number; tone: 'total' | 'pending' | 'success' | 'failed' }>)

function onJobPage(e: PageState) {
  jobCurrentPage.value = e.page + 1
  jobPageSize.value = e.rows
}

function onProjectPage(e: PageState) {
  currentPage.value = e.page + 1
  pageSize.value = e.rows
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>工作台</h1>
      </div>
      <p class="m-0 inline-flex items-center gap-2 px-4 py-1.5 ds-meta bg-[var(--ih-surface)] border border-[var(--ih-line)] rounded-full"><span class="ds-tag-dot tone-contrast"></span>{{ todayLabel }}</p>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <template v-if="initialLoading">
        <div v-for="i in 4" :key="i" class="ds-stat tone-zero">
          <Skeleton width="3rem" height="2.25rem" />
          <Skeleton width="4rem" height="0.875rem" />
        </div>
      </template>
      <template v-else>
        <!-- 值为 0 的卡降级为中性:值本就是 0 就不该用彩色喊话,
             否则「失败 0」的红色卡片会一直报警,真失败时反而失去区分度 -->
        <div
          v-for="s in stats"
          :key="s.label"
          class="ds-stat"
          :class="s.value === 0 ? 'tone-zero' : `tone-${s.tone}`"
        >
          <span class="ds-stat-value">{{ s.value }}</span>
          <span class="ds-stat-label">{{ s.label }}</span>
        </div>
      </template>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <Card class="ds-card">
        <template #title>今日任务</template>
        <template #content>
          <div class="flex flex-wrap gap-2">
            <Tag v-if="pendingTasks > 0" severity="warn" :value="`${pendingTasks} 待执行`" />
            <Tag v-if="failedTasks > 0" severity="danger" :value="`${failedTasks} 失败`" />
          </div>
          <DataTable :value="paginatedJobs" :loading="loading" class="ds-table">
            <template #empty>
              <div v-if="initialLoading" class="flex flex-col gap-3 py-2">
                <Skeleton v-for="i in 4" :key="i" height="2rem" />
              </div>
              <span v-else>暂无今日任务</span>
            </template>
            <Column field="project_name" :header="TH.project">
              <template #body="{ data }">{{ data.project_name }}</template>
            </Column>
            <!-- 短列挂 ds-nowrap(机制见 ExecutionLogTable / BugListDialog 注释);
                 「项目」属名称类、长度不可控 ⇒ 不挂,省下的宽度归它。 -->
            <Column field="task_type" :header="TH.type" class="ds-nowrap">
              <template #body="{ data }">
                <Tag
                  :severity="TASK_TYPE_SEVERITY[data.task_type] ?? 'secondary'"
                  :value="TASK_TYPE_LABELS[data.task_type] || data.task_type"
                />
              </template>
            </Column>
            <Column field="scheduled_time" :header="TH.plannedAt" class="ds-nowrap">
              <template #body="{ data }">
                {{ formatDateTimeShort(data.scheduled_time) }}
              </template>
            </Column>
            <Column field="status" :header="TH.status" class="ds-nowrap">
              <template #body="{ data }">
                <Tag
                  :severity="taskStatusSeverity(data.status)"
                  :value="taskStatusText(data.status)"
                />
              </template>
            </Column>
          </DataTable>
          <div v-if="jobTotalPages > 1">
            <Paginator
              :first="(jobCurrentPage - 1) * jobPageSize"
              :rows="jobPageSize"
              :totalRecords="todayTasks.length"
              template="PrevPageLink PageLinks NextPageLink"
              @page="onJobPage"
            />
          </div>
        </template>
      </Card>

      <Card class="ds-card">
        <template #title>项目提醒配置</template>
        <template #content>
          <DataTable :value="paginatedProjects" :loading="loading" class="ds-table">
            <template #empty>
              <div v-if="initialLoading" class="flex flex-col gap-3 py-2">
                <Skeleton v-for="i in 4" :key="i" height="2rem" />
              </div>
              <span v-else>暂无项目</span>
            </template>
            <Column field="project_name" :header="TH.project">
              <template #body="{ data }">{{ data.project_name }}</template>
            </Column>
            <Column :header="TH.remindProgress" class="ds-nowrap">
              <template #body="{ data }">
                {{ data.need_story_remind ? data.story_remind_time : '—' }}
              </template>
            </Column>
            <Column :header="TH.remindTask" class="ds-nowrap">
              <template #body="{ data }">
                {{ data.need_task_remind ? data.task_remind_time : '—' }}
              </template>
            </Column>
            <Column :header="TH.remindScan" class="ds-nowrap">
              <template #body="{ data }">
                {{ data.need_sonar_scan_remind ? data.sonar_remind_time : '—' }}
              </template>
            </Column>
          </DataTable>
          <div v-if="totalPages > 1">
            <Paginator
              :first="(currentPage - 1) * pageSize"
              :rows="pageSize"
              :totalRecords="remindEnabledProjects.length"
              template="PrevPageLink PageLinks NextPageLink"
              @page="onProjectPage"
            />
          </div>
        </template>
      </Card>
    </div>
  </div>
</template>
