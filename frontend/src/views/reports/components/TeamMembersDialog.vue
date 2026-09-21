<script setup lang="ts">
import { type SprintMemberItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'

// 团队成员明细弹窗:由父级(Reports.vue)在「团队成员」卡下钻时打开,
// 父级负责取数,本组件只做纯展示(与 AvgTimeDevelopersDialog / StoryListDialog 同构)。
//
// 口径以后端 /reports/sprint-members 的 docstring 为准,两条容易误读的在此点明:
// 1. 行集恒等于概览卡片上的成员数,含「任务数与故障数都为 0」的成员 ——
//    行数与卡片对得上比表格紧凑更重要,否则用户会以为漏了数据。
// 2. 「故障数」是该成员作为**故障修复人**修复的故障数,不是故障的经办人:
//    实测故障经办人恒为提单的测试人员(整个迭代的故障会全挤在一人名下),
//    按修复人统计才反映「这人改了多少故障」。
// 后端已按 任务数 → 故障数 → 人名 排好序(有产出的在前、0/0 行垫底),
// 顺序本身带语义,故表格不再开放点击排序。
defineProps<{
  visible: boolean
  members: SprintMemberItem[]
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
        <span>团队成员明细</span>
        <span class="ds-meta">
          任务数按子任务经办人统计，故障数按故障修复人统计；行数与概览「团队成员」一致
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
      <Column field="task_count" :header="TH.taskCount" class="ds-nowrap" />
      <Column field="bug_count" :header="TH.bugCount" class="ds-nowrap" />
    </DataTable>
    <div v-else class="ds-empty">该迭代无关联人员</div>
  </Dialog>
</template>
