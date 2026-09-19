<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ReopenBugItem } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'
import SelectButton from 'primevue/selectbutton'
import { RDM_BROWSE_URL } from './charts'
import BugInstanceDetailDialog from './BugInstanceDetailDialog.vue'
import {
  REOPEN_BUCKETS,
  matchesReopenBucket,
  reopenBucketLabel,
  reopenBucketOf,
  type ReopenBucket,
} from './reopenBuckets'

// 故障重开明细弹窗。除了该 Sprint 的重开故障列表,还承载「按重开次数分档」的过滤 ——
// 卡片上点「重开 2 次」那一格进来,这里就只列重开 2 次的那些故障。
//
// 过滤放在前端而不是再多一个后端参数:同一批数据(每只故障的 reopen_times)既要用于
// 显示「重开次数」列,又要用于分档;再让后端按档位查一遍,就等于同一个判定写在两处。
// 数据量也无压力 —— 单 Sprint 的重开故障全库最多十几只。
//
// 行点击 = 打开统一的「故障详情」(字段 + 变更记录),与其它故障列表一致。
const props = withDefaults(defineProps<{
  visible: boolean
  reopenBugs: ReopenBugItem[]
  loading: boolean
  /** 当前档位。由卡片上被点的格子决定('all' = 点「合计」数字或整行) */
  bucket?: ReopenBucket
}>(), {
  bucket: 'all',
})

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:bucket': [value: ReopenBucket]
}>()

// 档位不在弹窗内自存一份,而是回传给父组件(父组件 v-model:bucket)。
// 为什么:若自存,「点 A 行『多次』→ 弹窗内切回『全部』→ 关闭 → 再点 B 行『多次』」时,
// 父组件的 bucket 值两次都是 'many'、并未变化,任何 watch(props.bucket) 都不会触发,
// 弹窗就会停在『全部』。让状态只有父组件一个持有者,这类陈旧状态无从产生。
const activeBucket = computed<ReopenBucket>({
  get: () => props.bucket,
  set: (value) => emit('update:bucket', value),
})

const bucketCount = computed<Record<ReopenBucket, number>>(() => {
  const counts: Record<ReopenBucket, number> = {
    all: props.reopenBugs.length,
    once: 0,
    twice: 0,
    many: 0,
  }
  for (const bug of props.reopenBugs) counts[reopenBucketOf(bug.reopen_times ?? 0)] += 1
  return counts
})

// 计数取自分档结果本身,故「全部」恒等于其余三档之和 —— 界面上自洽。
// 这些数字应与卡片上同一 Sprint 的四个格子逐个相等(同源:都是每只故障计一次)。
const bucketOptions = computed(() =>
  REOPEN_BUCKETS.map(b => ({ label: `${reopenBucketLabel(b)} (${bucketCount.value[b]})`, value: b }))
)

const filteredBugs = computed(() =>
  props.reopenBugs
    .filter(bug => matchesReopenBucket(bug.reopen_times ?? 0, activeBucket.value))
    // 序号按当前视图重排:沿用后端序号会出现 2、5、9 这样的跳号,像是有数据丢了
    .map((bug, i) => ({ ...bug, index: i + 1 }))
)

function emptyText(): string {
  return props.bucket === 'all'
    ? '暂无重开故障数据'
    : `该迭代没有${reopenBucketLabel(props.bucket)}的故障`
}

// ── 行点击 → 统一的「故障详情」──
// 本表全是 RDM 故障,故来源恒为 'RDM'。分档过滤会重排列表,但每行的 issue_key 不变,
// 所以「先切档再点行」取到的仍然是那一行自己的故障(序号重排不影响它)。
const detailVisible = ref(false)
const detailKey = ref<string | null>(null)

/** 有编码的行才可点。判定与点击处理器同源 */
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
    class="ds-dialog-lg"
    modal
    :pt="MAXIMIZED_DIALOG_PT"
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="flex flex-col gap-1">
        <span>故障重开明细</span>
        <span class="ds-meta">点击任意一行查看故障详情（含变更记录）</span>
      </div>
    </template>
    <div v-if="loading" class="flex flex-col items-center gap-2 py-8">
      <ProgressSpinner strokeWidth="4" />
    </div>
    <template v-else>
      <!-- 只有一种档位有数据时也保留分段控件:它是「当前看的是哪一档」的唯一提示,
           去掉之后用户看到 2 行会以为明细就是 2 行。 -->
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SelectButton
          v-model="activeBucket"
          :options="bucketOptions"
          option-label="label"
          option-value="value"
          :allow-empty="false"
        />
        <span class="ds-meta">共 {{ filteredBugs.length }} 个</span>
      </div>
      <DataTable
        v-if="filteredBugs.length > 0"
        :value="filteredBugs"
        class="ds-table"
        :row-class="rowClass"
        @row-click="openDetail($event.data)"
      >
        <!-- 全站最宽的一张表(10 列):短列统一挂 ds-nowrap,省下的宽度让给长文本列。
             ⚠ 判据是「**单元格内容**是否长文本」,不是「表头只有两个字」 ——
             「原因」(bug_reason)与「结果」(resolution)表头虽短,内容却是整段文字,
             挂 nowrap 会把整段撑成一行、直接顶出横向滚动条 ⇒ 与「名称」一并排除。 -->
        <Column field="index" :header="TH.seq" class="ds-nowrap" />
        <Column field="issue_key" :header="TH.code" class="ds-nowrap">
          <template #body="{ data }">
            <!-- 与其它列表一致:编码跳 RDM;整行可点,故必须 @click.stop 免得"又跳又开" -->
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
        <Column field="reopen_times" :header="TH.reopenTimes" class="ds-nowrap" />
        <Column field="bug_maker" :header="TH.developer" class="ds-nowrap" />
        <Column field="reporter" :header="TH.reporter" class="ds-nowrap" />
        <Column field="bug_type" :header="TH.type" class="ds-nowrap" />
        <Column field="priority" :header="TH.priority" class="ds-nowrap" />
        <Column field="bug_reason" :header="TH.reason" />
        <Column field="resolution" :header="TH.resolution" />
      </DataTable>
      <div v-else class="ds-empty">{{ emptyText() }}</div>
    </template>

    <!-- 统一的「故障详情」(字段 + 变更记录)。
         Sprint 不往这里传:详情组件自己从页面 provide 的下钻上下文里取(见 useSprintScope)。 -->
    <BugInstanceDetailDialog
      v-model:visible="detailVisible"
      source="RDM"
      :issue-key="detailKey"
    />
  </Dialog>
</template>
