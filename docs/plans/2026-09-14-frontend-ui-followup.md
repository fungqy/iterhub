# 前端 UI 后续整改（样式统一整改续篇）

**Goal:** 修掉 `2026-09-12-frontend-style-overhaul.md` 落地后**仍然残留**的缺陷与口径分裂。上一轮把「地基」做干净了（三层样式体系、token、`.ds-*` 组件类、Tailwind 4），本轮不再动地基，只做**收尾、口径统一、体验与可访问性补课**。

**Architecture:** 沿用既有三层结构，新增一个「常量/工具单一源」薄层：
- `src/constants/taskMeta.ts` —— 任务类型与执行状态的**唯一**标签/配色映射
- `src/utils/datetime.ts` —— 时间格式化的**唯一**实现
- `src/utils/notify.ts` —— Toast 的**唯一**入口（composable）
- 删除与上述重复的本地实现，消灭「同名不同值」

**Tech Stack:** Vue 3 + TypeScript + Vite 5 + PrimeVue 4.5.5 + Tailwind 4.3.3 + Sass + ECharts 5

**基线日期:** 2026-09-14

**前置关系:** 本计划是 `2026-09-12-frontend-style-overhaul.md` 的续篇。该计划 Task 0–14 已落地（Task 14 类名前缀统一未做，保留为独立决策），本计划**不重复**其已完成项，只处理其未覆盖的部分。

---

## 一、现状复核（量化基线）

### 1.1 上一轮成果确认（已达标，勿重做）

| 指标 | 09-12 基线 | 2026-09-14 实测 | 结论 |
| --- | --- | --- | --- |
| 含 `<style>` 块的 `.vue` | 2 / 21 | **0 / 21** | ✅ 达标 |
| `:deep()` 使用 | 1 处 | **0 处** | ✅ 达标 |
| `!important` | 多处 | **0 处** | ✅ 达标 |
| `.vue` 内硬编码 hex | 30 + 24 | **1 处**（`BurndownDialog.vue:49` 的 `rgba(0,0,0,0)` 渐变透明端） | ✅ 达标 |
| 弹窗宽度档位 | 7 种魔法数字 | **4 档 token** | ✅ 达标 |
| `.bak` 死文件 | 2 个 | **0 个** | ✅ 达标 |
| 版本控制 | 无 git | **已 init**（4 commits） | ✅ 达标 |

**结论：地基合格。** 本轮问题不在「脏」，而在「收尾没做完 + 口径没统一 + 体验没补课」。

### 1.2 本轮待处理项（实测）

| 类别 | 数量 | 代表位置 |
| --- | --- | --- |
| 页面可见缺陷（P0） | 5 | `index.html:5`、`MetricsTrendChart.vue:109`、`router/index.ts` |
| 跨页口径分裂（P1） | 4 组 | `Dashboard.vue:34-51` vs `jobsConstants.ts` |
| Element Plus 迁移残留 | 6 处 | `vite.config.ts:56`、`jobsConstants.ts:38-45`、`router/index.ts:21-51` |
| 可访问性缺口 | 18 label + 全站 1 处 `aria-*` | `MainLayout.vue:84-88` 等 |
| 页面级体验 | 6 项 | `ProjectList.vue:67-75`、`Reports.vue:317` |

---

## 二、任务分解

### Task 1：任务类型 / 状态口径单一源（最高杠杆，零视觉变化）

**问题：** `Dashboard.vue:34-51` 自建了一套 `taskTypeMap` / `taskSeverityMap` / `statusMap`，与 `jobs/components/jobsConstants.ts` **重复且不一致**：

| 概念 | Dashboard.vue | jobsConstants.ts | 后果 |
| --- | --- | --- | --- |
| `pending` | 「待执行」 | 「等待中」 | 同一状态两个名字 |
| `running` | **缺** | 「执行中」 | 露出英文原值 `running` |
| `sonar_reminder` | **缺** | 「Sonar扫描」 | 露出英文原值 `sonar_reminder` |
| `report_data` 标签 | 「报表数据」 | 「报表数据」 | ✅ 一致 |
| sonar 命名 | 列头「Sonar」 | 「Sonar扫描」 | 页面内第三次叫法 |

**Files:**
- Create: `frontend/src/constants/taskMeta.ts`
- Modify: `frontend/src/views/dashboard/Dashboard.vue:34-51`（删除本地 map，改 import）
- Modify: `frontend/src/views/jobs/components/jobsConstants.ts`（保留 `formatDateTime` 相关之外的导出，改为 re-export `taskMeta`）
- Modify: `frontend/src/views/jobs/components/ExecutionLogTable.vue:4`
- Modify: `frontend/src/views/jobs/components/ManualExecutePanel.vue:15-20`
- Modify: `frontend/src/views/projects/ProjectList.vue:77-82`（`reminderTags` 的 label 对齐）

**Step 1:** 新建 `src/constants/taskMeta.ts`，定义**唯一**口径：

