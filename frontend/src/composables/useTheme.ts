// 主题(亮/暗)唯一入口。
//
// 三处必须保持一致,任何一处改了名字都会失效:
//   1. 本文件给 documentElement 加的类名 —— 默认 'dark'
//   2. main.ts 里 PrimeVue 的 theme.options.darkModeSelector —— 同为 '.dark'
//   3. tokens.scss 里的 :root.dark 覆盖块
//
// 状态放在模块级而非 ref 内部,使所有组件共享同一份 isDark(单例),
// 避免每个调用方各持一份、切换后互不同步。
import { ref, readonly } from 'vue'

const STORAGE_KEY = 'iterhub-theme'
const DARK_CLASS = 'dark'

/** 模块级单例:全应用共享 */
const isDark = ref(false)

function apply(dark: boolean) {
  const root = document.documentElement
  root.classList.toggle(DARK_CLASS, dark)
  // 让滚动条、原生表单控件等浏览器 UI 跟随主题
  root.style.colorScheme = dark ? 'dark' : 'light'
}

/**
 * 应用启动时调用一次(main.ts)。优先级:
 * 用户显式选择(localStorage) > 系统偏好 > 亮色
 */
export function initTheme() {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'dark' || stored === 'light') {
    isDark.value = stored === 'dark'
  } else {
    isDark.value = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  }
  apply(isDark.value)
}

export function setTheme(dark: boolean) {
  isDark.value = dark
  localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light')
  apply(dark)
}

export function toggleTheme() {
  setTheme(!isDark.value)
}

export function useTheme() {
  return {
    isDark: readonly(isDark),
    setTheme,
    toggleTheme,
  }
}
