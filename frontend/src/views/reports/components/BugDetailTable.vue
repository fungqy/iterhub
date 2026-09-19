<script setup lang="ts">
import { computed } from 'vue'
import type { BugDetailResponse } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import Row from 'primevue/row'

// 分布明细主表 + 合计行
// 合计行是 PrimeVue **组件自带**的列分组表尾(`<ColumnGroup type="footer">` + Row/Column +
// #footer 插槽),不是手写的 <tr> —— 列宽、合并、frozen 都由组件自己与表体对齐;
// 它的版式口径(内边距 / 上边线 / 字号字重)在 components.scss 的
// `.ds-table .p-datatable-tfoot` 一段里补齐(该行原先吃的是 Aura 默认值,与全表对不上)。
// 只负责展示与单元格点击上抛,数据加载由父组件( BugDetailDialog )负责
const props = defineProps<{
  detail: BugDetailResponse
}>()

const emit = defineEmits<{
  (e: 'cell-click', developer: string, priority: string, tag: string): void
  (e: 'row-click', developer: string): void
  (e: 'summary-click', priority: string, tag: string): void
  (e: 'summary-all-click'): void
}>()

function getCellCount(developer: string, priority: string, tag: string): number {
  const devData = props.detail.data[developer]
  if (!devData) return 0
  const priorityData = devData[priority]
  if (!priorityData) return 0
  return priorityData[tag] || 0
}

function getTableColumnTotal(priority: string, tag: string): number {
  let total = 0
  for (const dev of props.detail.developers) {
    total += getCellCount(dev.developer, priority, tag)
  }
  return total
}

const grandTotal = computed(() =>
  props.detail.developers.reduce((sum, d) => sum + d.total, 0),
)

// ── 列宽口径(用户 2026-09-17:「各数值列等宽铺满」)────────────────────
/** 「开发」列宽。原值 = 头像 2rem + 间距 0.75rem + 4 个中文字 ≈3.75rem + 左右内边距 1.5rem。
 *  2026-09-17 去掉姓名前的首字头像后**没有同步收窄**(用户只要求去图标) —— 要收紧改这一处即可，
 *  它同时是 numColWidth 里扣掉的那一份。 */
const DEV_COL_WIDTH = '8.5rem'
/** 数值列 / 「合计」列的下限宽 ≈ 两个字(3.5rem − 左右内边距 1.5rem = 2rem)。 */
const MIN_COL_WIDTH = '3.5rem'

/**
 * 数值列(优先级 × 标签 的矩阵格)宽度:把整表宽度扣掉「开发」「合计」两列后,
 * 在**所有数值列之间等分**。
 *
 * ⚠ 为什么必须动态算:列数是数据驱动的(优先级 × 标签),SCSS 里压根没有这个分母。
 * ⚠ 为什么每列都要写同一个值:auto 布局只认「各列自己的偏好宽度」,给得不一样
 *   (或只给一部分列)时,富余宽度会按各列 max-content 的比例分掉 —— 那正是上一版
 *   「有的列被撑肥、合计行被拉散」的成因(用户:很丑)。全表同值才真正等宽。
 * ⚠ `max(3.5rem, …)`:宽容器取等分值(每列 > 两字)铺满整表;算出来不足两字时回落到
 *   3.5rem,由 .p-datatable-table-container 的 overflow:auto 横向滚动兜底,
 *   而不是把表头压成逐字竖排。
 */
const numColWidth = computed(() => {
  const n = props.detail.priorities.length * props.detail.tags.length
  if (n === 0) return MIN_COL_WIDTH
  return `max(${MIN_COL_WIDTH}, calc((100% - ${DEV_COL_WIDTH} - ${MIN_COL_WIDTH}) / ${n}))`
})

function onCellClick(developer: string, priority: string, tag: string) {
  if (getCellCount(developer, priority, tag) > 0) {
    emit('cell-click', developer, priority, tag)
  }
}

