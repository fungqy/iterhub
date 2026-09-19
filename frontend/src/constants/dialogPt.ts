/**
 * 弹窗「固定放大态」的 PassThrough 配置。
 *
 * ── 需求 ──
 * 弹窗头部原本有两个圆形图标按钮：最大化/还原 + 关闭。
 * 产品要求「固定展示放大状态，去掉缩放按钮」
 *   = 一打开就是**点了最大化按钮之后**的样子，且不再提供该按钮。
 *
 * ── 为什么不是 `maximizable` ──
 * PrimeVue 的 `maximized` 是 Dialog **内部 data**（默认 false），没有任何 prop
 * 能设定它的初始值，只有点击按钮才会翻转。想「默认放大」只能去改组件内部状态。
 *
 * 更关键的是：放大态的样式类由 props 决定（primevue/dialog/style/index.mjs）：
 *     root: ['p-dialog p-component', { 'p-dialog-maximized': props.maximizable && instance.maximized }]
 *   ⇒ 一旦去掉 `maximizable`，这个类**永远挂不上**。
 *   所以「去掉按钮」不能靠删 prop 顺带实现，必须自己把类补回去。
 *
 * ── 本方案 ──
 * 直接给根节点挂 `p-dialog-maximized`（PrimeVue 官方的样式逃生口 `pt`），
 * 同时不再传 `maximizable` —— 按钮由模板里的 `v-if="maximizable"` 自然消失。
 * 全程只用公开 API，不碰组件内部状态。
 *
 * ⚠ 副作用（已确认无害）：maximizable 为 false 时，Dialog 打开后的初始焦点
 *   落在**关闭按钮**上（源码 focus() 的 else 分支），不再是最大化按钮。
 *   components.scss 里 `.p-dialog-header-actions .p-button:focus-visible` 那条
 *   去圆环规则因此**仍然需要**（现在正好覆盖到关闭按钮）。
 *
 * ── 放大态的真实尺寸（2026-09-17 探针 86 实测，1440×900 视口）──
 *   ⚠ **不是 100vw × 100vh**，而是 **95vw × 95vh**：
 *     · `.p-dialog-maximized` 给的是 width/height: 100vw/100vh !important；
 *     · 但本项目 components.scss（@layer ds，层序在 primevue 之后 ⇒ 优先）
 *       另有 `.p-dialog { max-height: 95% }` 与 `.ds-dialog-* { max-width: 95vw }`，
 *       两条上限把它压回 95%。实测 1368×855 = 1440×0.95 / 900×0.95，与之一致。
 *   · 圆角保持 12px(原本被 `.p-dialog-maximized` 抹成 0px；2026-09-17 用户要求
 *     「直角弹窗统一成概览弹窗的圆角」后，由 components.scss 覆写回
 *     `dt('dialog.border.radius')`，与普通态同源 —— 见该处注释)；
 *   · top/left 虽被设为 0，但 .p-dialog 是 position:static，
 *     不生效，居中仍由遮罩的 flex center 完成（实测左上角 36,23 即居中结果）。
 * 这些值**不要**照 PrimeVue 文档写成 100vw/100vh —— 实测口径是 95%。
 */
export const MAXIMIZED_DIALOG_PT = {
  root: { class: 'p-dialog-maximized' },
} as const
