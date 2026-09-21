<script setup lang="ts">
import { computed } from 'vue'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'
import type { SprintMetricsItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'

// 「故障重开数」分布表 —— 顶替同一格里的趋势图卡。
//
// 为什么是表格:原柱+线图只回答「这个 Sprint 有几只故障被重开过」(COUNT DISTINCT),
// 回答不了「每只被重开了几次」—— 重开 1 次与重开 5 次在图上都只是 +1。
// 表格把同一批量按次数拆开:1 次 / 2 次 / 多次(≥3),行 = Sprint、列 = 次数档。
//
// 口径与后端严格同源:「合计」= reopen_once + reopen_twice + reopen_many,
// 而后端就是由这同一个分组查询派生出 bug_reopen_count 的(见 reports.py),
// 所以表格合计与原来图表上的数值、以及概览弹窗的「故障重开数」逐字对得上。
// 字段含义详见 api/reports.ts 的 SprintMetricsItem 注释。
//
// ⚠ 本卡自 2026-09-21 起是**纯展示**:原先点档位数字 / 点行会下钻到「故障重开明细」,
//   该入口已统一收口到「Sprint 概览」的「故障重开率」卡(打开重开故障列表)。
//   所以这里没有 :row-class、没有 @row-click、没有 .ds-cell-button,也没有 emit ——
//   同一份明细只留一条入口,本卡只回答「每个 Sprint 各档各有多少只」。
const props = withDefaults(defineProps<{
  /** 项目指标列表(父组件已按展示窗口裁剪,与其余三张趋势图同一批 Sprint) */
  metrics: SprintMetricsItem[]
  loading?: boolean
}>(), {
  loading: false,
})

interface ReopenRow {
  name: string
  once: number
  twice: number
  many: number
  total: number
}

// 三个档位列的装配表。列头文案留在卡片:它受半宽卡的宽度约束(「多次」不能写成
// 「多次（≥3 次）」)。
// ⚠ 「多次」的下界 = 3,由后端 reports.py 的 reopen_many 判定给出。2026-09-21 用户
//   明确要求删掉副标题里那行「多次 = 重开 N 次及以上」的说明(并要求删后同样压缩卡高),
//   故边界值**不再上界面**,界面上只留列头;前端随之不再持有该常量
//   (原 reopenBuckets.ts 的唯一消费方就是那行提示,已一并删除)。
//   要在界面上重新交代边界,改的就是这里 —— 别再引一个只剩文案的常量文件。
const bucketCols: { field: 'once' | 'twice' | 'many'; header: string }[] = [
  { field: 'once', header: '重开 1 次' },
  { field: 'twice', header: '重开 2 次' },
  { field: 'many', header: '重开多次' },
]

const rows = computed<ReopenRow[]>(() => props.metrics.map((s) => {
  // 缺字段一律按 0 兜底:老版本后端(未升级)不该让整张表渲染成 NaN
  const once = s.reopen_once ?? 0
  const twice = s.reopen_twice ?? 0
  const many = s.reopen_many ?? 0
  return {
    // 与趋势图横轴同一口径:统一用 sprint_name(前端不再消费 short_sprint_name,
    // 后者在同项目内会撞名,如 JSST-Sprint1 与 JSST-1.0-Sprint-1 都缩成 Sprint1)
    name: s.sprint_name,
    once,
    twice,
    many,
    total: once + twice + many,
  }
}))
</script>

<template>
  <!-- 复用 ds-trend-card:最初是为了借它的副标题 0.875rem 字号口径(与同排趋势图卡一致)。
       ⚠ 2026-09-21 两件事让它退化成纯标记:① 趋势图卡的图例移入标题行,那条字号规则删除;
         ② 本卡按用户要求删掉了副标题(「多次 = 重开 N 次及以上」),本卡已无副标题可赋字号。
         类名留着是因为探针按类定位卡片,本文件不再依赖它的任何样式。
       ds-reopen-card 才是本卡私有作用域:紧凑行高、锁住卡高(见 components.scss)。 -->
  <Card class="ds-card ds-trend-card ds-reopen-card">
    <template #title>故障重开数</template>
    <template #content>
      <!-- 加载态做成覆盖层而不是替换内容:表格常驻,避免加载完成瞬间卡片高度跳动 -->
      <div class="relative">
        <div
          v-if="loading"
          class="absolute inset-0 z-10 flex items-center justify-center bg-[var(--ih-surface)]"
        >
          <ProgressSpinner strokeWidth="4" />
        </div>
        <DataTable
          v-if="rows.length > 0"
          :value="rows"
          class="ds-table ds-table--center"
        >
          <!-- 短列(四个档位 + 合计)挂 ds-nowrap:这是**页内卡片**里的表,容器只有弹窗的一半宽,
               空间争抢比弹窗内更狠。「迭代」是名称类、长度不可控 ⇒ 不挂,省下的宽度归它。 -->
          <Column field="name" :header="TH.iteration" />
          <Column
            v-for="col in bucketCols"
            :key="col.field"
            :field="col.field"
            :header="col.header"
            class="ds-nowrap"
          />
          <Column field="total" :header="TH.total" class="ds-nowrap" />
        </DataTable>
        <div v-else-if="!loading" class="ds-empty">暂无数据</div>
      </div>
    </template>
  </Card>
</template>
