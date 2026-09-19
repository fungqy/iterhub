# 前端样式统一整改

**Goal:** 把迭代看板前端从「21 个页面 5 套设计语言混用、19 个页面裸 div 无样式」整改为「一层设计 token + 一套组件类 + Tailwind 4 布局原语」的可维护体系。

**Architecture:** 三层结构 —— ① `tokens.scss` 定义 `--ih-*` 设计 token；② `components.scss` 用 token 实现 `.ds-*` 组件类（卡片/表格/页壳/弹窗/空态/统计卡）；③ 页面只用 Tailwind 工具类做布局，不再写 `<style scoped>`。

**Tech Stack:** Vue 3 + TypeScript + Vite 5 + PrimeVue 4.5.5 + Tailwind 4.3.3 + Sass

**基线日期:** 2026-09-12

---

## 一、现状诊断

### 1.1 量化基线

| 指标 | 现状 |
| --- | --- |
| `.vue` 文件总数 | 21 |
| 含 `<style>` 块 | 2（9.5%）—— Dashboard.vue、ProjectList.vue |
| `<style>` 总行数 | 200 行（含标签） |
| `lang="scss"` 的 style 块 | 0（Sass 已装且已配置，但没人用） |
| 全项目 class 属性总数 | 47 |
| class 属性为 0 的文件 | **19 / 21** |
| 页面内 `var(--p-*)` 使用 | **0 处**（全部 13 处在 layout.scss 里） |
| `.vue` 内硬编码 hex | 30 处 + charts.ts 24 处 |
| `.vue` 内硬编码 rgba() | 17 处 |
| 内联 `style=` / `:style=` | 13 处，散落 11 个文件 |
| PrimeVue 内部 `.p-*` 覆写 | 7 处，全在全局 layout.scss |
| `:deep()` 使用 | 1 处（ProjectList.vue:510） |
| Tailwind 工具类 | **0**（依赖已声明，从未接入） |
| git 仓库 | **无** |

### 1.2 并存的设计语言（5 套）

1. **PrimeVue Aura 默认 + 品牌绿 preset**（`main.ts:18-34`）—— 21 个文件中 15 个的唯一样式来源，即"完全没管"的兜底态。
2. **应用壳结构 SCSS**（`layout.scss:4-114`）—— `.app-*` 用于 MainLayout，`.center-page` 用于 Login。附带一条隐式规则 `.app-content > div`（`layout.scss:101-105`）给每个页面根 div 套 `flex column + gap 1rem`，是全站唯一的"页面布局"，且靠 `>` 子选择器链式生效，极度脆弱。
3. **DeepSeek 官网风 `ds-*`**（`layout.scss:116-170`）—— 暖纸底 `#f9f8f8` + 墨字 `#1e232c` + 发丝线 `rgba(9,45,78,0.12)` + 16/20px 大圆角。**仅** Dashboard.vue 和 ProjectList.vue 使用，且两者各自又在 `<style scoped>` 里重复抄了同一套调色板。
4. **裸 div 惯用法**（0 class）—— 16 个文件：Jobs、ExecutionLogTable、ManualExecuteDialog、ManualExecutePanel、Reports、BugDetailDialog、AvgTimeDevelopersDialog、BugChartCard、BugDetailTable、BugListDialog、BurndownDialog、MetricsTrendChart、ReportReopenDialog、DocBugImport、Screen、Sonar、App。**这是"丑"的主因**：没有栅格、没有间距、没有留白，元素纯靠浏览器默认块级流自上而下堆叠。
5. **ECharts TS 侧调色板**—— 18 处 hex 写在 Reports.vue，24 处写在 `charts.ts`，3 个图表组件各写一份 tooltip 配色（`#1A1A2E` 底 / `#fff` 字 / `#666` 轴）。CSS 里完全看不到这些颜色。

### 1.3 具体病灶

**P1 — 页面无布局，元素堆叠。**
`Jobs.vue:104-129` 的模板里留着注释「Main Layout: Left (main content) + Right (manual execute)」「Left Column」「Right Column」，但**对应的 CSS 一行都不存在**。实际渲染是两个 div 上下摞着。`Reports.vue`（408 行、4 张图表 + 时间轴）全部 class 为 0，同样只有全局 `.app-content > div` 那一条 flex-gap 生效。

**P2 — PrimeVue 基础字号被整体放大 12.5%。**
`index.scss:6` 设 `html { font-size: 18px }`。PrimeVue Aura 全部尺寸按 16px 基准设计，这里全局拉到 18px 后所有组件的 padding、字号、行高同步膨胀 12.5%，观感松散。

**P3 — 表格风格自相矛盾。**
`layout.scss:140-164` 的 `.ds-table` 设计意图是「无底色表头 + 发丝线 + 无斑马纹」，但实际调用点：Dashboard 两处写 `stripedRows`、ProjectList 一处写 `stripedRows`，其余 6 处 DataTable 还额外开 `showGridlines`（DocBugImport.vue:268、BugDetailTable、BugListDialog、ReportReopenDialog、AvgTimeDevelopersDialog、ExecutionLogTable）。斑马纹 + 网格线 + 发丝线三者叠加。

**P4 — 弹窗宽度失控。**
11 个文件里 13 处内联尺寸，全是魔法数字：`500px`(ManualExecuteDialog:223)、`760px`(ProjectList:367)、`900px`(DocBugImport:223)、`1100px`(BurndownDialog:128)、`min(1300px, 95vw)`(BugListDialog:35)、`95vw`(BugDetailDialog:184 等 4 处)、`70vw`(AvgTimeDevelopersDialog:127)。无尺度、无规律。

**P5 — 品牌绿 #aadb1e 对比度不足，不能做文字色。**
`#aadb1e` 对白底对比度约 **1.6:1**（WCAG AA 正文要求 4.5:1，大字要求 3:1）。它只能用于填充/背景/图标块。任何把 `primary-500` 当文字色的地方都不可读。

