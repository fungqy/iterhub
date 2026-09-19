<script setup lang="ts">
import { computed } from 'vue'

// 指标卡标签后的「解释」问号:悬停或键盘聚焦时,由 PrimeVue Tooltip 指令弹出一个
// 对该卡片数据的说明。整卡本身可能可点击下钻,因此解释用独立的「?」图标承载,
// 既不干扰卡片点击,也比「整卡悬停弹 tooltip」更克制、更可发现。
//
// 位置优先取顶部(.top 修饰符);PrimeVue Tooltip 的 fitContent 默认开启,
// 顶部行卡片空间不足时会自动翻转到下方,不会被弹窗裁掉。
// maxWidth 放宽到 20rem 以容纳中文多行说明;文案里的 \n 会被 .p-tooltip-text 的
// `white-space: pre-line` 渲染成换行(无需 HTML)。
const props = defineProps<{
  /** 解释说明文本,可含 \n 换行 */
  help: string
}>()

const tip = computed(() => ({
  value: props.help,
  dt: { maxWidth: '20rem' },
}))
</script>

<template>
  <span
    class="ds-metric-help"
    v-tooltip.top="tip"
    tabindex="0"
    role="img"
    :aria-label="help"
    @click.stop
  ><i class="pi pi-question" aria-hidden="true"></i></span>
</template>
