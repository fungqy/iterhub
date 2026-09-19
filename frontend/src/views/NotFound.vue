<script setup lang="ts">
import { useRouter } from 'vue-router'
import Button from 'primevue/button'

// 兜底路由页面。此前未匹配的路径会渲染出「有侧栏、无内容」的空白壳,
// 用户无法判断是页面坏了还是地址错了。
const router = useRouter()
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>页面不存在</h1>
        <p class="ds-meta">该地址没有对应的页面</p>
      </div>
    </div>
    <div class="ds-card ds-empty">
      <p>请检查地址是否拼写正确,或返回工作台继续操作。</p>
      <Button label="返回工作台" icon="pi pi-home" @click="router.push('/dashboard')" />
    </div>
  </div>
</template>