```ts
// 任务类型/状态的唯一标签与配色映射。所有页面从这里取,禁止各自再定义。
export type TagSeverity = 'info' | 'success' | 'warn' | 'contrast'

export const TASK_TYPE_LABELS: Record<string, string> = {
  story_reminder: '进度提醒',
  task_reminder: '任务提醒',
  sonar_reminder: '代码扫描',   // 统一叫法,对齐主导航「代码扫描」
  report_data: '报表数据',
}

export const TASK_TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'story_reminder', label: '进度提醒' },
  { value: 'task_reminder', label: '任务提醒' },
  { value: 'sonar_reminder', label: '代码扫描' },
  { value: 'report_data', label: '报表数据' },
]

export const TASK_TYPE_SEVERITY: Record<string, TagSeverity> = {
  story_reminder: 'info',
  task_reminder: 'success',
  sonar_reminder: 'warn',
  report_data: 'contrast',
}

export const TASK_STATUS: Record<string, { text: string; severity: TagSeverity | 'danger' | 'secondary' }> = {
  running: { text: '执行中', severity: 'info' },
  pending: { text: '待执行', severity: 'warn' },      // 统一为「待执行」
  success: { text: '成功', severity: 'success' },
  failed:  { text: '失败', severity: 'danger' },
  expired: { text: '已过期', severity: 'secondary' },
}

export const EXEC_TYPE_LABELS: Record<string, string> = {
  automatic: '自动',
  manual: '手动',
}
```

**Step 2:** 全站替换。用 `?? 'secondary'` 与 `|| raw` 兜底**保留**（防后端新增枚举时白屏），但兜底不应再被触发。

**Step 3:** 命名决策（需业主确认，见 §四.3）：
- 任务类型统一「**代码扫描**」（原 `Sonar扫描`）
- 提醒开关仍叫「**扫描提醒**」（它是"提醒"而非"任务类型"，概念不同，保留区分）
- Dashboard 列头「Sonar」→「**扫描提醒**」

**验收:**
```bash
cd frontend
# 口径 map 在全项目只应有一处定义
grep -rn "taskTypeMap\|taskSeverityMap" src/ | grep -v "constants/taskMeta.ts"   # 零命中
grep -rn "'待执行'\|'等待中'" src/                                                # 只出现在 taskMeta.ts
npm run build
```
浏览器验证 Dashboard「今日任务」表：`running` 状态显示「执行中」、sonar 任务显示「代码扫描」，无英文原值外露。

---

### Task 2：时间格式化单一源

**问题：** 存在 **3 份**实现且输出不同：

| 位置 | 行为 | 输出 |
| --- | --- | --- |
| `jobsConstants.ts:58` | `toLocaleString` 全量 | `2026/09/14 10:25:37` |
| `Dashboard.vue:60` | 手写 options，**无年份** | `09/14 10:25` |
| `DocBugImport.vue:207` | 字符串替换 + 截断 | `2026-09-14 10:25:37` |

**Files:**
- Create: `frontend/src/utils/datetime.ts`
- Modify: `frontend/src/views/jobs/components/jobsConstants.ts:58-68`
- Modify: `frontend/src/views/dashboard/Dashboard.vue:60-63`
- Modify: `frontend/src/views/screen/DocBugImport.vue:207-210`
- Modify: `frontend/src/views/jobs/components/ExecutionLogTable.vue:4,132,135`

**Step 1:** 新建 `src/utils/datetime.ts`：

```ts
// 时间格式化唯一实现。禁止各页面再写 toLocaleString/切片。
const pad = (n: number) => String(n).padStart(2, '0')

/** 完整时间:2026-09-14 10:25:37 — 用于日志表格等需要精确的历史记录 */
export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 短时间:09-14 10:25 — 仅用于「当日」语境(如工作台今日任务),年份冗余 */
export function formatDateTimeShort(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 纯日期:2026-09-14 */
export function formatDate(value: string | Date | null): string {
  if (!value) return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
```

**Step 2:** 统一分隔符为 `-`（现 `jobsConstants` 走的 `toLocaleString('zh-CN')` 实际产出 `/`，与另两处的 `-` 不一致，**这是跨页可见的差异**）。

**Step 3:** `DocBugImport.vue` 的 `formatTime` 原本处理的是后端返回的 `2026-09-14T10:25:37` 这类 **ISO 串且可能带时区**，直接换成 `formatDateTime` 前需确认后端字段格式（若为不带时区的本地时间串，`new Date()` 解析在 Safari 上有兼容坑，需按 `T` 拆分再组装）。**这是本任务唯一的风险点。**

**验收:**
```bash
grep -rn "toLocaleString\|function formatTime\|function formatDateTime" src/ | grep -v "utils/datetime.ts"  # 零命中
npm run build
```
日志页与工作台两处时间格式肉眼可辨一致（均为 `-` 分隔）。

---

### Task 3：Toast 助手收敛为 composable

**问题：** 全项目 **7 处**重复定义 `notify`，且 severity 联合类型各不相同；`src/utils/appToast.ts` 已存在却**无人使用**。

| 文件 | severity 联合类型 |
| --- | --- |
| `Login.vue:22` | `success \| warn \| error` |
| `ProjectList.vue:25` | `success \| warn \| error` |
| `DocBugImport.vue:21` | `success \| warn \| error` |
| `ManualExecuteDialog.vue:18` | `success \| info \| warn \| error` |
| `AvgTimeDevelopersDialog.vue:13` | `warn \| error` |
| `Reports.vue:17` / `BugDetailDialog.vue:13` | `notifyError` 专用 |

