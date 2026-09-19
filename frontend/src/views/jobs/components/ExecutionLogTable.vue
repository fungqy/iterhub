<script setup lang="ts">
import { computed } from 'vue'
import type { TaskLogItem } from '@/api/jobs'
import {
  TASK_TYPE_LABELS,
  TASK_TYPE_SEVERITY,
  TASK_TYPE_OPTIONS,
  EXEC_TYPE_LABELS,
  EXEC_TYPE_SEVERITY,
  taskStatusText,
  taskStatusSeverity,
} from '@/constants/taskMeta'
import { formatDateTime } from '@/utils/datetime'
import { TH } from '@/constants/tableHeaders'
import InputText from 'primevue/inputtext'
import DatePicker from 'primevue/datepicker'
import Select from 'primevue/select'
import Button from 'primevue/button'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Paginator, { type PageState } from 'primevue/paginator'

// 日志表格 + 分页 + 筛选表头
// 筛选状态由父组件( Jobs.vue )持有,通过 props 传入并经 v-model 事件回传
const props = defineProps<{
  logs: TaskLogItem[]
  total: number
  currentPage: number
  pageSize: number
  loading: boolean
  filterProjectName: string
  filterExecutedDate: string
  filterTaskType: string
}>()

const emit = defineEmits<{
  (e: 'update:filterProjectName', value: string): void
  (e: 'update:filterExecutedDate', value: string): void
  (e: 'update:filterTaskType', value: string): void
  (e: 'search'): void
  (e: 'reset'): void
  (e: 'manual-execute'): void
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
}>()

function seqIndex(idx: number): number {
  return (props.currentPage - 1) * props.pageSize + idx + 1
}

// DatePicker 只接受 Date,过滤条件是 YYYY-MM-DD 字符串,此处做双向适配
function parseLocalDate(s: string): Date | null {
  const [y, m, d] = s.split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(y, m - 1, d)
}

function formatLocalDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const dateValue = computed<Date | null>({
  get: () => (props.filterExecutedDate ? parseLocalDate(props.filterExecutedDate) : null),
  set: (d) => emit('update:filterExecutedDate', d ? formatLocalDate(d) : ''),
})

// 任务类型下拉:去掉"全部"空选项,靠 showClear + placeholder="全部" 实现清空
const taskTypeSelectOptions = computed(() => TASK_TYPE_OPTIONS.filter(o => o.value !== ''))

function onPage(e: PageState) {
  if (e.rows !== props.pageSize) {
    emit('size-change', e.rows)
    return
  }
  const newPage = e.page + 1
  if (newPage !== props.currentPage) {
    emit('page-change', newPage)
  }
}
</script>

<template>
  <div class="ds-card p-6 flex flex-col gap-4 min-w-0">
    <div class="flex flex-wrap gap-3 items-end">
      <div class="flex flex-col gap-2">
        <label class="ds-meta" for="job-filter-project">项目名称</label>
        <InputText
          id="job-filter-project"
          :model-value="filterProjectName"
          placeholder="搜索项目名称"
          showClear
          @update:model-value="emit('update:filterProjectName', $event ?? '')"
          @keyup.enter="emit('search')"
        />
      </div>
      <div class="flex flex-col gap-2">
        <label class="ds-meta" for="job-filter-date">执行日期</label>
        <DatePicker
          v-model="dateValue"
          inputId="job-filter-date"
          placeholder="选择日期"
          dateFormat="yy-mm-dd"
          showIcon
          showButtonBar
        />
      </div>
      <div class="flex flex-col gap-2">
        <label class="ds-meta" for="job-filter-type">任务类型</label>
        <Select
          :model-value="filterTaskType || null"
          inputId="job-filter-type"
          :options="taskTypeSelectOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="全部"
          showClear
          @update:model-value="emit('update:filterTaskType', $event ?? '')"
        />
      </div>
      <div class="flex gap-2">
        <Button label="查询" @click="emit('search')" />
        <Button label="重置" @click="emit('reset')" />
        <Button label="手动执行" @click="emit('manual-execute')" />
      </div>
    </div>

    <div class="min-w-0">
      <DataTable :value="logs" :loading="loading" class="ds-table">
      <template #empty>暂无执行日志</template>
      <!-- 短列挂 ds-nowrap:table-layout:auto 下中文 min-content 只有一个字宽,窄容器里
           短表头会被逐字竖排;顺带把省下的宽度让给「错误信息」(长文本列,故不挂 nowrap)。
           只挂 ds-nowrap、不写死 width —— 写死宽度在窄容器里是负作用(见 BugListDialog 注释)。
           「项目」属名称类,内容长度不可控 ⇒ 不挂。 -->
      <Column :header="TH.seq" class="ds-nowrap">
        <template #body="{ index }">{{ seqIndex(index) }}</template>
      </Column>
      <Column field="project_name" :header="TH.project">
        <template #body="{ data }">{{ data.project_name }}</template>
      </Column>
      <Column field="task_type" :header="TH.type" class="ds-nowrap">
        <template #body="{ data }">
          <Tag
            :severity="TASK_TYPE_SEVERITY[data.task_type] ?? 'secondary'"
            :value="TASK_TYPE_LABELS[data.task_type] || data.task_type"
          />
        </template>
      </Column>
      <Column :header="TH.executedAt" class="ds-nowrap">
        <template #body="{ data }">{{ formatDateTime(data.executed_at) }}</template>
      </Column>
      <Column :header="TH.plannedAt" class="ds-nowrap">
        <template #body="{ data }">{{ formatDateTime(data.scheduled_time) }}</template>
      </Column>
      <Column field="status" :header="TH.status" class="ds-nowrap">
        <template #body="{ data }">
          <Tag
            :severity="taskStatusSeverity(data.status)"
            :value="taskStatusText(data.status)"
          />
        </template>
      </Column>
      <Column field="task_exec_type" :header="TH.execType" class="ds-nowrap">
        <template #body="{ data }">
          <Tag
            :severity="EXEC_TYPE_SEVERITY[data.task_exec_type] ?? 'secondary'"
            :value="EXEC_TYPE_LABELS[data.task_exec_type] || data.task_exec_type"
          />
        </template>
      </Column>
      <Column field="error_message" :header="TH.errorMessage">
        <template #body="{ data }">
          <span
            v-if="data.error_message"
            v-tooltip.top="data.error_message"
          >{{ data.error_message }}</span>
          <span v-else>—</span>
        </template>
      </Column>
    </DataTable>
    </div>

    <div v-if="total > 0">
      <Paginator
        :first="(currentPage - 1) * pageSize"
        :rows="pageSize"
        :totalRecords="total"
        :rowsPerPageOptions="[10, 20, 50]"
        template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
        currentPageReportTemplate="共 {totalRecords} 条"
        @page="onPage"
      />
    </div>
  </div>
</template>
