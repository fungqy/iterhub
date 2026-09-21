<script setup lang="ts">
import { type StoryListItem } from '@/api/reports'
import { RDM_BROWSE_URL } from './charts'
import { formatDate } from '@/utils/datetime'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'

// 故事列表弹窗:Sprint 内**某一子集故事**的明细表,由父级(Reports.vue)在概览卡下钻时打开,
// 父级负责取数,本组件只做纯展示(与 AvgTimeDevelopersDialog / TeamMembersDialog 同构)。
//
// 目前服务两种下钻 —— 两者行结构、列、交互完全一致,差异只在文案,故文案做成 props:
//   1. 「计划外故事占比」卡 → 计划外故事(rdm_issue.is_unplaned = 1,Sprint 激活后插入);
//   2. 「用例覆盖率」卡    → 未被用例覆盖的故事(rdm_testcase 里没有任何一行引用到它)。
// ⚠ 文案**不给默认值**:两处语气不同(「该迭代无计划外故事」 vs 「该迭代的故事均已被用例覆盖」),
//   留个默认值只会在调用方漏传时静默显示成另一张表的说法。
defineProps<{
  visible: boolean
  /** 标题 / 副标题 / 空态文案,由调用方按自己的口径给出(见上方说明) */
  title: string
  subtitle: string
  emptyText: string
  stories: StoryListItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()
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
        <span>{{ title }}</span>
        <span class="ds-meta">{{ subtitle }}</span>
      </div>
    </template>
    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="stories.length > 0"
      :value="stories"
      class="ds-table"
    >
      <!-- 短列统一挂 ds-nowrap:table-layout:auto 下中文 min-content 只有一个字宽,
           窄容器(≤900px 视口)里短表头会被压成逐字竖排(实测「负责人」= 2 行 / 62px)。
           只挂 ds-nowrap、不写死 width —— 写死宽度在窄容器里是负作用(见 BugListDialog 注释)。 -->
      <Column field="issue_key" :header="TH.code" class="ds-nowrap">
        <template #body="{ data }">
          <!-- 点击新开 tab 跳转 RDM 故事详情页(与故障编码同一交互) -->
          <a
            v-if="data.issue_key"
            :href="RDM_BROWSE_URL + data.issue_key"
            target="_blank"
            rel="noopener noreferrer"
          >{{ data.issue_key }}</a>
        </template>
      </Column>
      <!-- 「名称」是长文本列,必须能折行 ⇒ 不挂 ds-nowrap -->
      <Column field="issue_name" :header="TH.name" />
      <Column field="status" :header="TH.status" class="ds-nowrap" />
      <Column field="priority" :header="TH.priority" class="ds-nowrap" />
      <Column field="assignee" :header="TH.assignee" class="ds-nowrap" />
      <Column :header="TH.createdAt" class="ds-nowrap">
        <template #body="{ data }">
          {{ data.created ? formatDate(data.created) : '—' }}
        </template>
      </Column>
    </DataTable>
    <div v-else class="ds-empty">{{ emptyText }}</div>
  </Dialog>
</template>