**Files:**
- Create: `frontend/src/utils/notify.ts`
- Modify: 上述 7 个文件
- Keep: `frontend/src/utils/appToast.ts`（非组件模块专用，**不要删**）

**Step 1:** 新建 composable（组件内使用的正统做法，避免依赖"全局实例已注入"这一隐式前提）：

```ts
// 组件内统一 Toast 入口。非组件模块请继续用 utils/appToast.ts 的 notify()。
import { useToast } from 'primevue/usetoast'
import { type NotifySeverity } from './appToast'

export function useNotify() {
  const toast = useToast()
  return (severity: NotifySeverity, detail: string, summary = '提示', life = 3000) =>
    toast.add({ severity, summary, detail, life })
}
```

**Step 2:** 7 处替换为 `const notify = useNotify()`，删除本地函数定义。`notifyError` 变体替换为 `notify('error', detail)`。

**Step 3:** 保留各页调用点的 `life` 差异（`ManualExecuteDialog` 的轮询常驻提示用 `group` + 长 `life`，不走本 composable 的默认 3 秒）。

**验收:**
```bash
grep -rn "function notify\|function notifyError" src/   # 零命中
grep -rn "useNotify" src/ | wc -l                        # ≥ 7
npm run build
```

---

### Task 4：清理 Element Plus 迁移残留

**问题：** 技术栈已全量迁至 PrimeVue，但 Element Plus 时代的产物没清干净。

**Files:**
- Modify: `README.md:9`
- Modify: `frontend/package.json`（移除死依赖）
- Modify: `frontend/vite.config.ts:56`（移除死 chunk）
- Modify: `frontend/src/views/jobs/components/jobsConstants.ts:38-45,50-56`
- Modify: `frontend/src/router/index.ts:21,27,33,39,45,51`
- Modify: `frontend/src/components/layout/MainLayout.vue:18-25`

**Step 1（文档漂移）:** `README.md:9` 技术栈行：
```diff
-| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia |
+| 前端 | Vue 3 + TypeScript + Vite + PrimeVue 4 + Tailwind 4 + ECharts 5 + Pinia |
```

**Step 2（死依赖 + 空 chunk）:** `@iconify/vue`、`@iconify-json/lucide` 全项目 **0 引用**，却在 `vite.config.ts:56` 配了 `icons: ["@iconify/vue"]` —— 产出的是一个**空 chunk**（build 时 Rollup 会警告）。执行：
```bash
cd frontend
npm uninstall @iconify/vue
npm uninstall -D @iconify-json/lucide
```
并删除 `vite.config.ts:56` 的 `icons: [...]` 一行。图标全站统一用 `primeicons`（`pi pi-*`）。

**Step 3（死字段）:**
- `jobsConstants.ts:38-45` 的 `manualButtons[].icon` 存的是 **lucide 名**（`notebook-1`/`checkbox`/`monitor`/`data-line`），实际被 `ManualExecutePanel.vue:15-20` 自己的 `pi pi-*` map 完全覆盖。→ 删除 `icon` 字段与 `ManualButton` 接口中的该字段。
- `jobsConstants.ts:50` 的 `statusMap` 残留 `cls` / `type` 两个**无人读取**的字段（Task 1 后该 map 整体迁走，本步自然完成）。

**Step 4（导航双份定义）:** 目前导航定义了两处——
- `router/index.ts:21-51` 的 `meta.icon`：`Odometer`/`FolderOpened`/`Timer`/`Monitor`/`DataAnalysis`/`FullScreen` 全是 **Element Plus 图标名**，且**无人读取**（`meta.title` 被 `MainLayout.vue:16` 用于页头，`meta.icon` 是死的）。
- `MainLayout.vue:18-25` 的 `menuItems`：硬编码 PrimeIcons 名。

→ **让路由成为导航的唯一源**，`MainLayout` 改为派生：

```ts
// MainLayout.vue
const menuItems = computed(() =>
  router.getRoutes()
    .filter(r => r.meta?.title && !r.meta?.hidden)
    .sort((a, b) => (a.meta.order as number) - (b.meta.order as number))
    .map(r => ({ path: r.path, label: r.meta.title as string, icon: r.meta.icon as string }))
)
```
同步把 `router/index.ts` 的 `meta.icon` 改为 PrimeIcons 类名（如 `'pi pi-th-large'`），并补 `meta.order`。`meta.hidden` 已存在于 `Login` 路由，复用即可。

**Step 5:** 移除 `router/index.ts` 中无用的 `meta.hidden` 之外的 Element Plus 痕迹，确认 `grep -rn "element-plus\|ElMessage" frontend/src/` 零命中。

**验收:**
```bash
cd frontend
grep -rn "element-plus\|ElMessage\|iconify" src/ vite.config.ts   # 零命中
ls node_modules/@iconify 2>/dev/null || echo "已卸载"
grep -n "Element Plus" ../README.md || echo "README 已修正"
npm run build   # 无「空 chunk」警告
```
侧边栏 6 个导航项图标、文案、顺序与改动前**完全一致**（这是本任务的回归重点）。

