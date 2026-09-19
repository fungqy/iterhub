import type { ToastServiceMethods } from 'primevue/toastservice'

// PrimeVue Toast 需在组件 setup 内 useToast() 获取,
// 非组件模块(api 拦截器等)通过这里持有的全局实例发通知。
// 由 App.vue 挂载时 setAppToast() 注入。
let appToast: ToastServiceMethods | undefined

export function setAppToast(instance: ToastServiceMethods) {
  appToast = instance
}

export type NotifySeverity = 'success' | 'info' | 'warn' | 'error'

export function notify(severity: NotifySeverity, detail: string, summary = '提示') {
  appToast?.add({ severity, summary, detail, life: 3000 })
}
