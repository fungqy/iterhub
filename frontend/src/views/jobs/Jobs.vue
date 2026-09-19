<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { jobApi, type TaskLogItem } from '@/api/jobs'
import { projectApi, type ProjectConfig } from '@/api/projects'
import ExecutionLogTable from './components/ExecutionLogTable.vue'
import ManualExecuteDialog from './components/ManualExecuteDialog.vue'

// 状态编排层:日志/分页/筛选/项目与 Sprint 加载,展示与交互拆到子组件

const loading = ref(false)
const logs = ref<TaskLogItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)

const filterProjectName = ref('')
const filterExecutedDate = ref(new Date().toISOString().slice(0, 10))
const filterTaskType = ref('')

const projects = ref<ProjectConfig[]>([])
const dialogVisible = ref(false)

onMounted(async () => {
  await Promise.all([loadLogs(), loadProjects()])
})

async function loadLogs() {
  loading.value = true
  try {
    const res = await jobApi.getLogs({
      page: currentPage.value,
      page_size: pageSize.value,
      project_name: filterProjectName.value || undefined,
      executed_date: filterExecutedDate.value || undefined,
      task_type: filterTaskType.value || undefined,
    })
    logs.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadProjects() {
  try {
    projects.value = await projectApi.getList()
  } catch {
    // handled by interceptor
  }
}

function handleSearch() {
  currentPage.value = 1
  loadLogs()
}

function handleReset() {
  filterProjectName.value = ''
  filterExecutedDate.value = new Date().toISOString().slice(0, 10)
  filterTaskType.value = ''
  currentPage.value = 1
  loadLogs()
}

function handleManualExecute() {
  dialogVisible.value = true
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadLogs()
}

function handleSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  loadLogs()
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>任务调度</h1>
      </div>
    </div>

    <div class="flex flex-col gap-6">
      <ExecutionLogTable
        :logs="logs"
        :total="total"
        :current-page="currentPage"
        :page-size="pageSize"
        :loading="loading"
        v-model:filter-project-name="filterProjectName"
        v-model:filter-executed-date="filterExecutedDate"
        v-model:filter-task-type="filterTaskType"
        @search="handleSearch"
        @reset="handleReset"
        @manual-execute="handleManualExecute"
        @page-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <!-- Dialog -->
    <ManualExecuteDialog
      v-model:visible="dialogVisible"
      :projects="projects"
      @confirm="loadLogs"
    />
  </div>
</template>