**P6 — 死代码与残留物。**
- `src/views/reports/Reports.vue.bak` —— 1470 行 / 42KB，`import { ElMessage } from 'element-plus'`，Element Plus 时代遗留，路由未引用。
- `frontend/.npmrc.bak`。
- `package.json:23` 的 `tailwindcss` 声明了却从未接入（无 `@tailwindcss/vite` 插件、无 postcss 配置、无 `@import "tailwindcss"`、构建产物 0 命中）。

**P7 — 无版本控制。**
`frontend/` 及整个 `iterhub/` 都不是 git 仓库。整改要动 21 个文件，没有回滚手段。**这是 Task 0，必须先做。**

---

## 二、目标架构

### 2.1 三层结构

```
┌─ 第 1 层：设计 token ─────────────────────────────┐
│ src/assets/styles/tokens.scss                     │
│   --ih-paper / --ih-ink / --ih-line / --ih-accent │
│   --ih-status-{info,success,warn,danger}          │
│   --ih-radius-{sm,md,lg,pill}                     │
│   --ih-dialog-{sm,md,lg,xl}                       │
│ 同时把品牌绿写进 PrimeVue preset，让 --p-primary-* │
│ 与 --ih-* 同源                                     │
└───────────────────────────────────────────────────┘
                       ↓ 被引用
┌─ 第 2 层：组件类（全局，非 scoped）────────────────┐
│ src/assets/styles/components.scss                 │
│   .ds-page  页面壳（暖纸底 + 大圆角 + 内边距）      │
│   .ds-card  卡片（白底 + 发丝线 + 16px 圆角）       │
│   .ds-table 表格（无斑马纹 · 无网格 · 发丝线）      │
│   .ds-toolbar 顶栏                                 │
│   .ds-stat  统计卡（含 4 种 tone）                  │
│   .ds-dialog 弹窗尺寸档位                           │
│   .ds-empty 空态                                   │
│ PrimeVue 内部覆写只允许出现在本文件，一处一份        │
└───────────────────────────────────────────────────┘
                       ↓ 被使用
┌─ 第 3 层：页面布局 ────────────────────────────────┐
│ Tailwind 4 工具类，页面零 <style scoped>            │
│   <div class="grid grid-cols-[1fr_320px] gap-4">   │
└───────────────────────────────────────────────────┘
```

### 2.2 Token 映射表

从现有 `ds-*` 实现中提取，不发明新色：

| Token | 值 | 来源 |
| --- | --- | --- |
| `--ih-paper` | `#f9f8f8` | layout.scss:120 暖纸底 |
| `--ih-surface` | `#ffffff` | layout.scss:125 |
| `--ih-ink` | `#1e232c` | layout.scss:146 墨字 |
| `--ih-ink-strong` | `#0f0f0f` | layout.scss:137 |
| `--ih-ink-muted` | `rgba(30, 35, 44, 0.6)` | ProjectList.vue:485 |
| `--ih-ink-faint` | `rgba(30, 35, 44, 0.4)` | ProjectList.vue:561 |
| `--ih-line` | `rgba(9, 45, 78, 0.12)` | layout.scss:126 发丝边 |
| `--ih-line-soft` | `rgba(9, 45, 78, 0.07)` | layout.scss:154 |
| `--ih-accent` | `#4d6bfe` | Dashboard.vue:242 |
| `--ih-brand` | `#aadb1e` | main.ts:26 品牌绿（仅填充） |
| `--ih-brand-text` | `#415a0b` | main.ts:31 primary-900（文字用） |
| `--ih-status-info` | `#0284c7` | ProjectList.vue:538 |
| `--ih-status-success` | `#16a34a` | ProjectList.vue:542 |
| `--ih-status-warn` | `#d97706` | ProjectList.vue:546 |
| `--ih-status-danger` | `#dc2626` | Dashboard.vue:284 |
| `--ih-chart-1..4` | `#6366F1` `#F97316` `#EC4899` `#14B8A6` | Reports.vue:96-171 |
| `--ih-chart-tooltip-bg` | `#1A1A2E` | MetricsTrendChart.vue:57 |
| `--ih-radius-sm` | `8px` | |
| `--ih-radius-md` | `16px` | layout.scss:127 |
| `--ih-radius-lg` | `20px` | layout.scss:120 |
| `--ih-radius-pill` | `999px` | Dashboard.vue:235 |

弹窗尺寸档位（替换 13 处魔法数字）：

| 档位 | 值 | 用例 |
| --- | --- | --- |
| `--ih-dialog-sm` | `min(500px, 95vw)` | ManualExecuteDialog、ConfirmDialog 类 |
| `--ih-dialog-md` | `min(760px, 95vw)` | ProjectList 编辑、DocBugImport(900 并入) |
| `--ih-dialog-lg` | `min(1100px, 95vw)` | BurndownDialog |
| `--ih-dialog-xl` | `min(1360px, 95vw)` | BugDetailDialog、BugListDialog |

### 2.3 命名说明

- Token 前缀用 **`--ih-*`**（IterHub，产品名），不跟 `ds-` 走 —— token 属于产品，不属于某次视觉参考。
- 组件类**保留 `ds-*` 前缀**（已在 2 个文件落地、有代码引用），避免 21 个文件的无谓重命名。语义上把它理解为"设计系统类"，前缀无需自解释。
- 若希望彻底统一，可在全部整改完成后追加一次 `ds-` → `ih-` 的机械重命名（可选，见 Task 14）。

---

## 三、约束与风险

### R1 — Tailwind 4 的 preflight 会打垮 PrimeVue

Tailwind 4 的 `preflight` 会重置 `button`、`input`、`table` 的默认样式，与 PrimeVue 的组件样式直接冲突。

**对策：不引入 preflight。** Tailwind 4.3.3 已安装且入口已拆分（`node_modules/tailwindcss/{theme,preflight,utilities}.css`），按需只引 theme + utilities：

```css
/* src/assets/styles/tailwind.css */
@layer theme, primevue, ds, utilities;

@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);
```

跳过 `preflight.css`，PrimeVue 的原生视觉不受干扰，同时 `flex/gap-4/grid` 等布局工具类照常可用。布局类不依赖 preflight，这是安全的。

### R2 — PrimeVue 自身也占 CSS layer，顺序必须固定

