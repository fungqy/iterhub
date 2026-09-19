<script setup lang="ts">
import Message from 'primevue/message'
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>代码扫描</h1>
      </div>
    </div>
    <div class="ds-card ds-empty">
      <Message severity="info" :closable="false">代码扫描模块正在规划中，敬请期待...</Message>
    </div>
  </div>
</template>