---

### Task 5：修复运行时缺陷（P0）

#### 5.1 favicon 404

**Files:** Modify `frontend/index.html:5`；Create `frontend/public/favicon.svg`

`index.html:5` 是 `<link rel="icon" type="image/svg+xml" href="/vite.svg" />`，但 `frontend/public/` **目录不存在**，`vite.svg` 也不存在 → 每次访问 favicon 都 404；且绝对路径 `/vite.svg` 忽略了 `VITE_BASE=/iterhub/`，生产环境必然错。

**Step 1:** 新建 `frontend/public/favicon.svg`（建议用品牌绿 `#aadb1e` 底 + 白色简笔图标的方形 SVG，16px 下可辨）。

**Step 2:** 改为跟随 base：
```html
<link rel="icon" type="image/svg+xml" href="%BASE_URL%favicon.svg" />
```

**验收:** `npm run build && cat dist/index.html`，确认产物中 href 为 `/iterhub/favicon.svg`（即 `%BASE_URL%` 已被 Vite 正确替换）。**若替换未生效**（Vite 版本差异），退化为在 `vite.config.ts` 用 `transformIndexHtml` 注入，不要硬编码 `/iterhub/`。浏览器 Network 面板不再出现 favicon 404。

#### 5.2 折叠侧栏后图表错位

**Files:** Modify `frontend/src/views/reports/components/MetricsTrendChart.vue:107-116`

`MetricsTrendChart.vue:109` 只监听 `window.addEventListener('resize')`。侧栏折叠是 `base.scss:36` 的 `transition: width 0.2s`，**只改容器宽度、不触发 window resize** → ECharts 保留旧宽度，图表与卡片错位。全项目目前 `ResizeObserver` **零使用**。

**Step 1:** 用 `ResizeObserver` 替换 window 监听：

```ts
let ro: ResizeObserver | null = null
let rafId = 0

onMounted(() => {
  render()
  if (chartRef.value) {
    ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() => chartInstance?.resize())
    })
    ro.observe(chartRef.value)
  }
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  ro?.disconnect()
  ro = null
  chartInstance?.dispose()
  chartInstance = null
})
```

`requestAnimationFrame` 合并抖动是必需的：`transition: width 0.2s` 期间 ResizeObserver 会连续触发约 12 次，不合并会反复重排导致卡顿。

**Step 2:** 顺带修同一个文件的**加载态叠罗汉**：`MetricsTrendChart.vue:146` 的 `chartRef` 容器在 `loading` 时依然占位，与 `:142` 的 spinner 上下堆叠。改为 `v-show="!loading"`（用 `v-show` 而非 `v-if`，否则容器被销毁会导致 `echarts.init` 拿不到 DOM）。

**验收:** 在 `/reports` 页折叠/展开侧栏，4 张图表即时跟随、无错位无残影；缩放浏览器窗口同样正常。

#### 5.3 缺少 404 兜底路由

**Files:** Modify `frontend/src/router/index.ts:53`；Create `frontend/src/views/NotFound.vue`

未知路径（如 `/typo`）当前渲染出「有侧栏、无内容」的空白壳——因为路由未匹配，但 `showLayout` 为 true。

**Step 1:** 新建极简 `NotFound.vue`：复用 `.ds-page` + `.ds-empty`，给「返回工作台」按钮。

**Step 2:** 在 `routes` 末尾追加：
```ts
{ path: '/:pathMatch(.*)*', name: 'NotFound',
  component: () => import('@/views/NotFound.vue'),
  meta: { title: '页面不存在', hidden: true } },
```
`hidden: true` 保证 **Task 4 Step 4** 的派生导航不会把它列进侧栏。

**验收:** 访问 `/iterhub/anything-typo`，显示 404 页而非空白；侧边栏 6 项数量不变。

#### 5.4 每次切页重复请求用户信息

**Files:** Modify `frontend/src/router/index.ts:62-84`

守卫里对**每一次**导航都调 `authApi.getCurrentUser()`，切页时多一次网络往返，观感变慢。

**Step 1:** 加短路——本地已有用户信息时跳过校验，仅在缺失或首次进入时拉取：
```ts
router.beforeEach(async (to, _from, next) => {
  const token = localStorage.getItem('token')
  if (to.path === '/login') return next()
  if (!token) return next('/login')

  const authStore = useAuthStore()
  if (authStore.user) return next()   // 已校验过,不再重复请求

  try {
    authStore.user = await authApi.getCurrentUser()
    next()
  } catch {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    next('/login')
  }
})
```

**Step 2:** 刷新页面时 `authStore.initFromStorage()`（`main.ts:71`）会从 localStorage 恢复 `user` → 首屏也省掉一次请求。**风险：** token 在服务端失效但本地仍存时，用户会看到"登录态"却所有接口 401。**必须**保留 `api` 的 401 拦截器（`src/api/index.ts`）作为最终兜底——**执行本步前请先确认该拦截器存在且会清 token 并跳登录**。

**验收:** DevTools Network 面板中连续切换 6 个页面，`getCurrentUser` 只出现 **1 次**；手工清空 localStorage 的 `user` 后能正确重拉。

