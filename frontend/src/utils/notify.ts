// 组件内统一 Toast 入口。
//
// 历史上 7 个组件各自写了一份 notify / notifyError,severity 联合类型还各不相同
// (有的只有 success|warn|error,有的多了 info),而 utils/appToast.ts 里其实早有
// 一份实现却无人使用。现在组件内一律用 useNotify()。
//
// 与 appToast.ts 的分工:
//   - 组件 setup 内           → useNotify()(本文件)
//   - 非组件模块(api 拦截器等) → appToast.ts 的 notify()
// 两者不要混用:appToast 依赖「全局实例已被注入」这一隐式前提,组件内没必要承担。
import { useToast } from 'primevue/usetoast'
import type { NotifySeverity } from './appToast'

export type { NotifySeverity }

export interface NotifyOptions {
  /** 标题,默认「提示」 */
  summary?: string
  /** 存活毫秒数,默认 3000 */
  life?: number
}

/**
 * 返回一个 notify 函数。必须在组件 setup 顶层的同步代码中调用。
 */
export function useNotify() {
  const toast = useToast()
  return (severity: NotifySeverity, detail: string, options: NotifyOptions = {}) =>
    toast.add({
      severity,
      summary: options.summary ?? '提示',
      detail,
      life: options.life ?? 3000,
    })
}
