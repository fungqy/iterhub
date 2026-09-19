<script setup lang="ts">
import { type SprintReopenMemberItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'

// 故障重开(按成员)分布弹窗:由父级(Reports.vue)在「故障重开率」卡下钻时打开,
// 父级负责取数,本组件只做纯展示(与 TeamMembersDialog 同构)。
//
// 口径以后端 /reports/sprint-reopen-members 的 docstring 为准,两点在此点明:
// 1. 只列「有重开记录」的成员 —— 后端已按此过滤,无重开的成员不出现在结果里,
//    故表格天然不含 0 行;若该迭代整体无重开则返回空数组,由下方 empty 态兜底。
// 2. 三档(重开 1 次 / 2 次 / 多次)与卡片上的重开次数同源,三栏之和 = 该成员被重开的
//    故障数,所有成员之和 = 概览「故障重开率」卡的「重开 N」。成员身份取故障修复人,
//    与「团队成员明细」的故障归属口径一致。
// 后端已按 重开总数 → 人名 排好序(重开多的排前),顺序带语义,表格不再开放点击排序。
defineProps<{
  visible: boolean
  members: SprintReopenMemberItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()
</script>

<template>
  <Dialog
    :visible="visible"
    class="ds-dialog-md"
    modal
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="flex flex-col gap-1">
        <span>故障重开分布（按成员）</span>
        <span class="ds-meta">
          成员身份取故障修复人；重开 1 次 / 2 次 / 多次（≥3 次），仅列出有重开记录的成员
        </span>
      </div>
    </template>
    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="members.length > 0"
      :value="members"
      class="ds-table"
    >
      <!-- 数字列挂 ds-nowrap(机制见 ExecutionLogTable / BugListDialog 注释);
           「成员」是名称类、长度不可控 ⇒ 不挂,省下的宽度归它。 -->
      <Column field="member" :header="TH.member" />
      <Column field="reopen_once" :header="TH.reopenOnce" class="ds-nowrap" />
      <Column field="reopen_twice" :header="TH.reopenTwice" class="ds-nowrap" />
      <Column field="reopen_many" :header="TH.reopenMany" class="ds-nowrap" />
    </DataTable>
    <div v-else class="ds-empty">该迭代暂无故障重开数据</div>
  </Dialog>
</template>