PrimeVue 4.5.5 的 theme API 支持 `cssLayer`（已在 `node_modules/primevue/umd/primevue.min.js` 中确认该选项存在），需在 `main.ts` 显式声明层级名，与 `tailwind.css` 的 `@layer` 声明顺序对齐，否则 utilities 可能被 PrimeVue 覆盖。实现时按下述形式落地，并以实际构建产物验证（Task 2 的验收项）：

```ts
app.use(PrimeVue, {
  theme: {
    preset: IterhubPreset,
    options: { cssLayer: { name: 'primevue', order: 'theme, primevue, ds, utilities' } },
  },
});
```

### R3 — ECharts 读不到 CSS 变量

ECharts 的 `color` / `lineStyle.color` 接收的是真实色值，`var(--ih-chart-1)` 这类字符串在 canvas 渲染路径下不生效。

**对策：图表色单独放 TS 常量，不放 CSS。** 新建 `src/views/reports/components/chartPalette.ts`，导出与 `--ih-chart-*` 数值一致的常量，ECharts 侧统一从这里取。CSS 变量负责 DOM，TS 常量负责 canvas，两者数值在 Task 12 里对齐并加注释互指。

### R4 — 全局 `html { font-size: 18px }` 的连锁反应

改回 16px 会让**所有** rem 尺寸（含现有 200 行 scoped 样式和 layout.scss）同步缩小 11%。这不是副作用，正是目标；但必须和 Task 1 的基线截图逐页对照，确认没有布局塌陷。

### R5 — 无版本控制

Task 0 必须先完成，否则整改不可回滚。

---

## 四、任务分解

> **执行顺序原则：** 先地基后页面，先简单页后复杂页。`Dashboard.vue` 与 `ProjectList.vue` 是唯一的正确参照物，放**最后**回归，避免参照物被污染。

---

### Task 0：建立安全网（必做前置）

**Files:**
- Create: `frontend/.gitignore`（若 `iterhub/` 根已有，确认含 `node_modules/`、`dist/`、`.env*`、`logs/`）

**Step 1:** 在仓库根初始化版本控制
```bash
cd /home/nie/workspace/40-projects/iterhub
git init
git add -A
git commit -m "chore: 前端样式整改前的基线快照"
```

**Step 2:** 记录基线视觉证据。启动 dev server，对 6 个路由各截一张全页图存档：`/login` `/dashboard` `/projects` `/jobs` `/reports` `/screen` `/sonar`。整改每一步后对照。

**Step 3:** 确认基线可构建
```bash
cd frontend && npm run build
```
必须通过（`vue-tsc` 无错），否则先修构建再看样式。

**验收：** `git log` 有一条基线提交；7 张基线截图存档；`npm run build` 退出码 0。

---

### Task 1：拆分样式文件结构

现在 `index.scss` 与 `layout.scss` 职责混乱 —— 应用壳、DS 组件类、页面级类全挤在 `layout.scss` 一个文件里。

**Files:**
- Create: `frontend/src/assets/styles/tokens.scss`
- Create: `frontend/src/assets/styles/base.scss`
- Create: `frontend/src/assets/styles/components.scss`
- Create: `frontend/src/assets/styles/tailwind.css`
- Modify: `frontend/src/assets/styles/index.scss`
- Delete: `frontend/src/assets/styles/layout.scss`（内容迁走后删除）
- Modify: `frontend/src/main.ts:9,12`

**Step 1:** 建 `tokens.scss`，按 §2.2 映射表定义全部 `--ih-*` 变量，写在 `:root` 下。每个变量加一行注释标明来源（如 `/* 暖纸底，源自 layout.scss:120 */`）。

**Step 2:** 建 `base.scss`，迁入 `index.scss` 的 html/body/#app 规则 + `layout.scss:4-114` 的应用壳 `.app-*` 与 `.center-page`。

同时把 `html { font-size: 18px }` 改为 `16px`（对应病灶 P2），并在文件顶部写明原因。

**Step 3:** 建 `components.scss`，从 `layout.scss:116-170` 迁入 `.ds-*` 全部规则，并把其中硬编码色值替换为 `var(--ih-*)`：
- `#f9f8f8` → `var(--ih-paper)`
- `#fff` → `var(--ih-surface)`
- `#1e232c` → `var(--ih-ink)`
- `#0f0f0f` → `var(--ih-ink-strong)`
- `rgba(9, 45, 78, 0.12)` → `var(--ih-line)`
- `rgba(9, 45, 78, 0.07)` → `var(--ih-line-soft)`
- `rgba(30, 35, 44, 0.5)` → `var(--ih-ink-muted)`
- 圆角数值 → `var(--ih-radius-*)`

**Step 4:** 删除 `.app-content > div` 规则（`layout.scss:101-105`）。这条隐式子选择器是"页面看起来有布局"的假象来源，Task 3 起由页面显式声明布局取代。

**Step 5:** `main.ts` 的样式导入改为：
```ts
import "primeicons/primeicons.css";
import "./assets/styles/tailwind.css";
import "./assets/styles/tokens.scss";
import "./assets/styles/base.scss";
import "./assets/styles/components.scss";
```
顺序即优先级：token 先定义，base 次之，组件类再次，Tailwind utilities 层次在 `@layer` 里已声明。

**Step 6:** 同步更新 `main.ts:18-34` 的 `IterhubPreset`：把品牌绿改成引用集中常量（或在注释里标注与 `tokens.scss` 的 `--ih-brand` 必须保持一致），并加上 `cssLayer` 选项（见 R2）。

**验收：** `npm run build` 通过；Dashboard 与 ProjectList 视觉**与基线截图逐像素一致**（此步只搬文件不改视觉，唯一例外是 P2 的 18px→16px，此差异需单独确认并记录）。

---

