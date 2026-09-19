import { computed, inject, provide, type ComputedRef, type InjectionKey } from 'vue'

/**
 * 「当前正在下钻的 Sprint」—— 全站唯一一份。
 *
 * ## 为什么需要它
 * RDM 侧的「故障详情」要按 sprint 消歧:`rdm_issue.issue_key` **不是唯一键**
 * (同一只故障被多个 Sprint 各拉一行,实测 JSST-560 同时属于 6845 与 6954),
 * 少传 sprint 就会取到"另一次拉取"的那一行。
 *
 * 改前这个 sprint 是**逐层手传**的:页面上一张表一个 ref,再经列表弹窗透传给详情弹窗。
 * 加第五张故障表的人必须记得三处接线,漏一处不会报错 —— 只会静默取到错的行。
 * 这里把它改成**由页面 provide、由需要的人自己 inject**:将来再加一张表,挂上组件就能用。
 *
 * ## 为什么不是 route/query
 * 直觉上「当前 Sprint」像是 URL 的一部分,但 `/reports` 是**同时展示多个 Sprint** 的
 * 看板(趋势图一次画 7 个、时间轴列出全部),页面上并不存在一个"当前 Sprint"。
 * 把它塞进 query 等于凭空发明一个概念,还得处理"用户没选任何 Sprint 时 query 是什么"。
 * 真正的事实是:**一次下钻只涉及一个 Sprint**,那正是下面这个 scope 表达的东西。
 *
 * ## 为什么单一 ref 是安全的
 * 弹窗是模态的 ⇒ 任意时刻只有**一条**下钻链在展开(Sprint → 列表 → 详情),
 * 链条上每一层看到的都是同一个 Sprint。所以 8 个各自为政的 ref 可以合并成 1 个,
 * 而不存在"'两个弹窗同时属于不同 Sprint'该信谁"的问题。
 *
 * ## 跨 teleport 依然有效
 * PrimeVue 的 Dialog 会把内容 teleport 到 body,但 provide/inject 走的是**组件树**
 * (vnode 的父子关系)而不是 DOM 树 —— 插槽内容的 parent 仍是"在模板里写下它的那个组件"。
 * 所以页面 provide 的值,能被嵌套在其子弹窗里的详情弹窗拿到。
 */
export const SPRINT_SCOPE: InjectionKey<ComputedRef<number | null>> = Symbol('ih:sprint-scope')

/**
 * 归一化为 `number | null`。
 *
 * 接口返回的 `sprint_id` 是**字符串**(如 "7506"),而各处判定一律按 number 比较;
 * 空串/null/非数字一律归为 null(= 没有 sprint 语境),避免把空串拼进请求
 * —— 后端 `/reports/bugs/one` 声明的是 `int | None`,传空串会被判 422。
 */
export function normalizeSprintId(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * 在页面(或任意祖先组件)里声明「当前下钻的 Sprint」。
 *
 * 传**取值函数**而不是值本身:函数在 computed 求值时才会调用,
 * 于是页面 ref 变化能如实传导到下游的 inject 方。
 */
export function provideSprintScope(
  source: () => unknown,
): ComputedRef<number | null> {
  const id = computed(() => normalizeSprintId(source()))
  provide(SPRINT_SCOPE, id)
  return id
}

/**
 * 取当前下钻的 Sprint。**没有祖先 provide 时返回 null**(而不是抛错)——
 * 文档故障走的是另一条链(其 key 唯一、不需要消歧),挂在没有 scope 的页面上也应当能用。
 */
export function useSprintScope(): ComputedRef<number | null> | null {
  return inject(SPRINT_SCOPE, null)
}
