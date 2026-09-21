<script setup lang="ts">
import { computed } from 'vue'
import { type WorktimeMismatchResponse } from '@/api/reports'
import { RDM_BROWSE_URL } from './charts'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'

// 工时不一致明细弹窗:由父级(Reports.vue)在迭代概览「工时」卡下钻时打开,
// 父级负责取数,本组件只做纯展示(与 StoryListDialog / AvgTimeDevelopersDialog 同构)。
//
// 这份清单回答的是「合计为什么对不上」:列出**计划工时与投入工时不相等的每一个条目**,
// 按差额(投入 − 计划)从大到小 —— 正的在上(多报),负的在下(漏填)。
//
// ⚠⚠ **两个方向都必须在清单里**(用户 2026-09-17 定的口径)。
//   早先只列「投入 > 计划」的方向,于是清单里「差额」列相加(实测 botadp-Sprint-11 = +28)
//   比卡片上的净差额(+8)大 —— 欠报那部分被丢掉了,读的人只能得出"有一边算错了"。
//   全列之后,清单自带的差额列相加**恰好等于**卡片上的净差额(sum(rows.delta) == delta_total),
//   不需要合计行、也不需要任何补充说明。
//   ⚠ 所以这个弹窗里没有表尾合计、也没有口径注释:数字自己能对上时,多一句解释都是噪音。
const props = defineProps<{
  visible: boolean
  /**
   * 整份响应(rows + 合计)。
   * ⚠ 传整个响应而不是拆成多个 prop:这些数是**同一次查询的快照**,
   *   拆开后任何一个漏传/传错都会让弹窗内部自相矛盾,而拆开本身没有任何收益。
   */
  data: WorktimeMismatchResponse | null
  loading: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

/** 数值文本:整数不带小数点(6 → "6"),非整数保留一位(8.25 → "8.3")。与概览卡同口径。 */
function hoursText(hours: number | null): string {
  if (hours === null) return '—'
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1)
}

/** 带符号文本:正数补「+」;负数原样(负号本身就是信息,不能省) */
function signedText(hours: number): string {
  return hours > 0 ? `+${hoursText(hours)}` : hoursText(hours)
}

const rows = computed(() => props.data?.rows ?? [])
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
        <span>工时不一致明细</span>
        <span class="ds-meta">计划工时与投入工时不相等的条目，按差额从大到小</span>
      </div>
    </template>

    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <DataTable
      v-else-if="rows.length > 0"
      :value="rows"
      class="ds-table"
    >
      <!-- 短列统一挂 ds-nowrap、不写死 width:table-layout:auto 下中文 min-content 只有一个
           字宽,窄容器里短表头会被压成逐字竖排;而写死宽度在窄容器里是负作用
           (见 BugListDialog 的实测注释)。「名称」是长文本列,必须能折行 ⇒ 不挂。 -->
      <Column field="issue_key" :header="TH.code" class="ds-nowrap">
        <template #body="{ data: row }">
          <!-- 点编码新开 tab 跳 RDM 详情页:这份清单的用途就是拿着它去源头改数据,
               原地给出可跳的入口比让人自己去搜编号省一步。 -->
          <a
            v-if="row.issue_key"
            :href="RDM_BROWSE_URL + row.issue_key"
            target="_blank"
            rel="noopener noreferrer"
          >{{ row.issue_key }}</a>
        </template>
      </Column>
      <Column field="issue_type" :header="TH.type" class="ds-nowrap" />
      <Column field="issue_name" :header="TH.name" />
      <Column field="status" :header="TH.status" class="ds-nowrap" />
      <Column field="assignee" :header="TH.assignee" class="ds-nowrap" />
      <Column :header="TH.planWorktime" class="ds-nowrap">
        <template #body="{ data: row }">{{ hoursText(row.plan_worktime) }}</template>
      </Column>
      <Column :header="TH.actualWorktime" class="ds-nowrap">
        <template #body="{ data: row }">{{ hoursText(row.actual_worktime) }}</template>
      </Column>
      <Column :header="TH.worktimeDelta" class="ds-nowrap">
        <template #body="{ data: row }">
          <!-- 两个方向给两种色:多报 ⇒ warn(要去看一眼),漏填 ⇒ secondary(推向背景)。
               与项目里「是 ⇒ warn / 否 ⇒ secondary」的取值口径同族;
               符号仍在文字里,颜色只是加快扫读,不承担唯一区分职责。 -->
          <Tag
            :severity="row.delta > 0 ? 'warn' : 'secondary'"
            :value="signedText(row.delta)"
          />
        </template>
      </Column>
    </DataTable>
    <div v-else class="ds-empty">该迭代没有计划与投入不一致的条目</div>
  </Dialog>
</template>