### Task 2：接入 Tailwind 4

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/assets/styles/tailwind.css`（Task 1 已建）

**Step 1:** 安装插件
```bash
cd frontend && npm i -D @tailwindcss/vite
```

**Step 2:** `vite.config.ts` 的 `plugins` 数组加入 `tailwindcss()`（`@tailwindcss/vite`），置于 `vue()` 之后。

**Step 3:** `tailwind.css` 按 R1 落地 `@layer` 声明 + theme/utilities 双入口导入，**不引 preflight**。

**Step 4:** 在 `@theme` 里把 `--ih-*` 暴露为 Tailwind 主题值，使工具类可直接使用语义色：
```css
@theme {
  --color-paper: var(--ih-paper);
  --color-ink: var(--ih-ink);
  --color-line: var(--ih-line);
  --radius-card: var(--ih-radius-md);
}
```

**Step 5:** 冒烟验证 —— 在 `Sonar.vue`（9 行的占位页，改动风险最低）随便加一个 `class="flex gap-4 p-6"`，确认三个工具类都生效且 PrimeVue 的 `Message` 组件外观无变化。

**验收：** 构建通过；`dist/assets/*.css` 中出现工具类；PrimeVue 组件无视觉回退（与基线对照）；`Sonar.vue` 的冒烟类已移除。

---

### Task 3：补齐组件类

现在 `components.scss` 只有 `.ds-page` / `.ds-card` / `.ds-table` 三个类，覆盖不了 21 个页面的需求。

**Files:**
- Modify: `frontend/src/assets/styles/components.scss`

**Step 1:** 补齐以下类（全部用 token，不写死值）：

| 类 | 职责 | 关键规则 |
| --- | --- | --- |
| `.ds-page` | 页面壳 | `background: var(--ih-paper)`；`border-radius: var(--ih-radius-lg)`；`padding: 2rem`；`display:flex; flex-direction:column; gap:1.5rem` |
| `.ds-card` | 卡片 | 白底 + `1px var(--ih-line)` + `var(--ih-radius-md)`；覆写 `.p-card-body` padding / `.p-card-title` 字号字重 |
| `.ds-table` | 表格 | 无斑马纹；无网格线；表头小字大写 + `--ih-ink-muted` + 透明底 + 发丝线；行 hover `--ih-paper`；末行去边 |
| `.ds-toolbar` | 顶栏 | 迁入现有 `.app-header.p-toolbar` 规则，改名对齐 DS |
| `.ds-stat` | 统计卡 | 含 `.tone-{total,pending,success,failed}` 四种渐变；渐变色值改用 `--ih-*`（新增 4 组渐变 token，见 Step 2） |
| `.ds-dialog` | 弹窗尺寸 | 四档：`.ds-dialog-sm/md/lg/xl` 映射 §2.2 尺寸表 |
| `.ds-empty` | 空态 | 居中 + 图标 + 主副文案 + 可选操作按钮的竖排布局 |
| `.ds-page-head` | 页头 | 标题 + 副标题 + 右侧操作的 flex 两端对齐（取代 ProjectList 的 `.proj-head`） |
| `.ds-tag-dot` | 状态点 | 8px 圆点 + `.tone-*` 变体（取代 ProjectList 的 `.rem-dot`） |

**Step 2:** 在 `tokens.scss` 补 4 组统计卡渐变 token（源自 `Dashboard.vue:272,276,280,284`）：
```
--ih-grad-total:   linear-gradient(135deg, #4d6bfe 0%, #7a90ff 100%)
--ih-grad-pending: linear-gradient(135deg, #b45309 0%, #d97706 100%)
--ih-grad-success: linear-gradient(135deg, #16a34a 0%, #22c55e 100%)
--ih-grad-failed:  linear-gradient(135deg, #dc2626 0%, #f25a5a 100%)
```

**Step 3:** PrimeVue 内部覆写集中到本文件顶部一个 `/* ── PrimeVue 内部覆写（唯一允许位置）── */` 区块，并加注释说明「`.p-*` 覆写只允许出现在这里，页面文件禁止」。

**Step 4:** 在 `vite.config.ts` 的 scss 配置上确认无需改动（`api: "modern-compiler"` 已就位）。`components.scss` 用 `@use "./tokens.scss" as *;` 引入 token（若 token 已在 `:root` 定义则页面直接用 `var()`，无需 `@use`；优先后者，更简单）。

**验收：** `npm run build` 通过；文件中无任何硬编码 hex/rgba；`grep -E "#[0-9a-fA-F]{3,6}|rgba?\(" components.scss` 零命中（除注释）。

---

### Task 4：清除死代码

**Files:**
- Delete: `frontend/src/views/reports/Reports.vue.bak`
- Delete: `frontend/.npmrc.bak`

**Step 1:** 确认 `Reports.vue.bak` 无任何引用：
```bash
cd frontend && grep -rn "Reports.vue.bak\|\.bak" src/ vite.config.ts index.html
```
零命中才可删。

**Step 2:** 删除两个文件。

**Step 3:** 确认 `package.json` 无其他死依赖。`tailwindcss` 在 Task 2 已转正；检查 `echarts`/`sass`/`primeicons` 均有实际引用（是）。

**验收：** `npm run build` 通过；仓库内 `find . -name "*.bak"` 零结果。

---

### Task 5：Login 页

最小页面，用来校准 DS 语言在表单场景下的表现。

**Files:**
- Modify: `frontend/src/views/auth/Login.vue`

**Step 1:** 移除 `Card` 上的内联 `style="width: min(420px, 92vw)"`（:48），改用 Tailwind `class="w-[min(420px,92vw)]"`。

**Step 2:** 表单字段改为明确的布局：
```html
<form class="flex flex-col gap-4" @submit.prevent="handleLogin">
  <div class="flex flex-col gap-2">
    <label for="login-username" class="ds-meta">用户名</label>
    <InputText ... />
  </div>
```

**Step 3:** 登录按钮 `class="w-full"`，与表单等宽。

**Step 4:** 卡片套 `ds-card` 类，页面容器保留 `center-page`（此页是 `App.vue` 里 `showLayout=false` 分支渲染，无 `.app-content`，不需要 `ds-page` 壳）。

**Step 5:** 视觉确认：对比度检查 —— label 用 `--ih-ink-muted`（对白底约 4.8:1，达标）；按钮保持 PrimeVue 默认（primary 填充 + 白字，白字对 `#aadb1e` 同样只有 1.6:1，**需在 Task 13 统一处理**，此处先记录）。