function onSummaryCellClick(priority: string, tag: string) {
  if (getTableColumnTotal(priority, tag) > 0) {
    emit('summary-click', priority, tag)
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <h3 class="ds-section-title">分布明细</h3>
    <DataTable
      :value="detail.developers"
      class="ds-table ds-table--matrix ds-table--center"
    >
      <template #empty>暂无数据</template>
      <!-- ── 列宽与纵向分隔线(用户 2026-09-17)──
           这张表**列数是数据驱动的**(优先级 × 标签),历史上被几轮反向诉求拉扯过:
             · 早先:容器 ≤1024px 时 13 个表头被榨成 2 行(合计 / 代码实现 / 环境问题 / 其他,
               宽度只剩 46~72px)。根因是 `table-layout:auto` + 中文 min-content 只有一个字宽,
               富余空间全给了「开发」等宽列;当时的修法是短列表头 nowrap。
             · 其后:表头第二行**超过两个字就换行**,用折行把列压到两个字宽(与 nowrap 相反,
               故第二行**撤掉 nowrap**),并顺带把整张表设成不吃满容器宽 + 居中。
             · 现在(用户要求「分布明细表格铺满可用区域」):**撤销上一条** ——
               表体回到 width:100%(见 components.scss 的 .ds-table--matrix),整表居中随之取消。
               但**不能靠把列撑肥来铺满**(用户:那样很丑),故各数值列改为绑定同一个计算宽度
               `numColWidth` ⇒ 富余宽度在数值列之间**等分**,整块是宽窄一致的规整网格。
           ⚠ 等宽的前提是**每列同值**:auto 布局只认各列自己的偏好宽度,给得不一致(或只给
             一部分列)时,富余宽度就按各列 max-content 的比例分掉 —— 上一版「有的列肥、
             合计行被拉散」正是这么来的。表头第二行与表体两处必须绑同一个值。
           ⚠ 撤掉 nowrap 不会退回「逐字竖排」:竖排的成因是列被 auto 布局**压到** 1 字宽,
             而不是缺少 nowrap。`numColWidth` 用 `max(3.5rem, …)` 兜住两字下限:
             宽容器取等分值、容器窄到不足两字时回落 3.5rem 并交给容器横向滚动。
           ⚠ 3.5rem 的取法:内容盒 = 3.5rem − 左右内边距 0.75rem×2 = 2rem = 2 个字宽。
             它现在是**列宽下限**(也是「合计」列宽),改内边距/字号仍要重核这个值。
           ⚠ 「表头/表体内容居中」(用户 2026-09-17)走 .ds-table--center 变体:
           它管 thead/tbody/tfoot 的 text-align,并额外把表头那层 flex 的 justify-content 居中
           (只写 text-align 折不中表头,原因见 components.scss 该段)。
           「开发」那一格原先另包了一层 flex(头像 + 名字)、靠 justify-center 居中;
           2026-09-17 去掉头像后它已是纯文本,td 的 text-align 直接生效,那层 flex 随之撤掉。
           ⚠ 该变体原先还兼「整张表居中」一职(靠 .ds-table--matrix 的 margin-inline:auto),
             已随满宽一并取消,现在只剩「单元格内容居中」这一层含义。
           ⚠ 第一行的优先级组头(致命/严重/一般/轻微/优化,均为 2 字)保持 ds-nowrap:
             它们横跨整组,宽度是下面若干列之和,本来就够宽,折行只会白白抬高表头。
           ⚠ 「开发」列 8.5rem(用户更早的一条要求):
             原推导 = 头像 2rem + 间距 0.75rem + 4 个中文字 ≈3.75rem + 左右内边距 1.5rem;
             2026-09-17 去掉首字头像后没有同步收窄(用户只要求去图标),口径见 DEV_COL_WIDTH。
             它是**首选宽度**而非硬上限:auto 布局下最小内容宽仍是地板 —— 人名更长时这一列
             会略微变宽,而不是把名字压到溢出(这也是它配 ds-nowrap 的原因:
             让超长人名走「列变宽」,而不是「折成两行、行高翻倍」)。
             表头组里那个 Column 与表体那个是**两个实例**,宽度两边各写了一次。

           纵向分隔线不在模板里画,而是按 class 由 components.scss 的 .ds-table--matrix 统一出线:
             · 列与列之间:发丝线(--ih-line-soft);
             · 每个优先级组的**起始列** + 末列「合计」:再压深一档(--ih-line),
               让「开发 │ 组 │ 组 │ 合计」这层结构显出来。
           ⚠ 组起始列由 `ti === 0`(每个优先级下的第一个标签)判定,且**四处必须一致**:
             表头第一行、表头第二行、表体、合计行 —— 少一处就会出现「上半段有线、下半段没有」
             的断头线,比不画更难看。 -->
      <ColumnGroup type="header">
        <Row>
          <Column :header="TH.developer" :rowspan="2" frozen class="ds-nowrap" :style="{ width: DEV_COL_WIDTH }" />
          <Column
            v-for="priority in detail.priorities"
            :key="priority"
            :header="priority"
            :colspan="detail.tags.length"
            class="ds-nowrap ds-col-sep"
          />
          <!-- 「合计」列宽与数值列下限同口径(两个字),不写死在上面的 colspan 里 -->
          <Column
            :header="TH.total"
            :rowspan="2"
            frozen
            alignFrozen="right"
            class="ds-nowrap ds-col-sep"
            :style="{ width: MIN_COL_WIDTH }"
          />
        </Row>
        <Row>
          <!-- 第二行:标签名,可折行(见上方注释)。宽度 = 数值列的**等分值**(numColWidth),
               全表同值才会等宽 —— 只给一部分列就是上一版那种胖瘦不均。 -->
          <template v-for="priority in detail.priorities" :key="priority">
            <Column
              v-for="(tag, ti) in detail.tags"
              :key="priority + '-' + tag"
              :header="tag"
              :class="ti === 0 ? 'ds-col-sep' : null"
              :style="{ width: numColWidth }"
            />
          </template>
        </Row>
      </ColumnGroup>

      <!-- 宽度与表头那个 Column 同步写（两个实例，见上方注释） -->
      <Column field="developer" frozen class="ds-nowrap" :style="{ width: DEV_COL_WIDTH }">
        <template #body="{ data }">
          <!-- 纯文本，居中由 .ds-table--center 的 text-align 直接生效。
               2026-09-17 用户要求去掉姓名前的首字头像(Avatar)：原先那层 flex + justify-center
               是为「头像 + 名字」两件东西服务的，头像去掉后一并撤掉。不要再套回 div ——
               套了 td 的 text-align 就不作用在这行文字上，得再补 justify-center 才居中。 -->
          {{ data.developer }}
        </template>
      </Column>

      <template v-for="priority in detail.priorities" :key="'body-' + priority">
        <Column
          v-for="(tag, ti) in detail.tags"
          :key="'body-' + priority + '-' + tag"
          :class="ti === 0 ? 'ds-col-sep' : null"
          :style="{ width: numColWidth }"
        >
          <template #body="{ data }">
            <!-- 没有数据的格子**留空**，不画破折号（用户 2026-09-17）：
                 优先级 × 标签 的笛卡尔积里绝大多数格子是 0，满屏「—」只是要读者逐格忽略的
                 噪声，而这张表要回答的是「哪一格有故障」—— 0 不携带这个信息。
                 ⚠ 空值也**不渲染 button**：一个看不见的按钮既是无效命中目标，
                   又会让读屏念出「查看 X / Y / Z 的故障明细」却什么都点不开。
                 （onCellClick 里的 `> 0` 判定保留：它与这里的条件同源，
                   防止将来模板改动后出现「看着可点却点不动」。） -->
            <button
              v-if="getCellCount(data.developer, priority, tag) > 0"
              type="button"
              class="ds-cell-button"
              :aria-label="`查看 ${data.developer} / ${priority} / ${tag} 的故障明细`"
              @click="onCellClick(data.developer, priority, tag)"
            >
              {{ getCellCount(data.developer, priority, tag) }}
            </button>
          </template>
        </Column>
      </template>

      <Column frozen alignFrozen="right" class="ds-col-sep">
        <template #body="{ data }">
          <button
            type="button"
            class="ds-cell-button"
            :aria-label="`查看 ${data.developer} 的全部故障明细`"
            @click="emit('row-click', data.developer)"
          >
            {{ data.total }}
          </button>
        </template>
      </Column>

      <ColumnGroup type="footer">
        <Row>
          <Column :footer="TH.total" frozen />
          <template v-for="priority in detail.priorities" :key="'foot-' + priority">
            <Column
              v-for="(tag, ti) in detail.tags"
              :key="'foot-' + priority + '-' + tag"
              :class="ti === 0 ? 'ds-col-sep' : null"
            >
              <template #footer>
                <!-- 空值留空、不渲染 button —— 口径与表体完全一致(见上方 body 那段注释)。
                     合计 0 与表体 0 是同一件事(该列全员都没有故障),两处画法不该分叉。 -->
                <button
                  v-if="getTableColumnTotal(priority, tag) > 0"
                  type="button"
                  class="ds-cell-button"
                  :aria-label="`查看 ${priority} / ${tag} 合计的故障明细`"
                  @click="onSummaryCellClick(priority, tag)"
                >
                  {{ getTableColumnTotal(priority, tag) }}
                </button>
              </template>
            </Column>
          </template>
          <Column frozen alignFrozen="right" class="ds-col-sep">
            <template #footer>
              <button
                type="button"
                class="ds-cell-button"
                aria-label="查看全部故障明细"
                @click="emit('summary-all-click')"
              >
                {{ grandTotal }}
              </button>
            </template>
          </Column>
        </Row>
      </ColumnGroup>
    </DataTable>
  </div>
</template>
