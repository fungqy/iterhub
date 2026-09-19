<script setup lang="ts">
import type { BugListItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import { RDM_BROWSE_URL } from './charts'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'
import { ref } from 'vue'
import BugInstanceDetailDialog from './BugInstanceDetailDialog.vue'

// 故障明细列表弹窗,展示某单元格/行/汇总下的故障明细。
// 这张表里同时装着**两类**故障:RDM 故障(source='RDM')与文档故障(source='DOC'),
// 由后端 get_bug_list 用 UNION ALL 合并。
//
// 行点击:两类故障**都**可点,统一打开「故障详情」——
//   RDM 行 → 字段 + 故障变更记录;DOC 行 → 字段 + 现场截图。
// 「编码」列的行为按来源区分(见模板注释):RDM 跳 RDM 详情页,DOC 是纯文本。
//
// 这一版删掉了「截图」与「是否典型」两列,并把列宽定死(2026-09-17):
//   · 截图列 —— 删掉的是**这一列**,不是截图本身。文档故障的现场截图改由「点开这一行」的口子看
//     (详情弹窗的「现场截图」段)。删列之后这个入口反而更顺:原先只有「有图」的行才给按钮,
//     没有图的行走进去是空态;现在整行一律可点,「有没有图」交给详情页如实回答。
//   · 是否典型 —— 该列从上线起就没有数据源(后端 fetch 里硬编码 `"is_typical": ''`),屏幕上恒空。
//
// ⚠ 列宽用 width + 后端实测的列值宽度定,不靠 table-layout 自动分配。
//   原因见 components.scss 的 ds-nowrap 段:DataTable 是 `table-layout: auto`,而中文的
//   min-content 只有一个字宽 —— 六个 2~8 字的短列会被「名称」这类长文本列榨到近乎一个字,
//   表头只得逐字竖排。实测值(4 个 Sprint / 260 行,全角按 2 计):
//     序号 3 / 编码 17 / 开发 6 / 优先级 4 / 标签 8 / 来源 3 / 名称 max 377 · p50 74 / 原因 68
//   故短列一律 ds-nowrap 且给出下限宽度,把富余空间明确让给「名称」与「原因及分析」两列 ——
//   这两列**必须能折行**,给它们 nowrap 会把表撑出横向滚动条。行高本就由「名称」决定(它最宽),
//   所以短列定宽不会增加任何一行的高度。
defineProps<{
  visible: boolean
  title: string
  data: BugListItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const detailVisible = ref(false)
const detailKey = ref<string | null>(null)
const detailSource = ref<'RDM' | 'DOC'>('DOC')

const prioritySeverityMap: Record<string, 'danger' | 'warn' | 'info' | 'success' | 'secondary'> = {
  '致命': 'danger',
  '严重': 'warn',
  '一般': 'info',
  '轻微': 'success',
  '优化': 'secondary',
  // 文档故障表用的是另一套档位(极高/高/中/低),与 RDM 的 致命/严重/一般/轻微 并存;
  // 两套都写在这里,各自的行才能取到自己的映射,而不会落到 secondary 的灰底。
  '极高': 'danger',
  '高': 'warn',
  '中': 'info',
  '低': 'success',
}

/** 有编码的行才可点。判定与点击处理器同源,不会「看着可点却点不动」 */
function rowClass(row: BugListItem): string {
  return row.issue_key ? 'is-clickable' : ''
}

function onRowClick(event: { data: BugListItem }): void {
  const row = event.data
  if (!row?.issue_key) return
  // 来源由行自己声明,不靠「有没有截图」之类的间接特征推断
  detailSource.value = row.source === 'DOC' ? 'DOC' : 'RDM'
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
        <span>{{ title }}</span>
        <span class="ds-meta">点击任意一行查看故障详情 · RDM 故障看变更记录，文档故障看现场截图</span>
      </div>
    </template>

    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="data.length > 0"
      :value="data"
      class="ds-table"
      :row-class="rowClass"
      @row-click="onRowClick"
    >
      <Column field="index" :header="TH.seq" class="ds-nowrap" style="width: 4rem" />
      <Column field="issue_key" :header="TH.code" class="ds-nowrap" style="width: 11rem">
        <template #body="{ data }">
          <!-- RDM 行:编码是真的能跳的出处,新开 tab 跳 RDM 故障详情页。
               ⚠ 整行现在也可点(is-clickable),故必须 @click.stop ——
               否则点编码会「又跳转又开详情」。 -->
          <a
            v-if="data.source !== 'DOC' && data.issue_key"
            :href="RDM_BROWSE_URL + data.issue_key"
            target="_blank"
            rel="noopener noreferrer"
            @click.stop
          >{{ data.issue_key }}</a>
          <!-- 文档故障:RDM 里没有对应编码,m09xxxxx 这类 key 点过去只会落空 ⇒ 纯文本 -->
          <span v-else>{{ data.issue_key }}</span>
        </template>
      </Column>
      <Column field="issue_name" :header="TH.name" />
      <Column field="developer" :header="TH.developer" class="ds-nowrap" style="width: 7rem" />
      <Column field="reason_analysis" :header="TH.reasonAnalysis" />
      <Column field="priority" :header="TH.priority" class="ds-nowrap" style="width: 6.5rem">
        <template #body="{ data }">
          <Tag
            :severity="prioritySeverityMap[data.priority] ?? 'secondary'"
            :value="data.priority"
          />
        </template>
      </Column>
      <Column field="tag" :header="TH.tag" class="ds-nowrap" style="width: 7.5rem" />
      <Column field="source" :header="TH.source" class="ds-nowrap" style="width: 6.5rem" />
    </DataTable>
    <div v-else class="ds-empty">暂无数据</div>

    <!-- ⚠ 详情自 2026-09-19 起是**非模态右侧抽屉**，不再是子弹窗。两件事必须分清：
         ① 组件树里它仍是本弹窗的子级（Sprint 靠 provide/inject 传得下去），
            但 DOM 上两者**都** teleport 到 body —— 不是父子关系；
         ② 故层级**不由 DOM 顺序决定**：PrimeVue 每开一层就向自己的全局计数器取号
            (ZIndex)，后开的 z-index 更大。实测「列表弹窗 < 抽屉(z=1104)」即由此而来。
            靠"谁写在模板后面"判断层叠是错的。
         抽屉非模态 ⇒ 底下的列表保持可点，这正是"看完一条直接点下一条"的前提。
         Sprint 不必往这里传 —— 详情组件自己从页面 provide 的下钻上下文里取(见 useSprintScope)。 -->
    <BugInstanceDetailDialog
      v-model:visible="detailVisible"
      :source="detailSource"
      :issue-key="detailKey"
    />
  </Dialog>
</template>