**验收：** 登录流程功能不变；无内联 style；页面在 375px 宽下不溢出。

---

### Task 6：Screen 与 Sonar 占位页

**Files:**
- Modify: `frontend/src/views/screen/Screen.vue`
- Modify: `frontend/src/views/sonar/Sonar.vue`

**Step 1:** 两页的根 div 加 `class="ds-page"`。

**Step 2:** `Screen.vue` 的 `Card` 加 `ds-card` 类；内容区文案套 `ds-meta`；按钮与文案间距用 `class="flex flex-col gap-4 items-start"`。

**Step 3:** `Sonar.vue` 的 `Message` 已在 `ds-page` 内，居中即可：`class="ds-page"` + 内部 `class="flex items-center justify-center min-h-[200px]"`。占位页不必过度设计，但必须与全站底色一致。

**验收：** 两页视觉与其他页同底同边距；无内联 style。

---

### Task 7：Jobs 页（病灶 P1 主战场）

页面模板里写着三列布局的注释，但 CSS 从未实现 —— 这是全站最明显的"乱"。

**Files:**
- Modify: `frontend/src/views/jobs/Jobs.vue`
- Modify: `frontend/src/views/jobs/components/ExecutionLogTable.vue`
- Modify: `frontend/src/views/jobs/components/ManualExecutePanel.vue`
- Modify: `frontend/src/views/jobs/components/ManualExecuteDialog.vue`

**Step 1:** `Jobs.vue` 根 div 加 `class="ds-page"`，删掉模板里那三行描述布局的注释（:105、:107、:125），把注释表达的结构真正写出来：

```html
<div class="ds-page">
  <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
    <ExecutionLogTable ... />
    <ManualExecutePanel :buttons="manualButtons" @execute="openManualDialog" />
  </div>
  <ManualExecuteDialog ... />
</div>
```

注意 `minmax(0,1fr)` 而非 `1fr` —— DataTable 内容宽时 `1fr` 会被撑破且不收缩，这是 PrimeVue 表格与 grid 组合的常见坑。

**Step 2:** `ExecutionLogTable.vue`：外层包 `ds-card`；移除 DataTable 上的 `showGridlines`，保留 `stripedRows` 的**移除**、改为 `class="ds-table"`；筛选栏用 `class="flex flex-wrap gap-3 items-end"`。

**Step 3:** `ManualExecutePanel.vue`：`Card` 加 `ds-card` 类；按钮组 `class="flex flex-col gap-2"`（右栏为竖排操作列表）。

**Step 4:** `ManualExecuteDialog.vue`：移除内联 `width: 500px`（:223），改 `class="ds-dialog-sm"`；表单字段套 `class="flex flex-col gap-4"`。

**验收：** ≥1024px 宽时确实呈左右两栏且右侧固定 320px；<1024px 时降为单列；DataTable 横向不溢出；功能（搜索/重置/分页/手动执行）全部可用。

---

### Task 8：Reports 页（最大页面）

**Files:**
- Modify: `frontend/src/views/reports/Reports.vue`

**Step 1:** 根 div 加 `class="ds-page"`。

**Step 2:** 顶部「选择项目 + Sprint 时间轴」从裸 div 改为卡片化双栏：
```html
<div class="ds-card p-6 flex flex-col gap-4">
  <div class="flex flex-wrap items-end gap-4">
    <div class="flex flex-col gap-2 min-w-[260px]">
      <label class="ds-meta">选择项目</label>
      <Select ... />
    </div>
    <ProgressSpinner v-if="loadingSprintTimeline" strokeWidth="4" class="w-8 h-8" />
  </div>
  <div v-else-if="timelinePoints.length > 0" class="pt-2">
    <Timeline :value="timelinePoints" layout="horizontal" />
  </div>
  <p v-else class="ds-meta">暂无已激活的 Sprint</p>
</div>
```
注意 `v-else-if` 必须与前一个 `v-if` 同级相邻 —— 现在 `ProgressSpinner` 和 `Timeline` 被包在两个不同的 `<div>` 里（:317-329），条件链是断的，`Timeline` 与 `span` 的 `v-else` 也不成链，需一并修正为同一父级下的连续条件。

**Step 3:** 四张图表的容器改为响应式栅格：
```html
<div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
  <MetricsTrendChart ... />
  <MetricsTrendChart ... />
  <MetricsTrendChart ... />
  <MetricsTrendChart ... />
</div>
```
（1280px 以下单列，以上两列 —— 每张图内部高 350px，两列时仍可读。）

**Step 4:** 四个 `<MetricsTrendChart>` 的 `legend-items` 传入的 hex（:339, :350, :361, :372）改为从 `chartPalette.ts` 导入（Task 12 建，可先就地标记 TODO，Task 12 统一替换）。

**验收：** 无内联 style、无硬编码尺寸；条件链正确（加载中/有数据/无数据三态互斥）；四图在不同宽度下排布合理；点击图表打开对应弹窗功能不变。

---

### Task 9：Reports 子组件（8 个）

**Files:**
- Modify: `frontend/src/views/reports/BugDetailDialog.vue`
- Modify: `frontend/src/views/reports/components/MetricsTrendChart.vue`
- Modify: `frontend/src/views/reports/components/BugChartCard.vue`
- Modify: `frontend/src/views/reports/components/BugDetailTable.vue`
- Modify: `frontend/src/views/reports/components/BugListDialog.vue`
- Modify: `frontend/src/views/reports/components/BurndownDialog.vue`
- Modify: `frontend/src/views/reports/components/ReportReopenDialog.vue`
- Modify: `frontend/src/views/reports/components/AvgTimeDevelopersDialog.vue`

**Step 1 — 弹窗尺寸统一（5 个文件）：**
移除全部内联 `:style="{ width: ... }"`，替换为 DS 尺寸档位：

