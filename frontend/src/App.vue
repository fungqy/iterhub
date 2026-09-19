<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import Toast from 'primevue/toast'
import ConfirmDialog from 'primevue/confirmdialog'
import MainLayout from '@/components/layout/MainLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { setAppToast } from '@/utils/appToast'

const route = useRoute()
const authStore = useAuthStore()
const showLayout = computed(() => authStore.token && route.path !== '/login')

// 注入全局 Toast 实例,供非组件模块(api 拦截器等)发通知
setAppToast(useToast())
</script>

<template>
  <Toast position="top-center" />
  <!-- 报表轮询提示是常驻的(最长 5 分钟),与普通提示同为 top-center 会互相叠压 -->
  <Toast group="report-polling" position="bottom-right" />
  <ConfirmDialog />
  <MainLayout v-if="showLayout" />
  <router-view v-else />
</template>
