<script setup lang="ts">
import { ref } from 'vue'
import type { AvgTimeDeveloperItem } from '@/api/reports'
import { useNotify } from '@/utils/notify'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'
import { RDM_BROWSE_URL } from './charts'
import BugInstanceDetailDialog from './BugInstanceDetailDialog.vue'

const notify = useNotify()

// 故障平均时长弹窗,展示指定 Sprint 下各开发人员的故障时长,按总时长倒序。
//
// 行点击 = 打开统一的「故障详情」(字段 + 故障变更记录)。
// 此前这里是一个只显示时间线的「故障变更记录」子弹窗 —— 已并入统一详情,
// 故本组件不再自己取变更记录(详情组件会连同字段一起取,只多一次内联返回,不多一次往返)。
defineProps<{
  visible: boolean
  developers: AvgTimeDeveloperItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

// 秒换算为天,保留一位小数
function secondsToDays(seconds: number): string {
  return (seconds / 86400).toFixed(1)
}

const detailVisible = ref(false)
const detailKey = ref<string | null>(null)

/** 有编码的行才可点。本表全是 RDM 故障,故来源恒为 'RDM' */
function rowClass(row: AvgTimeDeveloperItem): string {
  return row.issue_key ? 'is-clickable' : ''
}

function openDetail(row: AvgTimeDeveloperItem): void {
  if (!row.issue_key) {
    // 本表由 rdm_bug_duration LEFT JOIN rdm_issue 得来,理论上可能取不到编码 ——
    // 静默不响应会让人以为"点了没坏",不如明说
    notify('warn', '该故障在 rdm_issue 中无对应记录，无法打开详情')
    return
  }
  detailKey.value = row.issue_key
  detailVisible.value = true
}
</script>

<template>
  <Dialog
    :visible="visible"
    class="ds-dialog-lg"
    modal
    :pt="MAXIMIZED_DIALOG_PT"
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="flex flex-col gap-1">
        <span>故障平均解决时长（工作日口径）</span>
        <span class="ds-meta">1.点击任意一行查看故障详情（含变更记录）; 2.点击编码跳转 RDM 故障详情页</span>
      </div>
    </template>
    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="developers.length > 0"
      :value="developers"
      class="ds-table"
      :sortField="'total_seconds'"
      :sortOrder="-1"
      removableSort
      :row-class="rowClass"
      @row-click="openDetail($event.data)"
    >
      <!-- ⚠ 短列一律挂 `ds-nowrap`（本表 2026-09-17 补）：
           实测容器 ≤1024px 时，排名/开发/状态/开发时长(天)/测试时长(天)/总时长(天)
           会被榨成 2 行（900px 时「总时长(天)」甚至 3 行）。
           根因是 `table-layout:auto` + 中文 min-content 只有一个字宽，
           富余空间全被「名称」吃掉。⚠「名称」是长文本列，**不能** nowrap，
           否则会撑出横向滚动条。⚠ 只加 nowrap、**不写死宽度** ——
           写死宽度在窄容器里会把别的列挤爆（见 BugListDialog 的三宽×四配实测）。 -->
      <Column field="index" :header="TH.rank" class="ds-nowrap" />
      <Column field="developer" :header="TH.developer" class="ds-nowrap" />
      <Column field="issue_key" :header="TH.code" class="ds-nowrap">
        <template #body="{ data }">
          <!-- 点击新开 tab 跳转 RDM 故障详情页;stop 阻止触发整行的详情弹窗 -->
          <a
            v-if="data.issue_key"
            :href="RDM_BROWSE_URL + data.issue_key"
            target="_blank"
            rel="noopener noreferrer"
            @click.stop
          >{{ data.issue_key }}</a>
        </template>
      </Column>
      <!-- 「名称」是长文本列,必须能折行 ⇒ 不挂 ds-nowrap(理由见上方注释) -->
      <Column field="issue_name" :header="TH.name" />
      <Column field="status" :header="TH.status" class="ds-nowrap" />
      <Column field="dev_seconds" :header="TH.devDuration" sortable class="ds-nowrap">
        <template #body="{ data }">{{ secondsToDays(data.dev_seconds) }}</template>
      </Column>
      <Column field="test_seconds" :header="TH.testDuration" sortable class="ds-nowrap">
        <template #body="{ data }">{{ secondsToDays(data.test_seconds) }}</template>
      </Column>
      <Column field="total_seconds" :header="TH.totalDuration" sortable class="ds-nowrap">
        <template #body="{ data }">{{ secondsToDays(data.total_seconds) }}</template>
      </Column>
    </DataTable>
    <div v-else class="ds-empty">暂无故障时长数据</div>

    <!-- 统一的「故障详情」(字段 + 变更记录),与其它故障列表用的是同一个组件。
         Sprint 不往这里传:详情组件自己从页面 provide 的下钻上下文里取(见 useSprintScope)。 -->
    <BugInstanceDetailDialog
      v-model:visible="detailVisible"
      source="RDM"
      :issue-key="detailKey"
    />
  </Dialog>
</template>