---

### Task 6：Toast 位置冲突

**Files:** Modify `frontend/src/App.vue:19-22`

两个 `<Toast>` 都是 `position="top-center"`：`report-polling` 组在报表任务执行时会挂一条 **最长 5 分钟** 的常驻提示（`ManualExecuteDialog.vue:88-95`），此时任何普通 toast 都会**压在同一位置**。

**Step 1:** 把轮询组移到底部，避开主线阅读区：
```html
<Toast position="top-center" />
<Toast group="report-polling" position="bottom-right" />
```

**验收:** 触发一次「报表数据」手动执行，在常驻提示存在期间快速制造一个普通 toast（如搜索框回车触发查询失败），两者可见且互不遮挡。

---

### Task 7：页头与语义结构统一

**问题：** `.ds-page-head` 在 `components.scss:65-78` 定义了，但**只有 `ProjectList.vue:254` 使用**（6 个页面里的 1 个）；全站**没有 `<h1>`**（唯一标题是 `ProjectList.vue:256` 的 `<h2>`）。

**Files:**
- Modify: `frontend/src/assets/styles/components.scss:73`（选择器 `h2` → `h1`）
- Modify: `frontend/src/views/projects/ProjectList.vue:256`
- Modify: `frontend/src/views/dashboard/Dashboard.vue:110`
- Modify: `frontend/src/views/jobs/Jobs.vue:104`
- Modify: `frontend/src/views/reports/Reports.vue:298`
- Modify: `frontend/src/views/screen/Screen.vue:11`
- Modify: `frontend/src/views/sonar/Sonar.vue:6`

**Step 1:** `components.scss:73` 的选择器由 `.ds-page-head h2` 改为 `.ds-page-head h1`，字号/字重不变（保持视觉零变化）。

**Step 2:** 6 个页面统一补页头：
```html
<div class="ds-page-head">
  <div>
    <h1>工作台</h1>
    <p class="ds-meta">副标题(可选)</p>
  </div>
  <!-- 右侧操作区(可选) -->
</div>
```
各页 `<h1>` 文案直接取 `route.meta.title`，与侧栏/顶栏一致。

**Step 3:** 同一页面内 `<h1>` 只允许一个。`ProjectList.vue:373,403,425` 与 `BugDetailTable.vue:58` 的 `<h3>` 是弹窗内分区标题，**保持不变**。

**注意:** Dashboard 顶部已有一个日期胶囊（`Dashboard.vue:112`），加页头后需确认不与 `.ds-page` 的 `gap: 1.5rem` 产生过大间距——若过空，可把日期胶囊并入页头右侧。

**验收:** 6 个页面顶部均有统一标题区；`grep -rn "<h1" src/views/` 恰好 **6 处**（+NotFound）；键盘 `Tab` 到页面顶部时，读屏能播报页面标题。

---

### Task 8：可访问性收口（补 09-12 Task 13 未覆盖部分）

**问题：** 全站仅 **1** 处 `aria-*`（`MainLayout.vue:72` 的折叠按钮）；**18** 个 `<label>` 没有 `for`；用户菜单是 `div + click`。

**Files:**
- Modify: `frontend/src/views/auth/Login.vue:54,63`
- Modify: `frontend/src/views/projects/ProjectList.vue:376,380,384,388,392,396,406,410,414,418`
- Modify: `frontend/src/views/jobs/components/ExecutionLogTable.vue:77,87,97`
- Modify: `frontend/src/views/jobs/components/ManualExecuteDialog.vue:232,245`
- Modify: `frontend/src/views/screen/DocBugImport.vue:234,252`
- Modify: `frontend/src/views/reports/Reports.vue:302`
- Modify: `frontend/src/components/layout/MainLayout.vue:84-88`

**Step 1（label 关联）:** 18 处 `<label class="ds-meta">` 补 `for` + 对应控件补 `id`。`Login.vue:54,63` 已是正确范例（`for="login-username"` + `id="login-username"`），**照抄这个模式**。命名建议 `pl-<字段名>`（ProjectList）、`job-<字段名>`、`import-<字段名>`，避免同页 id 冲突。

**Step 2（用户菜单可键盘操作）:** `MainLayout.vue:84-88` 的 `<Avatar @click>` 渲染为 `div`，键盘完全无法触发。改为带语义的按钮：

```html
<Button text rounded :aria-label="`用户菜单:${authStore.user?.username}`"
        aria-haspopup="menu" :aria-expanded="menuOpen" @click="toggleUserMenu">
  <Avatar :label="authStore.user?.username?.charAt(0)?.toUpperCase()" shape="circle" />
</Button>
```
补 `menuOpen` 状态与 `Menu` 的 `@hide`/`@show` 同步（`aria-expanded` 不能是死值）。同时给 `Menu` 的 `userMenuItems` 项保留 `label`（已具备）。

**Step 3（装饰性图标）:** 侧栏 `<i :class="item.icon">`（`MainLayout.vue:63`）等纯装饰图标补 `aria-hidden="true"`，避免读屏把 PrimeIcons 的伪内容念出来。**只加在装饰图标上**，纯图标按钮（如折叠按钮）反而**必须有** `aria-label`（已有）。

