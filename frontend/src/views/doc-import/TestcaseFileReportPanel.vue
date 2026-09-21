<script setup lang="ts">
import { computed } from 'vue'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Message from 'primevue/message'
import type { TestcaseFileReport } from '@/api/dataImport'
import { TH } from '@/constants/tableHeaders'

/**
 * 一份源文件的校验/导入报告。
 *
 * 2026-09-21 从 DocTestcaseImport.vue 抽出来:支持一次上传多份文件后,第 3 步(校验)与
 * 第 5 步(导入)都要**逐份**渲染结论,内联展开会在那个组件里长出一模一样的两大块。
 *
 * ⚠ 两个阶段刻意共用这一个组件:后端两侧走同一个 evaluate_testcase_import(),报告是
 *   同形的,界面若各写一套,「校验说 3 行可导」与「实际导了 42 行」这类分歧就会藏在两套
 *   代码的差异里,没人发现。
 */
const props = defineProps<{
  report: TestcaseFileReport
  /** validate=只出结论;import=额外展示实际写入行数与解码信息 */
  phase: 'validate' | 'import'
}>()

/** 迭代状态的中文名 —— 要让人一眼看出这个迭代是不是还在进行 */
const SPRINT_STATE_LABEL: Record<string, string> = {
  active: '进行中',
  closed: '已结束',
  future: '未开始',
}

const stories = computed(() => props.report.stories ?? [])

/** 读取的行数 vs 归并出的用例数 —— 源文档里一个用例占「首行 + N 行步骤」 */
const mergeNote = computed(() => {
  const r = props.report
  return `源文档 ${r.total_rows ?? 0} 行 → 归并出 ${r.case_count ?? 0} 个用例（含步骤 ${r.step_count ?? 0} 条）`
})

/** 入库行数 − 用例数:差额是「一个用例引用多个故事」展开出来的,不是重复导入 */
const expandNote = computed(() => {
  const r = props.report
  const written = r.imported ?? 0
  const cases = r.case_count ?? 0
  if (written === cases) return `共 ${cases} 个用例，每个引用 1 个故事，入库 ${written} 行。`
  return `共 ${cases} 个用例，其中引用多个故事的被展开成多行，故入库 ${written} 行。`
})

const skipRows = computed(() => {
  const s = props.report.skipped
  if (!s) return []
  return [
    {
      label: '关键字为空且不是步骤行',
      count: s.no_case_key,
      hint: '既不是用例首行也不是步骤行，无法归属',
    },
    {
      label: '步骤行出现在任何用例之前',
      count: s.orphan_step,
      hint: '没有可挂靠的用例，多半是首行被删掉了',
    },
    { label: '空的步骤行（只有步骤ID）', count: s.empty_step, hint: '没有步骤内容，未计入步骤数' },
  ].filter(r => r.count > 0)
})

/** 整份文件的结论 —— 校验与导入只差动词,故在一处按 phase 收口 */
const conclusion = computed(() => {
  const r = props.report
  if (!r.valid) {
    if (!r.header_ok) return '表头校验未通过，文件无法用于导入'
    return `整份文件被拒绝（共读取 ${r.total_rows ?? 0} 行）`
  }
  if (props.phase === 'import') return `成功导入 ${r.imported ?? 0} 行`
  return `校验通过：${r.importable ?? 0} 行可导入（${r.case_count ?? 0} 个用例，共读取 ${r.total_rows ?? 0} 行）`
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="font-medium">{{ report.filename }}</p>

    <Message :severity="report.valid ? 'success' : 'error'" :closable="false">
      {{ conclusion }}
    </Message>

    <p class="ds-meta">{{ mergeNote }}</p>

    <div v-if="stories.length" class="flex flex-col gap-2">
      <p class="ds-meta">故事号 → 迭代归属</p>
      <DataTable :value="stories" class="ds-table">
        <Column field="story_key" :header="TH.storyKey" class="ds-nowrap" />
        <Column :header="TH.sprint" class="ds-nowrap">
          <template #body="{ data }">
            {{ data.sprint_name || data.sprint_id || '—' }}
          </template>
        </Column>
        <Column header="迭代状态" class="ds-nowrap">
          <template #body="{ data }">
            {{ SPRINT_STATE_LABEL[data.state] || data.state || '—' }}
          </template>
        </Column>
        <Column field="case_count" header="用例数" class="ds-nowrap" />
      </DataTable>
    </div>

    <div v-if="report.missing_stories?.length" class="flex flex-col gap-2">
      <p class="ds-meta">
        以下故事号在 rdm_issue 中不存在（共 {{ report.missing_stories.length }} 个）
      </p>
      <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
        <li v-for="k in report.missing_stories.slice(0, 20)" :key="k">{{ k }}</li>
      </ul>
    </div>

    <div v-if="report.case_sets?.length" class="flex flex-col gap-2">
      <p class="ds-meta">文档中的用例集</p>
      <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
        <li v-for="cs in report.case_sets" :key="cs.name">
          {{ cs.name }}：{{ cs.count }} 个用例
        </li>
      </ul>
    </div>

    <template v-if="report.valid && phase === 'import'">
      <p class="ds-meta">{{ expandNote }}</p>
      <p v-if="report.encoding" class="ds-meta">
        源文件按 <b>{{ report.encoding }}</b> 解码。
      </p>
    </template>

    <div v-if="report.errors?.length" class="flex flex-col gap-2">
      <p class="ds-meta">{{ report.valid ? '明细' : '原因' }}</p>
      <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
        <li v-for="(err, idx) in report.errors" :key="idx">{{ err }}</li>
      </ul>
    </div>

    <div v-if="report.valid && phase === 'import' && skipRows.length" class="flex flex-col gap-2">
      <p class="ds-meta">已跳过</p>
      <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
        <li v-for="row in skipRows" :key="row.label">
          {{ row.label }}：{{ row.count }} 条<span class="ml-1">（{{ row.hint }}）</span>
        </li>
      </ul>
    </div>
  </div>
</template>
