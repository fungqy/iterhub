<script setup lang="ts">
import { ref } from 'vue'
import type { ReopenBugItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import { prioritySeverity } from '@/constants/priorityMeta'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'
import { RDM_BROWSE_URL } from './charts'
import BugInstanceDetailDialog from './BugInstanceDetailDialog.vue'

// 故障重开列表:某 Sprint 的**全部**重开故障(每只一条,带重开次数)。
//
// 入口唯一(2026-09-21 起):「Sprint 概览」弹窗的「故障重开率」卡。此前它由质量报表页的
// 「故障重开数」分布表逐格下钻打开,那张表已改为纯展示 —— 同一份明细不该有两条入口。
//
// 交互与「故障明细」(BugListDialog)**同构**,这是刻意的:
//   · 整行可点(有 issue_key 的行给 is-clickable),点开右侧**非模态抽屉**看字段 + 变更记录;
//   · 编码列是外链,必须 @click.stop,否则"又跳转又开抽屉";
//   · 短列 ds-nowrap + 定宽(宽度直接沿用 BugListDialog 的实测值),把富余宽度让给
//     「名称」与「原因及分析」两列 —— 这两列必须能折行。
// 两个列表的差别只在列:这里没有「来源」(只可能是 RDM)与「结果」,多了「重开次数」。
//
// ⚠ 分档筛选(重开 1 次 / 2 次 / 多次)已于 2026-09-21 移除:它是为「故障重开数」卡上
//   的那一格格子服务的,入口换成「故障重开率」后没有档位可带;而重开次数现在就是一列,
//   肉眼可读、无需再切一套筛选口径。
//
// 后端口径见 /reports/bugs/reopen 的 docstring(重开 = change_detail 为
// '待测试 -> 处理中' 的一次流转)。
defineProps<{
  visible: boolean
  reopenBugs: ReopenBugItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

// ── 行点击 → 统一的「故障详情」──
// 本表全是 RDM 故障,故来源恒为 'RDM'。
const detailVisible = ref(false)
const detailKey = ref<string | null>(null)

/** 有编码的行才可点。判定与点击处理器同源,不会「看着可点却点不动」 */
function rowClass(row: ReopenBugItem): string {
  return row.issue_key ? 'is-clickable' : ''
}

function openDetail(row: ReopenBugItem): void {
  if (!row.issue_key) return
  detailKey.value = row.issue_key
  detailVisible.value = true
}
</script>

<template>
  <Dialog
    :visible="visible"
    class="ds-dialog-xl"
    modal
    :pt="MAXIMIZED_DIALOG_PT"
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="flex flex-col gap-1">
        <span>故障重开列表</span>
        <span class="ds-meta">点击任意一行查看故障详情（含变更记录）</span>
      </div>
    </template>

    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="reopenBugs.length > 0"
      :value="reopenBugs"
      class="ds-table"
      :row-class="rowClass"
      @row-click="openDetail($event.data)"
    >
      <!-- 列宽口径与 BugListDialog 一致(短列 nowrap + 定宽,长文本列不挂 nowrap)。
           「原因及分析」绑 bug_reason:RDM 口径下它就是该列的正文 —— 故障明细那条查询
           也是把 bug_reason 当 reason_text 输出的(见后端 /bugs/reopen 的 docstring)。 -->
      <Column field="index" :header="TH.seq" class="ds-nowrap" style="width: 4rem" />
      <Column field="issue_key" :header="TH.code" class="ds-nowrap" style="width: 11rem">
        <template #body="{ data }">
          <a
            v-if="data.issue_key"
            :href="RDM_BROWSE_URL + data.issue_key"
            target="_blank"
            rel="noopener noreferrer"
            @click.stop
          >{{ data.issue_key }}</a>
        </template>
      </Column>
      <Column field="issue_name" :header="TH.name" />
      <Column field="bug_maker" :header="TH.developer" class="ds-nowrap" style="width: 7rem" />
      <Column field="bug_reason" :header="TH.reasonAnalysis" />
      <Column field="priority" :header="TH.priority" class="ds-nowrap" style="width: 6.5rem">
        <template #body="{ data }">
          <Tag :severity="prioritySeverity(data.priority)" :value="data.priority" />
        </template>
      </Column>
      <Column field="tag" :header="TH.tag" class="ds-nowrap" style="width: 7.5rem" />
      <Column field="reopen_times" :header="TH.reopenTimes" class="ds-nowrap" style="width: 6.5rem" />
    </DataTable>
    <div v-else class="ds-empty">该迭代暂无重开故障</div>

    <!-- 统一的「故障详情」(字段 + 变更记录)。
         Sprint 不往这里传:详情组件自己从页面 provide 的下钻上下文里取(见 useSprintScope)。 -->
    <BugInstanceDetailDialog
      v-model:visible="detailVisible"
      source="RDM"
      :issue-key="detailKey"
    />
  </Dialog>
</template>