**Step 4:** 保留 `components.scss:43-46` 已有的 `:focus-visible` 焦点环，不要删。

**验收:**
```bash
cd frontend
grep -rn "<label" src/ | grep -v "for=" | wc -l    # 期望 0
```
- 键盘 `Tab` 可完成：登录 → 切页 → 表格翻页 → 打开/关闭弹窗 → **打开用户菜单并登出**
- 浏览器 `axe DevTools` 扫描 6 个页面，「form label」类错误归零

---

### Task 9：修正图表配色「单一源」的假象

**问题：** `tokens.scss:29-34` 声明了 6 个 `--ih-chart-*`，注释称「数值须与 `chartPalette.ts` 保持一致」。实测这 6 个 token **被任何 CSS 规则消费的次数为 0**——只出现在注释里。而真正被 ECharts 读取的 `chartPalette.ts` 中，`axisLabel: '#666666'`、`tooltipText: '#FFFFFF'`、`pieBorder: '#F7F6F3'` **在 tokens 里根本没有对应项**，且 `pieBorder` 与 `--ih-paper: #f9f8f8` 并不相等。

**结论：** 所谓「双源同步」是单向的假承诺，已经产生漂移。正确做法不是「补全 token」，而是**承认 TS 是唯一源**（09-12 计划 R3 已明确「ECharts 读不到 CSS 变量」）。

**Files:**
- Modify: `frontend/src/assets/styles/tokens.scss:3,28-34`
- Modify: `frontend/src/views/reports/components/chartPalette.ts:1-13`

**Step 1:** 删除 `tokens.scss:29-34` 的 6 个 `--ih-chart-*` 声明，并把 `:3` 的注释改为：
```scss
// 图表 canvas 色不在本文件定义:ECharts 读不到 CSS 变量(见 09-12 计划 R3)。
// 唯一源是 views/reports/components/chartPalette.ts。
```

**Step 2:** `chartPalette.ts:2` 的注释同步改为「本项目图表配色的**唯一源**」，并加一行说明「新增图表色只改本文件，不要去 tokens.scss 找对应项」。

**Step 3:** 核对 `pieBorder: '#F7F6F3'`（`chartPalette.ts:12`）的实际用途（饼图描边）。若其本意是与页面暖纸底融为一体，应改为与 `--ih-paper` 一致的 `#f9f8f8`；若是有意的视觉区分，**保留并在注释里写明理由**。这是唯一的语义决策点。

**验收:**
```bash
cd frontend
grep -rn "ih-chart" src/    # 仅剩注释,无 token 声明
npm run build && npm run dev
```
`/reports` 4 张图表 + 弹窗内饼图配色与改动前**逐像素一致**（本任务只删死代码，不改渲染结果）。

---

### Task 10：页面级体验打磨

#### 10.1 ProjectList 时间选择：144 项下拉 → 时间输入

**Files:** Modify `frontend/src/views/projects/ProjectList.vue:67-75,430-462`

`timeOptions`（`ProjectList.vue:67-75`）生成 `00:00`~`23:50` 共 **144** 项，用户要在长列表里滚半天。三处 `Select`（`:433,445,457`）都受影响。

**Step 1:** 改用 PrimeVue `DatePicker` 的 `timeOnly` 模式（`hourFormat="24"`、`:stepMinute="10"`），或 `InputMask`（`mask="99:99"`）+ 提交前校验。**推荐 `InputMask`**：144 项下拉换成两个数字输入，交互成本最低，且不引入 DatePicker 的日历语义。

**Step 2:** 顺带修**布局跳动**：`:431,:443,:455` 的 `Select` 用 `v-if` 挂在开关上，开/关时整行高度突变。改为固定槽位 + `:disabled`（或 `v-show`），让三行高度恒定。

**Step 3:** 补**必填校验**：开关打开但未选时间时应拦截。目前 `handleSave`（`:187-191`）只校验 `board_id`/`project_id`。

**验收:** 三个提醒时间均可用键盘直接键入 `09:30`；开/关开关时行高不跳；开关开而时间为空时保存被拦截并提示。

#### 10.2 Reports 时间轴横向溢出

**Files:** Modify `frontend/src/views/reports/Reports.vue:315-328`

`Timeline` 用 `layout="horizontal"`（`:319`）渲染**项目全部已激活 Sprint**（`:284-290` 未做数量限制）。Sprint 多时横向溢出卡片，且无滚动容器。

**Step 1:** 给容器加横向滚动：外层 `<div class="overflow-x-auto">`，内层设 `min-width` 随点位数量增长（如每点 140px）。**仅此一步即可解决溢出**，且保留"看全历史"的信息价值。

**Step 2（可选）:** 默认只显示最近 12 个 Sprint + 「展开全部」。需先与业主确认是否需要（历史 Sprint 是这批用户的核心信息吗？）。

**Step 3:** `Reports.vue:325` 的时间轴文案直接显示后端 `state` 英文原值（如 `closed`/`active`）。补一张 `SPRINT_STATE` 映射表（复用 **Task 1** 的 `taskMeta.ts` 或就地定义）译为「已关闭/进行中」。

