<script setup lang="ts">
import { computed } from 'vue'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'
import type { SprintMetricsItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import { REOPEN_MANY_MIN, type ReopenBucket } from './reopenBuckets'

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
const props = withDefaults(defineProps<{
  /** 项目指标列表(父组件已按展示窗口裁剪,与其余三张趋势图同一批 Sprint) */
  metrics: SprintMetricsItem[]
  loading?: boolean
}>(), {
  loading: false,
})

// 上抛时带上被点的档位:点「多次」这一格就该只看 ≥3 次的故障,而不是该 Sprint 的全量。
// 边界由 reopenBuckets.ts 唯一定义,卡片与弹窗不会各判一套。
const emit = defineEmits<{
  (e: 'select', sprintId: number, bucket: ReopenBucket): void
}>()

interface ReopenRow {
  sprintId: number
  name: string
  once: number
  twice: number
  many: number
  total: number
}

// 三个档位列的装配表。列头文案留在卡片:它受半宽卡的宽度约束(「多次」不能写成
// 「多次（≥3 次）」),而档位标识取共用常量 —— 改边界只需改 reopenBuckets.ts。
const bucketCols: { field: 'once' | 'twice' | 'many'; header: string; bucket: ReopenBucket }[] = [
  { field: 'once', header: '重开 1 次', bucket: 'once' },
  { field: 'twice', header: '重开 2 次', bucket: 'twice' },
  { field: 'many', header: '重开多次', bucket: 'many' },
]

const rows = computed<ReopenRow[]>(() => props.metrics.map((s) => {
  // 缺字段一律按 0 兜底:老版本后端(未升级)不该让整张表渲染成 NaN
  const once = s.reopen_once ?? 0
  const twice = s.reopen_twice ?? 0
  const many = s.reopen_many ?? 0
  return {
    // 接口返回的 sprint_id 实际是字符串。这里转成 number 是让**行自身**语义自洽
    // (sprintId 就是"点这行要下钻的那个 Sprint");下钻入口的 setActiveSprint
    // 还会再归一化一次兜底,两条防线各管各的,谁都不依赖对方。
    sprintId: Number(s.sprint_id),
    // 与趋势图横轴同一口径:统一用 sprint_name(前端不再消费 short_sprint_name,
    // 后者在同项目内会撞名,如 JSST-Sprint1 与 JSST-1.0-Sprint-1 都缩成 Sprint1)
    name: s.sprint_name,
    once,
    twice,
    many,
    total: once + twice + many,
  }
}))

// 无重开故障的行不可点 —— 否则会出现「点了没反应」的假可点。
// 判定与点击处理器同源(都以 total 为准),两处不会打架。
// 行点击 = 不分档(等价于点「合计」),档位过滤只由数字格触发。
function rowClass(row: ReopenRow): string {
  return row.total > 0 ? 'is-clickable' : ''
}

function onRowClick(event: { data: ReopenRow }): void {
  const row = event.data
  if (row && row.total > 0) emit('select', row.sprintId, 'all')
}

// 值为 0 的档位格子:既不可点,也不把点击透给整行(row-click = 全部)。
// 为什么必须吞掉冒泡:否则「点重开 2 次那个 0」会打开该 Sprint 的**全部**明细 ——
// 同一片区域、同样的外观,行为只因数不同而分叉,这种设计迟早被当成 bug。
// 语义收敛成一句话:点数字 = 看那一档;0 不是数字入口,点它什么也不发生。
function onZeroCellClick(): void {
  /* 有意空实现:仅用于 @click.stop 吞掉冒泡 */
}
</script>

<template>
  <!-- 复用 ds-trend-card:它提供副标题 0.875rem 的字号口径,与同排三张趋势图卡一致
       (Aura 的 card 段没定义 subtitle 字号,不挂就继承 16px,同排会出现两档字号)。
       ds-reopen-card 是本卡私有作用域,只用于紧凑行高(见 components.scss)。 -->
  <Card class="ds-card ds-trend-card ds-reopen-card">
    <template #title>故障重开数</template>
    <template #subtitle>
      <div class="flex flex-wrap items-center gap-3">
        <span class="ds-meta">| 点击数字查看明细</span>
        <!-- 分桶边界必须写在界面上:只写「多次」读者无从知道是 2 次以上还是 3 次以上。
             数字取自共用常量,改边界时这行文案自动跟着走。 -->
        <span class="ds-meta">多次 = 重开 {{ REOPEN_MANY_MIN }} 次及以上</span>
      </div>
    </template>
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
          :row-class="rowClass"
          @row-click="onRowClick"
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
          >
            <template #body="{ data }">
              <!-- 每个档位各自可点:点「多次」就只列 ≥3 次的故障(弹窗按 reopen_times 过滤)。
                   值为 0 的格子渲染成纯文本 —— 可点性判定与显示值同源,不会出现「点了没反应」;
                   @click.stop 防止冒泡到 row-click(那是不分档的「全部」入口)。 -->
              <button
                v-if="data[col.field] > 0"
                type="button"
                class="ds-cell-button"
                :aria-label="`查看 ${data.name} ${col.header}的故障`"
                @click.stop="emit('select', data.sprintId, col.bucket)"
              >
                {{ data[col.field] }}
              </button>
              <span v-else @click.stop="onZeroCellClick">0</span>
            </template>
          </Column>
          <Column field="total" :header="TH.total" class="ds-nowrap">
            <template #body="{ data }">
              <!-- 行本身不可聚焦,故「合计」这一格用真按钮承载键盘可达性
                   (与 BugDetailTable 的 .ds-cell-button 同口径);@click.stop 防止
                   冒泡到 row-click 触发两次 emit。合计 = 不分档,即「全部」。 -->
              <button
                v-if="data.total > 0"
                type="button"
                class="ds-cell-button"
                :aria-label="`查看 ${data.name} 的全部重开故障`"
                @click.stop="emit('select', data.sprintId, 'all')"
              >
                {{ data.total }}
              </button>
              <span v-else @click.stop="onZeroCellClick">0</span>
            </template>
          </Column>
        </DataTable>
        <div v-else-if="!loading" class="ds-empty">暂无数据</div>
      </div>
    </template>
  </Card>
</template>