| 文件:行 | 现值 | 改为 |
| --- | --- | --- |
| `BugDetailDialog.vue:184` | `95vw` | `ds-dialog-xl` |
| `BugListDialog.vue:35` | `min(1300px, 95vw)` | `ds-dialog-xl` |
| `BurndownDialog.vue:128` | `1100px` | `ds-dialog-lg` |
| `ReportReopenDialog.vue:24` | `95vw` | `ds-dialog-lg` |
| `AvgTimeDevelopersDialog.vue:75` | `95vw` | `ds-dialog-lg` |
| `AvgTimeDevelopersDialog.vue:127` | `70vw / max 95vw` | `ds-dialog-lg` |

**Step 2 — 表格统一（4 个文件）：** `BugDetailTable`、`BugListDialog`、`ReportReopenDialog`、`AvgTimeDevelopersDialog` 里的 DataTable 一律去掉 `showGridlines` 与 `stripedRows`，加 `class="ds-table"`。

**Step 3 — 卡片统一（2 个文件）：** `MetricsTrendChart.vue` 的 `Card`（:122）与 `BugChartCard.vue` 的 `Card`（:116）加 `ds-card` 类。

**Step 4 — 图表容器尺寸（3 处）：** 内联 `style="width:100%; height:350px"`（MetricsTrendChart:138）、`220px`（BugChartCard:119）、`460px`（BurndownDialog:142）改为 Tailwind 类 `class="w-full h-[350px]"` 等。图表高度属于组件内部实现细节，用 Tailwind 表达即可，无需进 token。

**Step 5 — MetricsTrendChart 的 legend 布局：** 现在 `<span>` 逐个平铺（:125-131），加 `class="flex flex-wrap items-center gap-3"`，每个 legend 项内加色块圆点（用 `--ih-chart-*` 对应色，从 props 的 `item.color` 直接作用于内联 `background`，这是数据驱动色值，允许内联）。

**Step 6 — BugDetailDialog 的三张 BugChartCard 容器**改为 `class="grid grid-cols-1 lg:grid-cols-3 gap-4"`。

**验收：** 8 个文件零内联 `:style` 尺寸；所有弹窗宽度收敛到 4 档；表格风格与全站一致；图表加载/空态可见（`MetricsTrendChart.vue:134-139` 的加载态与空态没有布局，需补 `flex flex-col items-center gap-2` 居中）。

---

### Task 10：DocBugImport 与 ManualExecuteDialog

**Files:**
- Modify: `frontend/src/views/screen/DocBugImport.vue`

（`ManualExecuteDialog.vue` 已在 Task 7 处理。）

**Step 1:** Dialog 内联 `width: min(900px, 95vw)`（:223）改为 `class="ds-dialog-md"`。

**Step 2:** `Steps` 与内容区间距：外层 `class="flex flex-col gap-6"`。

**Step 3:** DataTable 去掉 `showGridlines` + `stripedRows`，加 `ds-table`。

**Step 4:** 步骤 3 的错误列表（:327-331）加 `class="flex flex-col gap-1 pl-5 list-disc"`，套上 `ds-meta` 色。

**Step 5:** 各步骤底部按钮行统一 `class="flex justify-end gap-2 pt-4"`（现在按钮位置在每步里各自散落）。

**Step 6:** 检查 `.p-steps` 与暖纸底的兼容性 —— Aura 的 Steps 组件默认在冷色 surface 上表现更佳，若对比不足，在 `components.scss` 的 PrimeVue 覆写区块内加一条 `.ds-dialog .p-steps-item-title { color: var(--ih-ink); }`，**不要**写在页面文件里。

**验收：** 四步流程视觉连贯；导入/重新导入/校验失败三种路径功能不变；表格无网格线。

---

### Task 11：回归 Dashboard 与 ProjectList

两个参照物页面反向对齐新的组件库 —— 它们的 scoped 样式现在与新 `components.scss` 重复，需消重。

**Files:**
- Modify: `frontend/src/views/dashboard/Dashboard.vue`
- Modify: `frontend/src/views/projects/ProjectList.vue`

**Step 1 — Dashboard.vue：** 删除 `<style scoped>` 块（:211-312）中所有已进 `components.scss` 的部分，保留页面独有结构。逐条对照：

| 原选择器 | 处置 |
| --- | --- |
| `.ds-stats`、`.ds-stat`、`.ds-stat-value`、`.ds-stat-label`、`.tone-*` | **删除** —— 已进 `components.scss` 的 `.ds-stat` |
| `@media (max-width:640px) { .ds-stats }` | **删除** —— 响应式改由 Tailwind `grid-cols-2 md:grid-cols-4` 承担 |
| `.ds-hero`、`.ds-meta`、`.ds-date`、`.ds-dot`、`.ds-sub` | **删除**，模板改用 `components.scss` 的 `.ds-meta` / `.ds-tag-dot` + Tailwind 布局 |
| `.tables` | **删除**，模板改 `class="grid grid-cols-1 xl:grid-cols-2 gap-4"` |

目标：`Dashboard.vue` 的 `<style>` 块完全消失。

**Step 2 — 模板改写：** 统计卡容器改 `class="grid grid-cols-2 md:grid-cols-4 gap-4"`；`.ds-hero` 区改 `class="flex flex-wrap items-center gap-4"`。

**Step 3 — ProjectList.vue：** 同样清空 `<style scoped>`。逐条对照：

| 原选择器 | 处置 |
| --- | --- |
| `.proj-head`、`h2`、`p` | **删除**，改用 `.ds-page-head` + `.ds-meta` |
| `.proj-filters` | **删除**，改 `class="flex flex-wrap items-center gap-3"` |
| `.proj-name`、`.proj-board` | **删除**，改 `class="flex items-center gap-3"` + `.ds-meta` |
| `:deep(.col-center)` | **删除** —— 表头/单元格居中改为在 `components.scss` 加一条 `.ds-table.center` 变体（若确有必要），不要用 `:deep` |
| `.rem-list`、`.rem-item`、`.rem-dot`、`.rem-time`、`.reminder-none` | **删除**，改用 `.ds-tag-dot` + Tailwind 布局 |
| Column 的内联 `style="min-width: 170px"`（:323） | 改 `class="min-w-[170px]"` |