**验收:** 选一个有 15+ Sprint 的项目，时间轴可横向滚动、不撑破卡片；状态显示中文。

#### 10.3 加载骨架屏

**Files:** Modify `frontend/src/views/dashboard/Dashboard.vue:131,173`；新增骨架块

全项目 `Skeleton` **零使用**，加载全靠 DataTable 的 `loading` 遮罩，首屏是"空表格闪一下再出数据"。

**Step 1:** 引入 PrimeVue `Skeleton`，为 Dashboard 两张表在 `loading && data.length === 0` 时渲染 3~4 行占位（**仅首次加载**；翻页等已有数据的场景继续用 DataTable 的 `loading` 遮罩，避免骨架闪烁）。

**Step 2:** 同理用于 `<Card>` 的统计卡区域——数字从 `0` 跳到真实值会闪，改为加载时显示短横线占位。

**验收:** 用 DevTools 把网络限速到 Slow 3G，Dashboard 首屏出现骨架而非空白抖动。

#### 10.4 Dashboard 统计卡视觉收敛

**Files:** Modify `frontend/src/assets/styles/components.scss:142-182`；`frontend/src/views/dashboard/Dashboard.vue:116-121`

**问题：** 4 张高饱和渐变卡（蓝/琥珀/绿/红，`tokens.scss:52-55`）与全站「暖纸底 `#f9f8f8` + 白卡 + 发丝线」的克制语言冲突；且**失败数为 0 时红卡依然在喊**，视觉警报失效。

**Step 1:** 值与 0 时降级为中性态——`value === 0` 时改用 `.ds-stat.tone-zero`（白底 + 发丝线 + 墨字 + 左侧 4px 状态色条），把"彩色"留给**非零**的真信号。这样 4 张卡的视觉权重会跟着数据走，而不是固定喊叫。

**Step 2:** 把 `Dashboard.vue:112` 日期胶囊的任意值 `text-[0.8125rem]`（绕过 token 的字号）改为 `.ds-meta`，与其他次要文字一致。

**注意：** 这是**视觉意图变更**，需业主确认（见 §四.3）。若业主坚持保留渐变卡，则至少执行 Step 1 的零值降级——那条与审美无关，是信息设计问题。

**验收:** 无任务时，4 张卡呈中性色；有失败任务时红卡恢复高亮。日期胶囊字号与 `.ds-meta` 一致。

---

### Task 11（可选，独立提交）：暗色模式

**问题：** `tokens.scss` 的 `--ih-*` 全部定义在 `:root`（`tokens.scss:4`），**没有 `.dark` 覆盖**；而 PrimeVue 侧（`main.ts:44-47`）本身支持暗色。结果是「一半能暗、一半不能」。

**Files:** Modify `frontend/src/assets/styles/tokens.scss`；`frontend/src/components/layout/MainLayout.vue`（切换入口）；`frontend/src/assets/styles/base.scss`（`.app-content` 的 `--p-surface-50`）

**Step 1:** 决策先行——**先问「谁需要暗色」**。内部迭代看板的用户多为白天办公场景，如果答案是"没人需要"，**本任务应当被删掉**，而不是"顺便做一下"。这是唯一一个"不做也是正确决策"的任务。

**Step 2:** 若要做，把 `tokens.scss` 的 `:root` 改写为 `:root`（亮）+ `:root.dark`（暗）两套，颜色/线/字全部给出暗色对应值；`:root.dark` 用同一组变量名覆盖。

**Step 3:** 同步 PrimeVue：`main.ts` 的 `theme.options.darkModeSelector` 需与 `tokens.scss` 的暗色类名**一致**（默认 `system`，建议改 `.dark` 手动可控）。

**Step 4:** 补切换入口 + 持久化到 localStorage。

**验收:** 切换后 6 个页面无"白底白字"或"黑底黑字"；`chartPalette.ts` 的图表色需**单独评估**（`tooltipBg: '#1A1A2E'` 在暗色下会糊成一片）——**这是本任务最大的隐藏成本，务必先估**。

---

## 三、执行顺序总览

```
Task 1  口径单一源（任务类型/状态）      ← 零视觉变化,杠杆最高,先做
  ↓
Task 2  时间格式化单一源                ← 同上
  ↓
Task 3  Toast 助手收敛                  ← 同上
  ↓   ↑ 三者为纯重构:不碰视觉,但消灭一半"不一致"观感
Task 5  修复运行时缺陷（P0）            ← 用户必然撞上,收益最直观
  ↓
Task 4  清理迁移残留 / 死代码 / 导航单源  ← 依赖 Task 1(否则 map 搬两遍)
  ↓
Task 6  Toast 位置冲突
  ↓
Task 7  页头与语义结构统一
  ↓
Task 8  可访问性收口
  ↓
Task 9  图表配色单一源真相修正
  ↓
Task 10 页面级体验打磨（4 个子项,可拆开提交）
  ↓
Task 11（可选）暗色模式                 ← 先决策"要不要",再谈"怎么做"
```

**每个 Task 完成后必须做：**
1. `npm run build` 通过（`vue-tsc` 无类型错误）
2. 该页面与基线截图对照
3. 独立 git commit

