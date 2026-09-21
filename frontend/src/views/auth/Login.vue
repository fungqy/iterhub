<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Card from 'primevue/card'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Button from 'primevue/button'
import { useNotify } from '@/utils/notify'

const notify = useNotify()
const router = useRouter()
const authStore = useAuthStore()

const loginForm = ref({
  username: '',
  password: '',
})
const loading = ref(false)

async function handleLogin() {
  if (loading.value) return // 防重复提交(回车会同时触发 keyup.enter 与 form submit)
  if (!loginForm.value.username || !loginForm.value.password) {
    notify('warn', '请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    await authStore.login(loginForm.value.username, loginForm.value.password)
    notify('success', '登录成功')
    router.push('/dashboard')
  } catch (error) {
    notify('error', '登录失败，请检查用户名和密码')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="center-page">
    <Card class="ds-card w-[min(420px,92vw)]">
      <template #title>Sprint Better</template>
      <template #subtitle></template>
      <template #content>
        <form class="flex flex-col gap-4" @submit.prevent="handleLogin">
          <div class="flex flex-col gap-2">
            <label for="login-username" class="ds-meta">用户名</label>
            <InputText
              id="login-username"
              v-model="loginForm.username"
              placeholder="请输入用户名"
              fluid
            />
          </div>
          <div class="flex flex-col gap-2">
            <label for="login-password" class="ds-meta">密码</label>
            <Password
              id="login-password"
              v-model="loginForm.password"
              placeholder="请输入密码"
              :feedback="false"
              toggle-mask
              fluid
            />
          </div>
          <Button
            type="submit"
            label="登 录"
            :loading="loading"
            class="w-full"
          />
        </form>
      </template>
    </Card>
  </div>
</template>