**Step 4 — 表头居中的最终决策：** 当前 `headerClass="col-center" bodyClass="col-center"` 用在全部 5 个 Column 上，等于整表居中。这是设计选择而非必需 —— 建议表格**左对齐**（符合 DS 的表格风格），仅在「操作」列居中。若确认要全居中，则在 `components.scss` 提供 `.ds-table--center` 变体。

**Step 5 — Dialog 尺寸：** `:style="{ width: '760px', maxWidth: '95vw' }"`（:367）改 `class="ds-dialog-md"`。

**Step 6 — 录入/编辑弹窗的表单布局：** 现在 20+ 个字段全是裸 div 堆叠（:371-457），改为分区栅格：
```html
<div class="flex flex-col gap-6">
  <section class="flex flex-col gap-4">
    <h3 class="ds-section-title">项目基础</h3>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="flex flex-col gap-2">
        <label class="ds-meta">面板 ID *</label>
        <InputText ... />
      </div>
      ...
    </div>
  </section>
  ...
</div>
```
「定时任务提醒」区的 ToggleSwitch + 文案 + Select 三元素需要明确布局（现在是三个裸元素并排）：
```html
<div class="flex items-center gap-3">
  <ToggleSwitch v-model="..." />
  <span class="min-w-[80px]">进度提醒</span>
  <Select v-if="..." class="flex-1" ... />
</div>
```

**Step 7:** 在 `components.scss` 补 `.ds-section-title`（小字标题，用于弹窗内的分组标题）。

**验收：** 两个文件的 `<style>` 块均为空/已删除；视觉与基线截图一致或更好（表格居中改左对齐是**有意变更**，需单独确认）；录入/编辑弹窗双列排布，375px 下退为单列；功能（筛选/分页/增删改）不变。

---

### Task 12：图表配色收口

**Files:**
- Create: `frontend/src/views/reports/components/chartPalette.ts`
- Modify: `frontend/src/views/reports/components/charts.ts`
- Modify: `frontend/src/views/reports/Reports.vue`
- Modify: `frontend/src/views/reports/components/MetricsTrendChart.vue`
- Modify: `frontend/src/views/reports/components/BugChartCard.vue`
- Modify: `frontend/src/views/reports/components/BurndownDialog.vue`

**Step 1:** 建 `chartPalette.ts`，导出与 `tokens.scss` 的 `--ih-chart-*` 数值一致的常量（R3）：
```ts
// 数值必须与 assets/styles/tokens.scss 的 --ih-chart-* 保持一致。
// ECharts 走 canvas 渲染，读不到 CSS 变量，故此处硬编码并集中管理。
export const CHART = {
  series1: '#6366F1',
  series2: '#F97316',
  series3: '#EC4899',
  series4: '#14B8A6',
  axisLabel: '#666666',
  tooltipBg: '#1A1A2E',
  tooltipText: '#FFFFFF',
  neutral: '#9CA3AF',
} as const

export const chartBarFill = (hex: string, alpha = 0.35) => /* hex → rgba */ 
export const chartAreaGradient = (rgba: string) => ({ /* 现有 areaGradient，从 Reports.vue:151 迁入 */ })
```

**Step 2:** `charts.ts:48-67` 的 24 个 hex 评估：`PRIORITY` / tag / developer 调色板是**数据语义色**（不同优先级不同色），不属于品牌 token，**保留在 charts.ts 内**，但改为从 `chartPalette.ts` 导入基础色再派生，避免同一色值两处定义。

**Step 3:** `Reports.vue` 的 18 处 hex（:89,96,97,110,111,119,133,140,141,161,162,170,171,173 及 legend :339,350,361,372）全部改为 `CHART.*` 引用；`areaGradient`（:151-154）改为导入 `chartAreaGradient`。

**Step 4:** `MetricsTrendChart.vue:57,59,64,66,67` 与 `BurndownDialog.vue:55,57,62,69,74,84,85,93,94`、`BugChartCard.vue:37,41,57,60,69,86` 的 tooltip / 轴色改为 `CHART.*` 引用。

**Step 5:** `tokens.scss` 的 `--ih-chart-*` 与 `chartPalette.ts` 的注释互指（R3），并在 `components.scss` 里给 legend 色点用上 `--ih-chart-*`。

**验收：** `grep -rnE "#[0-9a-fA-F]{6}" src/views/reports/` 只命中 `chartPalette.ts` 与 `charts.ts`；所有图表 tooltip / 轴 / 系列色与整改前**完全一致**（此任务只做集中化，不改视觉）。

---

### Task 13：对比度与可访问性收口

**Files:**
- Modify: `frontend/src/assets/styles/tokens.scss`
- Modify: `frontend/src/assets/styles/components.scss`
- Modify: `frontend/src/main.ts`

**Step 1:** 品牌绿 `#aadb1e` 的对比度问题（P5）落地规则：
- **填充用途**（按钮底、Tag 底、进度条）：保持 `--ih-brand: #aadb1e`。
- **文字/图标用途**：一律改用 `--ih-brand-text: #415a0b`（primary-900，对白底约 8.6:1，达标）。
- 在 `IterhubPreset` 里显式确认 `primary-500` 仅被 PrimeVue 用于填充；**检查 `Button` 组件**：Aura 的 primary 按钮是 primary 底 + 白字，白字对 `#aadb1e` 仅 1.6:1 —— 这是 Aura 预设本身的已知问题。对策：把按钮的文字色在 `components.scss` 的 PrimeVue 覆写区块中改为 `--ih-brand-text`，或把按钮底色改为 primary-700（`#739614`，白字对比度约 3.5:1，仍偏弱）→ **最稳妥是 primary-800 `#5a750f`（白字约 5.9:1，达标）**。

  → 这是一个需要视觉确认的取舍：更深的绿更合规但离"品牌绿"更远。建议把按钮底色定为 primary-700，并在 Task 13 的验收里逐页目视确认可读性；若不可接受，退回 primary-600 并接受对比度告警。

**Step 2:** 逐项检查（用浏览器 DevTools 的对比度检查器，或 `axe` DevTools 扩展）：

