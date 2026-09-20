<script setup lang="ts">
import { ref } from 'vue'
import Card from 'primevue/card'
import Button from 'primevue/button'
import DocBugImport from './DocBugImport.vue'
import DocTestcaseImport from './DocTestcaseImport.vue'

const showDocBugImport = ref(false)
const showDocTestcaseImport = ref(false)
</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>文档导入</h1>
      </div>
    </div>

    <Card class="ds-card">
      <template #content>
        <div class="flex flex-col gap-4 items-start">
          <Button label="故障导入" icon="pi pi-upload" @click="showDocBugImport = true" />
          <!-- 测试用例导入与故障导入并列:两者源头都是「文档」,但口径完全不同 ——
               故障的迭代归属在表内 sprint 列,用例的归属要用户自己选迭代。 -->
          <Button
            label="用例导入"
            icon="pi pi-list-check"
            @click="showDocTestcaseImport = true"
          />
        </div>
      </template>
    </Card>

    <DocBugImport
      :visible="showDocBugImport"
      @close="showDocBugImport = false"
    />

    <DocTestcaseImport
      :visible="showDocTestcaseImport"
      @close="showDocTestcaseImport = false"
    />
  </div>
</template>