**Task 1–3 建议合并为一次提交**（同一主题：口径收敛），**Task 10 拆 4 次**（互不依赖）。

---

## 四、验收标准

### 4.1 量化目标

| 指标 | 现状 | 目标 |
| --- | --- | --- |
| 重复的 `notify` 定义 | 7 处 | **0 处** |
| 重复的时间格式化实现 | 3 处 | **0 处** |
| 重复的任务状态/类型 map | 2 套 | **1 套** |
| 无 `for` 的 `<label>` | 18 处 | **0 处** |
| 全站 `aria-*` 数量 | 1 处 | **≥ 12 处**（label/菜单/图标按钮/装饰图标） |
| 页面级 `<h1>` | 0 个 | **6 个**（+ NotFound） |
| 控制台 favicon 404 | 每次访问 | **0** |
| 无匹配路由 | 空白壳 | **404 页** |
| 空 chunk（icons） | 1 个 | **0 个** |
| 未消费的 CSS token | 6 个 | **0 个** |
| 切页 `getCurrentUser` 调用 | 每次导航 1 次 | **每会话 1 次** |

### 4.2 人工验收清单

- [ ] 折叠/展开侧栏，`/reports` 4 张图表即时跟随，无错位
- [ ] 访问不存在的路径，显示 404 页而非空白壳
- [ ] favicon 正常显示，Network 无 404
- [ ] 「今日任务」表无任何英文原值（`running`/`sonar_reminder` 等）
- [ ] 同一状态名在 Dashboard 与任务调度页**逐字一致**
- [ ] 键盘可完成：登录 → 切页 → 翻页 → 开/关弹窗 → 打开用户菜单并登出
- [ ] 6 个页面在 375 / 768 / 1280 / 1920 四档宽度下无横向溢出
- [ ] `axe DevTools` 在 6 个页面无「form label」类错误
- [ ] 侧边栏 6 项图标/文案/顺序与改动前完全一致（Task 4 回归重点）
- [ ] 图表配色与改动前逐像素一致（Task 9 只删死代码）
- [ ] `npm run build` 通过，无 `vue-tsc` 错误、无 Rollup 空 chunk 警告

### 4.3 需业主决策项（不是回归，是选择）

1. **sonar 统一叫法** —— 建议任务类型用「代码扫描」、提醒开关用「扫描提醒」，Dashboard 列头改「扫描提醒」（Task 1 Step 3）
2. **`pending` 中文** —— 建议统一为「待执行」（原 Dashboard 用词），`jobsConstants` 的「等待中」废弃（Task 1）
3. **时间分隔符** —— 建议统一 `-`（现 `jobsConstants` 走 `toLocaleString` 产出 `/`）（Task 2）
4. **Dashboard 统计卡** —— 是否接受「零值降级为中性卡」（Task 10.4）。建议接受，这关乎**警报有效性**而非审美
5. **暗色模式** —— 先决策"要不要"（Task 11）
6. **Task 14（09-12 遗留）** —— `ds-` 前缀是否改 `ih-`，仍待决
7. **`pieBorder` 取值** —— `#F7F6F3` 是否对齐 `--ih-paper` 的 `#f9f8f8`（Task 9 Step 3）

---

## 五、风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| Task 1 改状态文案被误认为"功能变更" | 用户以为改了逻辑 | 提交信息写明「仅改展示文案,不改任何状态判定」 |
| Task 2 的 `DocBugImport.formatTime` 处理 ISO 串 | Safari 下 `new Date()` 解析失败 | 先确认后端字段格式；不带时区则按 `T` 拆分组装（§Task 2 Step 3） |
| Task 4 卸载 `@iconify` 时误删在用依赖 | 构建失败 | 先 `grep -rn "iconify" src/` 确认零命中再卸；卸后立即 `npm run build` |
| Task 4 导航改为路由派生后顺序错乱 | 侧栏顺序与现在不同 | 补 `meta.order` 并**显式对照改前顺序**（这是回归重点） |
| Task 5.4 短路校验后 token 失效未拦截 | 登录态假象 + 全接口 401 | 执行前**必须先确认** `api/index.ts` 的 401 拦截器存在且会清 token 跳登录 |
| Task 5.1 `%BASE_URL%` 占位符不生效 | 生产 favicon 仍 404 | 构建后 `cat dist/index.html` 验证；不生效则改用 `transformIndexHtml`，**不要硬编码 `/iterhub/`** |
| Task 9 删 token 时误删仍被引用的变量 | 页面掉色 | 删前 `grep -rn "ih-chart" src/` 已确认仅注释引用（本轮已核实） |
| Task 10.1 时间控件换成 InputMask | 提交值格式与后端不符 | 保持输出 `HH:mm` 字符串不变（与现 `Select` 的 value 同构），仅换交互 |
| Task 11 暗色模式改动面失控 | 图表色在暗色下不可读 | 先决策"要不要"；要做则先单独评估 `chartPalette.ts` 的暗色映射 |
| 无自动化测试 | 重构无回归网 | 每 Task 独立 commit + 基线截图对照；Task 1–3 属纯重构，可用"diff 只含 import/删除"自证 |