| 用途 | 前景 | 背景 | 目标 |
| --- | --- | --- | --- |
| 正文 | `--ih-ink` #1e232c | `--ih-surface` #fff | ≥ 4.5:1 |
| 次要文字 | `--ih-ink-muted` rgba(30,35,44,0.6) | #fff | ≈4.8:1 ✅ |
| 极淡文字 | `--ih-ink-faint` rgba(30,35,44,0.4) | #fff | ≈2.9:1 ⚠️ 仅用于非必要信息（如 "—" 占位） |
| 表头 | `--ih-ink-muted` | 透明→#fff | ✅ |
| 主按钮 | 白字 | primary 底 | 见 Step 1 |
| 侧栏激活项 | primary-700 | primary-100 | 需实测 |

**Step 3:** `--ih-ink-faint` 的使用范围收敛：`ProjectList.vue` 的 `.reminder-none`（"—"）可以，但不得用于任何需要阅读的文案。

**Step 4:** 焦点可见性：Tailwind 布局类不改变焦点样式，但删除 `.app-content > div` 后需确认 PrimeVue 组件的 `:focus-visible` 环仍在（默认在）。补一条：键盘 Tab 遍历 6 个页面，确认每个交互元素都有可见焦点环。

**验收：** DevTools 对比度检查无 AA 失败项（或已知例外已记录理由）；键盘可完整操作全部页面主要流程。

---

### Task 14（可选）：类名前缀统一

若决定把 `ds-` 改为 `ih-`（§2.3），在所有页面整改**完成并验收后**执行，作为独立提交：

```bash
cd frontend
grep -rl "ds-" src/ | xargs sed -i 's/\bds-page\b/ih-page/g; s/\bds-card\b/ih-card/g; ...'
```
每个类名单独列出并逐个替换，**不要**用宽泛的 `s/ds-/ih-/g`（会误伤 `ds-page` 之外的字符串）。替换后跑 `npm run build` 与全页视觉对照。

**验收：** `grep -rn "\bds-" src/` 零命中；构建通过；视觉零变化。

---

## 五、执行顺序总览

```
Task 0  安全网（git init + 基线截图 + 构建验证）        ← 阻塞项，必做
  ↓
Task 1  拆分样式文件结构（tokens / base / components）
  ↓
Task 2  接入 Tailwind 4（无 preflight + layer 顺序）
  ↓
Task 3  补齐组件类（ds-* 全量）
  ↓
Task 4  清除死代码（.bak）
  ↓
Task 5  Login（校准表单语言）
  ↓
Task 6  Screen / Sonar（占位页，低风险）
  ↓
Task 7  Jobs（病灶 P1 主战场）
  ↓
Task 8  Reports 页（最大页面）
  ↓
Task 9  Reports 子组件 ×8
  ↓
Task 10 DocBugImport
  ↓
Task 11 回归 Dashboard / ProjectList（参照物最后动）
  ↓
Task 12 图表配色收口
  ↓
Task 13 对比度与可访问性收口
  ↓
Task 14（可选）类名前缀统一
```

**每个 Task 完成后必须做：**
1. `npm run build` 通过
2. 该页面与基线截图对照
3. 独立 git commit（Task 0 之后才有版本控制）

---

## 六、验收标准

### 量化目标

| 指标 | 现状 | 目标 |
| --- | --- | --- |
| 含 `<style>` 块的 `.vue` | 2 / 21 | **0 / 21** |
| class 属性为 0 的文件 | 19 / 21 | **0** |
| 内联 `:style=` 尺寸 | 13 处 / 11 文件 | **0**（数据驱动色值除外） |
| `.vue` 内硬编码 hex | 30 + 24(charts.ts) | **0 + 24（集中到 chartPalette.ts）** |
| PrimeVue `.p-*` 覆写位置 | 7 处散落全局 scss | **全部集中于 components.scss 一个区块** |
| `:deep()` 使用 | 1 处 | **0** |
| 弹窗宽度档位 | 7 种魔法数字 | **4 档 token** |
| Tailwind 工具类 | 0 | 布局全覆盖 |
| 死代码文件 | 2 | **0** |

### 人工验收清单

- [ ] 7 个路由在 375px / 768px / 1280px / 1920px 四档宽度下均无横向溢出、无元素叠压
- [ ] 全站底色一致（暖纸底 `--ih-paper`），无页面残留冷灰 `surface-50`
- [ ] 全站卡片一致（白底 + 发丝线 + 16px 圆角 + 1.5rem 内边距）
- [ ] 全站表格一致（无斑马纹 + 无网格线 + 发丝线行分隔 + 小字大写表头）
- [ ] 全站弹窗宽度只出现 4 种
- [ ] 键盘 Tab 可完成登录、切页、表格翻页、打开/关闭弹窗
- [ ] 构建产物 `dist/assets/*.css` 中无重复的 `.ds-*` 定义
- [ ] `npm run build` 通过，无 `vue-tsc` 类型错误

### 有意变更（需业主确认，不是回归）

1. **字号基准 18px → 16px**（Task 1）—— 全站元素缩小 11%，这是修正而非退化。
2. **ProjectList 表格由全居中改左对齐**（Task 11）—— 仅"操作"列居中。
3. **按钮底色可能加深**（Task 13）—— 为满足对比度，品牌绿 `#aadb1e` 可能退为 primary-700/800。

---

## 七、风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| Tailwind preflight 破坏 PrimeVue | 全站组件视觉崩塌 | R1：不引 preflight，只引 theme + utilities |
| PrimeVue `cssLayer` 顺序配置错误 | utilities 被覆盖，工具类失效 | R2：Task 2 冒烟验证 + 构建产物检查 |
| 字号基准变更引发布局塌陷 | 多页错位 | R4：Task 1 单独提交，逐页对照基线截图 |
| grid `1fr` 被 DataTable 撑破 | Jobs 页溢出 | Task 7 Step 1 用 `minmax(0,1fr)` |
| ECharts 读不到 CSS 变量 | 图表无色 | R3：图表色走 TS 常量 |
| 改动量大、无回滚 | 无法恢复 | Task 0：先建 git 仓库 |
| 参照物页面被提前污染 | 失去对照基准 | 执行顺序：Dashboard/ProjectList 放最后的 Task 11 |
