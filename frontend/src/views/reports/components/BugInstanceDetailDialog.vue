<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { reportsApi, type RdmBugDetail } from '@/api/reports'
import type { DocBugImageMeta, DocBugRecord } from '@/api/dataImport'
import { dataImportApi, docBugImageUrl } from '@/api/dataImport'
import { useSprintScope } from '@/composables/useSprintScope'
import type { TagSeverity } from '@/constants/taskMeta'
import { MAXIMIZED_DIALOG_PT } from '@/constants/dialogPt'
import Dialog from 'primevue/dialog'
import ProgressSpinner from 'primevue/progressspinner'
import Tag from 'primevue/tag'
import Timeline from 'primevue/timeline'

/**
 * 统一的「故障详情」弹窗 —— **所有**故障列表里点任意一行都打开它。
 *
 * 故障有两种来源,共用同一个外壳与同一套版式,只有「额外那一段」不同:
 *   - RDM 故障(source='RDM'):字段取自 rdm_issue,额外一段 = **故障变更记录**(时间线);
 *   - 文档故障(source='DOC'):字段取自 rdm_doc_bug,额外一段 = **现场截图**。
 *
 * 文档故障在 rdm_bug_changelog 里没有对应记录,故对它**整段不渲染**变更记录 ——
 * 不渲染成空态,是因为「这一段的空」在数据上根本不存在,画一个空壳只会让人以为是加载失败
 * 或数据缺失。RDM 侧则相反:空态要留着(结构上可能有、只是当前没有)。
 *
 * 两条性能取向(文档故障这一侧尤为关键):
 *  1. **字段与附属清单一次并行取**:RDM 是变更记录内联在详情响应里(一次往返),
 *     DOC 是「字段 + 截图清单」两个小响应并行 —— 都不构成"打开详情变慢"的理由。
 *  2. **主视图恒走缩略图**(单张 12~35KiB),**点图片**才在原图弹窗里拉原图(单张最大 1.5MiB)。
 *     截图中位 2618×1448,直接铺原图会让每次打开都付出兆级流量;而浏览器对 <img src> 的
 *     原生缓存 + 后端 ETag(内容 sha256) 会让二次打开走 304,几乎零流量。
 *     ⚠ 「查看原图 / 看缩略图」按钮与「新标签打开原图」链接已按用户要求删除(2026-09-17),
 *       原图只剩「点图片 → 弹窗」这一个入口,故主视图也再没有「就地铺原图」的态。
 */
const props = defineProps<{
  visible: boolean
  /** 故障来源。决定取哪张表、以及「额外那一段」是变更记录还是现场截图 */
  source: 'RDM' | 'DOC'
  /** 编码(列表里的 issue_key;DOC 侧即 rdm_doc_bug.key) */
  issueKey: string | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const isDoc = computed(() => props.source === 'DOC')

/**
 * RDM 侧消歧用的 Sprint —— **本组件自己从下钻上下文里取,不由调用方传**。
 *
 * 为什么不传:`rdm_issue.issue_key` 不唯一(同一故障被多个 Sprint 各拉一行,实测
 * JSST-560),少传就会取到"另一次拉取"的那一行,而"漏传"这件事**不会报错**。
 * 改前它由页面上的 ref 经列表弹窗逐层透传,新增一张故障表就得记得接三处线;
 * 现在页面 provide 一次(见 useSprintScope),这里 inject 即可 ——
 * 新增列表只要挂在同一个页面下就自动是对的,没有可漏的环节。
 *
 * 取不到时(如文档故障所在的 /doc-import 页面没有 Sprint 语境)为 null,
 * 后端只按 issue_key 取一行 —— 文档故障的 key 本就是唯一键,不需要消歧。
 */
const sprintScope = useSprintScope()
const sprintId = computed(() => sprintScope?.value ?? null)

const rdm = ref<RdmBugDetail | null>(null)
const docDetail = ref<DocBugRecord | null>(null)
const images = ref<DocBugImageMeta[]>([])
const loading = ref(false)
const loadError = ref('')
const activeIndex = ref(0)
/** 原图弹窗是否打开 —— 只有点主视图里那张缩略图才会置真(见模板) */
const viewerVisible = ref(false)

const changelog = computed(() => rdm.value?.changelog ?? [])

/**
 * 「额外那一段」是否存在 —— RDM 按 `!isDoc`、DOC 按 `isDoc`,**恒为 true**,
 * 故不设标志位,模板里直接用 `!isDoc` / `isDoc` 判。
 *
 * 关键是判「**这段该不该存在**」而不是「**现在有没有内容**」(`changelog.length` / `images.length`):
 *   · DOC 的字段与截图清单是并行取的,谁先回来不定 —— 按长度判会让右栏先空后跳,版式抖动;
 *   · RDM 无记录、DOC 无截图时,右栏应显示「暂无变更记录 / 暂无截图」的空态,
 *     而不是整段消失(见文件头注释:空态要留着)。
 * 两段互斥,故任何时刻恰好只有一侧有内容,右栏另一半永远是空的。
 */

const activeImage = computed<DocBugImageMeta | null>(
  () => images.value[activeIndex.value] ?? null
)

/**
 * 原图地址 —— **只给原图弹窗用**(见 viewerVisible)。
 * 主视图恒走缩略图,故这条 URL 只有用户真的点了图片才会被请求:
 * 原图单张最大 1.5MiB,不是"打开详情"该付的流量(见文件头)。
 */
const originalUrl = computed(() => (activeImage.value ? docBugImageUrl(activeImage.value.id) : ''))

/**
 * 取某张图的 URL。要求缩略图时**仍要检查该条是否真有缩略图** ——
 * 生成失败的个例(缩略图列为 NULL)若照拼 thumb=1 会 404,呈现为裂图。
 * 缩略图带尤其要注意:它是批量铺开的,一条裂图会毁掉整条带的可信度。
 */
function imageUrl(im: DocBugImageMeta, thumb: boolean): string {
  return docBugImageUrl(im.id, thumb && !!im.thumb_byte_size)
}

/**
 * 主视图那张图 —— **恒为缩略图**(imageUrl 内部对没有缩略图的个例自动回落到原图)。
 *
 * ⚠ 原先这里跟着一个 `showOriginal` 开关(「查看原图 / 看缩略图」按钮在切它)。
 *   该按钮与「新标签打开原图」链接已按用户要求去掉,改由「点图片 → 弹窗看原图」承担,
 *   所以这一处不再有第二个取值,开关连同它的三处重置(切图 / 打开详情)一起删干净。
 */
const previewSrc = computed(() => {
  const im = activeImage.value
  if (!im) return ''
  return imageUrl(im, true)
})

/**
 * 图片元信息文案 —— 主视图与看图弹窗**共用这一份**。
 * 两处各写一遍会漂:改了主视图那份、忘了弹窗那份,同一张图的尺寸与体积就会显示成两个值,
 * 而这件事**不报错**,只能靠肉眼比出来。
 */
const imageMeta = computed(() => {
  const im = activeImage.value
  if (!im) return ''
  return `第 ${activeIndex.value + 1} / ${images.value.length} 张 · ${im.column_label || '—'}`
    + ` · ${im.width ?? '—'}×${im.height ?? '—'} · ${fmtBytes(im.byte_size)}`
})

/**
 * 优先级色档。RDM 与文档故障用的是两套档位(致命/严重/一般/轻微/优化 与 极高/高/中/低),
 * 这里都把各自的档位显式写出来 —— 缺一条就会落到 secondary 的灰底,看起来像"没级别"。
 */
const PRIORITY_SEVERITY: Record<string, 'danger' | 'warn' | 'info' | 'success' | 'secondary'> = {
  致命: 'danger',
  严重: 'warn',
  一般: 'info',
  轻微: 'success',
  优化: 'secondary',
  极高: 'danger',
  高: 'warn',
  中: 'info',
  低: 'success',
}

/**
 * 「处理状态」色档。
 *
 * RDM 与文档故障是**两套完全不同的状态词表**(直连 DB 核过)：
 *   RDM  故障：完成(828/828 全部)
 *   DOC  文档故障：验证通过(10) / 未开始(2) / 继续观察 / 已排期 / 转需求 / 待测试
 * 两套都写全 —— 缺一条就落到 secondary 的灰底,看起来像"没状态"。
 *
 * ⚠ 未命中一律回 secondary(不是不渲染):后端加一个新状态词时,界面上应该出现一个
 *   灰色胶囊(说明"这个词我不认识"),而不是整格空白(那看起来像字段丢了)。
 */
const STATUS_SEVERITY: Record<string, TagSeverity> = {
  // RDM
  完成: 'success',
  // DOC
  验证通过: 'success',
  待测试: 'info',
  已排期: 'info',
  继续观察: 'warn',
  转需求: 'warn',
  未开始: 'secondary',
}

/**
 * 「解决结果」(RDM resolution,828 行里 5 种取值)色档。
 * 只有「完成」是真正的解决;其余四种(非问题/无法再次复现/重复提交/被否决)都是
 * 「关掉了但没修」—— 故统一给 secondary 的灰,而不是给 success 的绿:
 * 绿色在这张表里已经被「优先级=轻微」「状态=完成」占用,再来一个绿会稀释它的含义。
 */
const RESOLUTION_SEVERITY: Record<string, TagSeverity> = {
  完成: 'success',
  非问题: 'secondary',
  无法再次复现: 'secondary',
  重复提交: 'secondary',
  被否决: 'secondary',
}

/**
 * 「故障类型 / 问题类别 / 映射标签」色档 —— 这三者都是**分类词**,不是状态。
 *
 * 分类词与状态词的性质完全不同:状态有"好/坏"的极性,分类没有。
 * 故这里**一色到底用 info(蓝)**,不做极性映射 —— 给「系统问题」上红、给「优化建议」上绿,
 * 等于替用户对业务分类做价值判断,而分类本身并不携带这个信息。
 * 蓝是本页唯一没被状态/优先级占用的语义色(绿=完成、橙=进行中、红=致命、灰=已关闭),
 * 且它在亮暗两态都清晰可读。
 *
 * 值集(直连 DB 核过):RDM bug_type = 系统问题/优化建议;DOC original_type & type 同源。
 * 但**仍用查表 + 回退**,因为真实数据在后端补齐后会比现在这两三种多得多。
 */
const CATEGORY_SEVERITY: Record<string, TagSeverity> = {
  系统问题: 'info',
  优化建议: 'info',
  模型能力问题: 'info',
  环境问题: 'info',
}

/**
 * 「故障标签」(RDM bug_flag)色档 —— 这张表回答的是「这个故障**为什么**发生」。
 *
 * ⚠ 与 CATEGORY_SEVERITY(「是什么类的问题」)是两个不同的问题,故配色策略也不同:
 * 分类是中性描述 ⇒ 一色到底;归因是**责任性质的** ⇒ 值得区分:
 *   · 代码逻辑问题 / 漏做做错  —— 自己写的代码有问题(最该被看见)
 *   · 需求不完善 / 需求理解不到位 —— 上游输入不足
 *   · 沟通问题 / 外部依赖 / 环境问题 / 页面样式 —— 流程或环境
 *   · 优化 —— 不是缺陷
 * 值集取自 DB 实测(代码逻辑问题 91 / 需求不完善 9 / 沟通问题 6 / 漏做做错 5 / 外部依赖 3 /
 * 环境问题 3 / 页面样式 3 / 优化 2 / 需求理解不到位 2)。
 * ⚠ 该列 828 行里 **704 行为 NULL** —— 故「空值不渲染标签」这条在这里是主力情形(见 dd 模板)。
 */
const FLAG_SEVERITY: Record<string, TagSeverity> = {
  代码逻辑问题: 'danger',
  漏做做错: 'danger',
  需求不完善: 'warn',
  需求理解不到位: 'warn',
  沟通问题: 'info',
  外部依赖: 'info',
  环境问题: 'info',
  页面样式: 'info',
  优化: 'success',
}

/**
 * 「是否反复 / 是否偶发」(RDM is_unplaned 与 DOC is_repeated / is_occasional 同族)。
 *
 * 「否」不是一个需要被注意的值 —— 给绿色会让一整列「否」变成一片绿地,反而盖住
 * 真正需要看的那个「是」。故:是 ⇒ warn(橙,提示风险),否 ⇒ secondary(灰,推向背景)。
 * 未知(空) ⇒ 交给模板判空、不渲染。
 */
const YESNO_SEVERITY: Record<string, TagSeverity> = {
  是: 'warn',
  否: 'secondary',
}

/**
 * 恒定 secondary 的**空映射表** —— 给「打回次数」「处理方式」这类恒灰字段用。
 *
 * 为什么不直接在调用处写 `tag: {}`:空对象看不出意图,读的人得回去查 toItem 才知道
 * `{}` 到底意味着"不该有标签"还是"永远灰色"。有个名字,调用处就是自解释的:
 *   `tag: CONST_SEVERITY` ⇒ 恒定灰;不写 `tag` ⇒ 根本不是标签。
 * 同时它也让 `tag: {}` 这种字面量在文件里只剩一处(就是这里),便于统一调整。
 *
 * ⚠ 「打回次数」为什么恒定灰、不按 0/1/2+ 分档(用户 2026-09-17 拍板):
 *   同一个弹窗里「优先级」已经在用红/橙/蓝/绿表达严重度,再让一个纯计数按数量变色,
 *   会出现「橙色的 1 次打回」与「橙色的严重优先级」同色不同义,读者无从分辨哪个颜色在说什么。
 *   计数只需要**被当成数据读到**,不需要被赋予情绪 —— 数本身已表达大小,颜色再加一层是重复编码。
 */
const CONST_SEVERITY: Record<string, TagSeverity> = {}

/**
 * 字段值的渲染形态。
 *
 * 三档:
 *   · 不传  ⇒ 纯文本(默认)。人名、时间戳、编号、模块、迭代名、长文本都属此列。
 *   · tag   ⇒ 胶囊标签。key 是色档映射表,**空表({})表示该字段恒定用 secondary**。
 *   · priority ⇒ 沿用上面的优先级专档(单独留一档是因为它既要 Tag 又要特殊回退)。
 *
 * ⚠ 为什么把「怎么渲染」放到 FieldSpec 上,而不是在模板里 if 一串 label:
 *   模板里按 label 字符串分支,等于把「哪些字段是标签」这件事**又写了一遍** ——
 *   加一个字段就得记得改两处,而漏改表现为"某个字段悄悄是纯文本"(不报错)。
 *   放在数据旁,新增字段时它与 pick 同行,不可能只改一半。
 */
interface FieldSpec<T> {
  label: string
  pick: (d: T) => string
  /** 该字段用优先级 Tag 渲染(而不是纯文本) */
  priority?: boolean
  /** 该字段用胶囊 Tag 渲染;给色档映射表(空对象 = 恒定 secondary) */
  tag?: Record<string, TagSeverity>
}


function dash(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

/** 后端回的是 ISO 串;表里本来就是"日期+时间"口径,不需要本地化时区转换 */
function fmtTime(v: string | null): string {
  if (!v) return '—'
  return v.replace('T', ' ').slice(0, 19)
}

function fmtBytes(n: number | null | undefined): string {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / 1024 / 1024).toFixed(2)} MiB`
}

/** 秒换算为可读耗时(天/小时/分钟),不足一分钟归为 1 分钟 */
function secondsToDuration(seconds: number): string {
  if (seconds <= 0) return '-'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.max(1, Math.round((seconds % 3600) / 60))
  const parts: string[] = []
  if (days > 0) parts.push(days + '天')
  if (hours > 0 || days > 0) parts.push(hours + '小时')
  if (days === 0) parts.push(minutes + '分钟')
  return parts.join('')
}

/**
 * 文档故障的「故障信息」字段。
 *
 * ⚠ 加 `tag` 的字段 = 用户 2026-09-17 要求做成胶囊标签的那些。
 *   「所属迭代」**故意不加** —— 用户明确拍板不加(迭代名长如 botadp-Sprint-11,胶囊太占宽);
 *   探针 cdp-drive84 里有一条反向断言守着它,别顺手补上。
 *   人名/时间戳/编号/故事号同理保持纯文本:它们是**标识**,不是**分类**,
 *   做成胶囊只会让 16 个字段看起来像 16 个按钮、削弱真正需要区分的状态与类别。
 */
const DOC_SHORT_FIELDS: FieldSpec<DocBugRecord>[] = [
  { label: '优先级', pick: (d) => dash(d.priority), priority: true },
  { label: '处理状态', pick: (d) => dash(d.status), tag: STATUS_SEVERITY },
  { label: '问题类别', pick: (d) => dash(d.original_type), tag: CATEGORY_SEVERITY },
  { label: '映射标签', pick: (d) => dash(d.type), tag: CATEGORY_SEVERITY },
  { label: '产生人', pick: (d) => dash(d.maker) },
  { label: '所属迭代', pick: (d) => dash(d.sprint_name) },
  { label: '故事号', pick: (d) => dash(d.story_key) },
  { label: '创建时间', pick: (d) => fmtTime(d.propose_time) },
  { label: '解决时间', pick: (d) => fmtTime(d.resolve_time) },
  { label: '处理方式', pick: (d) => dash(d.resolve_method), tag: CONST_SEVERITY },
  { label: '是否反复', pick: (d) => dash(d.is_repeated), tag: YESNO_SEVERITY },
  { label: '是否偶发', pick: (d) => dash(d.is_occasional), tag: YESNO_SEVERITY },
  { label: '打回次数', pick: (d) => dash(d.bounce_count), tag: CONST_SEVERITY },
  { label: '最后编辑人', pick: (d) => dash(d.last_editor) },
  { label: '最后编辑时间', pick: (d) => fmtTime(d.last_edit_time) },
  { label: 'RDM 编号', pick: (d) => dash(d.rdm_key) },
]

const DOC_LONG_SECTIONS: FieldSpec<DocBugRecord>[] = [
  { label: '问题详述', pick: (d) => (d.name || '').trim() },
  { label: '原因分析', pick: (d) => (d.reason || '').trim() },
  { label: '验证备注', pick: (d) => (d.verify_note || '').trim() },
]

/** RDM 故障的「故障信息」字段（`tag` 的含义同 DOC_SHORT_FIELDS 上方注释） */
const RDM_SHORT_FIELDS: FieldSpec<RdmBugDetail>[] = [
  { label: '优先级', pick: (d) => dash(d.priority), priority: true },
  { label: '处理状态', pick: (d) => dash(d.status), tag: STATUS_SEVERITY },
  { label: '解决结果', pick: (d) => dash(d.resolution), tag: RESOLUTION_SEVERITY },
  { label: '故障类型', pick: (d) => dash(d.bug_type), tag: CATEGORY_SEVERITY },
  { label: '故障标签', pick: (d) => dash(d.bug_flag), tag: FLAG_SEVERITY },
  { label: '产生人', pick: (d) => dash(d.bug_maker) },
  { label: '修复人', pick: (d) => dash(d.bug_solver) },
  { label: '开发负责人', pick: (d) => dash(d.developer) },
  { label: '测试负责人', pick: (d) => dash(d.tester) },
  { label: '报告人', pick: (d) => dash(d.reporter) },
  { label: '经办人', pick: (d) => dash(d.assignee) },
  // ⚠ 「所属迭代」不加 tag —— 用户 2026-09-17 拍板（同 DOC 侧）
  { label: '所属迭代', pick: (d) => dash(d.sprint_name) },
  { label: '所属故事', pick: (d) => dash(d.bug_story) },
  { label: '模块', pick: (d) => dash(d.module) },
  { label: '打回次数', pick: (d) => dash(d.callback), tag: CONST_SEVERITY },
  { label: '是否计划外', pick: (d) => (d.is_unplaned == null ? '—' : (d.is_unplaned ? '是' : '否')) },
  { label: '创建时间', pick: (d) => fmtTime(d.created) },
  { label: '更新时间', pick: (d) => fmtTime(d.updated) },
  { label: '到期日', pick: (d) => dash(d.duedate) },
]

const RDM_LONG_SECTIONS: FieldSpec<RdmBugDetail>[] = [
  { label: '故障原因', pick: (d) => (d.bug_reason || '').trim() },
  { label: '描述', pick: (d) => (d.description || '').trim() },
]

/**
 * 字段 → 渲染项。
 *
 * `tag` 字段有三态,模板据此三选一:
 *   · `tag: null`        ⇒ 纯文本
 *   · `tag: { … }`       ⇒ 渲染胶囊,severity 已在这里解析好
 * 三态里最关键的一条:**空值(—)不产出 tag**。
 *
 * 为什么必须在这里判空、而不是让模板渲染一个 value 为「—」的灰胶囊:
 *   实测 rdm_doc_bug 的 16 行里,`resolve_method` / `is_repeated` / `is_occasional` /
 *   `bounce_count` **四列全为空**,`bug_flag` 在 828 行里 704 行为 NULL ——
 *   也就是说「空」不是边角情形,而是这些字段的**常态**。若空值也出胶囊,
 *   文档故障详情会变成一排写着「—」的灰胶囊,既没信息量,又让人误以为"有值、只是长得像破折号"。
 *   「—」在项目里的语义是**占位**(见 --ih-ink-faint 注释:仅"—"占位,不得用于需阅读的文案),
 *   占位就该是淡淡的文字,不该被框成一个看起来像数据的控件。
 */
function toItem<T>(f: FieldSpec<T>, d: T): { label: string; value: string; tag: TagSeverity | null } {
  const value = f.pick(d)
  if (f.priority) return { label: f.label, value, tag: detailSeverityOf(value) }
  if (f.tag) return { label: f.label, value, tag: value === '—' ? null : (f.tag[value] ?? 'secondary') }
  return { label: f.label, value, tag: null }
}

const fieldItems = computed(() => {
  if (isDoc.value) {
    const d = docDetail.value
    if (!d) return []
    return DOC_SHORT_FIELDS.map((f) => toItem(f, d))
  }
  const d = rdm.value
  if (!d) return []
  return RDM_SHORT_FIELDS.map((f) => toItem(f, d))
})

const longSections = computed(() => {
  if (isDoc.value) {
    const d = docDetail.value
    if (!d) return []
    return DOC_LONG_SECTIONS.map((s) => ({ label: s.label, value: s.pick(d) }))
  }
  const d = rdm.value
  if (!d) return []
  return RDM_LONG_SECTIONS.map((s) => ({ label: s.label, value: s.pick(d) }))
})

/**
 * 优先级值的色档解析 —— 收成一个纯函数,而不是留着原来的 `detailPriority` computed。
 *
 * 差别在哪:computed 是"从 ref 里再读一次 priority",而 `toItem()` **已经把值取出来了**
 * (它必须先取值才能判空)。若两处各自取值,就出现"同一个字段两条取数路径"——
 * 一旦某天 RDM 侧的优先级改成从别的字段回落(如 `d.priority ?? '一般'`),
 * 只改一边就会出现「文本是 X、颜色按 Y 算」的错配,且**不报错**。
 * 传值进来 ⇒ 颜色与文本必然同源,这类错配从结构上不可能发生。
 */
function detailSeverityOf(value: string): TagSeverity | null {
  if (value === '—') return null
  return PRIORITY_SEVERITY[value] ?? 'secondary'
}

function selectImage(i: number): void {
  activeIndex.value = i
}

watch(
  () => [props.visible, props.issueKey, props.source, sprintId.value] as const,
  async ([vis, key, , sid]) => {
    // 父弹窗一关,原图弹窗必须跟着关:它是 teleport 到 body 的独立节点,不随父弹窗卸载,
    // 少了这一句就会留下一张飘在页面上的原图(且没有任何入口能关掉它)。
    if (!vis) {
      viewerVisible.value = false
      return
    }
    if (!key) return
    loading.value = true
    loadError.value = ''
    rdm.value = null
    docDetail.value = null
    images.value = []
    activeIndex.value = 0
    viewerVisible.value = false
    try {
      if (props.source === 'DOC') {
        const [d, list] = await Promise.all([
          dataImportApi.getDocBug(key),
          dataImportApi.getDocBugImages(key),
        ])
        docDetail.value = d
        images.value = list.items
      } else {
        rdm.value = await reportsApi.getBugOne(key, sid)
      }
    } catch {
      loadError.value = isDoc.value
        ? '加载文档故障详情失败,请稍后重试'
        : '加载故障详情失败,请稍后重试'
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <Dialog
    :visible="visible"
    :header="`${isDoc ? '文档故障' : '故障'} ${issueKey ?? ''}`"
    class="ds-dialog-md ds-bugdetail"
    modal
    :pt="MAXIMIZED_DIALOG_PT"
    dismissableMask
    @update:visible="emit('update:visible', $event)"
  >
    <div v-if="loading" class="flex flex-col items-center gap-2 py-10">
      <ProgressSpinner strokeWidth="4" />
    </div>

    <div v-else-if="loadError" class="ds-empty">{{ loadError }}</div>

    <template v-else-if="isDoc ? !!docDetail : !!rdm">
      <!-- ── 左右两栏:左 = 故障信息(字段 + 长文本),右 = 「额外那一段」──
           右栏按来源二选一:RDM 只有变更记录、DOC 只有现场截图,两段互斥。

           ⚠ 用 **grid `repeat(2, 1fr)`(各 50%)** 而非 flex,且**栏数恒为 2**(右栏用
           `v-if="!isDoc"` / `v-if="isDoc"` 判"这段该不该存在",**不按 length 增删栏位**)。理由:
             · 空栏由**单元格**占着,内容不会落进去 ⇒ 左栏宽度与"有右栏"时完全相同,
               即用户要的「无内容则没有右栏,但左栏大小与有右栏时一样」;
             · `1fr auto` 不行:后者在右栏只剩一句「暂无截图」时会被内容压窄,左栏跟着变宽
               —— 版式随数据抖动。
           ⚠ 两栏间距 1.25rem:原先长文本段之间是 1rem,这里略大,免得左右两栏在视觉上粘成一块。
             改为「两栏之间的分隔线」后,这份间距由线的左右各 0.625rem 内边距带出(见样式区)。 -->
      <div class="bugdet-split">
        <div class="bugdet-main flex flex-col gap-4">
          <section class="flex flex-col gap-2">
            <h6 class="ds-section-title">故障信息</h6>
            <dl class="bugdet-grid">
              <div v-for="f in fieldItems" :key="f.label" class="bugdet-field">
                <dt>{{ f.label }}</dt>
                <dd>
                  <!-- 三态取二:f.tag 为 null ⇒ 纯文本;否则 ⇒ 胶囊。
                       空值(—)在 toItem 里就被解析成 null,故这里不会出现"写着破折号的胶囊"。 -->
                  <Tag v-if="f.tag" :severity="f.tag" :value="f.value" />
                  <span v-else>{{ f.value }}</span>
                </dd>
              </div>
            </dl>
          </section>

          <section v-for="s in longSections" :key="s.label" class="flex flex-col gap-2">
            <h6 class="ds-section-title">{{ s.label }}</h6>
            <div class="bugdet-longtext" :class="{ 'is-empty': !s.value }">{{ s.value || '—' }}</div>
          </section>
        </div>

        <!-- ── 右栏:RDM 专属 = 故障变更记录(时间线,仅 create/status,节点间标注工作日耗时)──
             文档故障没有变更记录,故这一格 `v-if="!isDoc"` 整段跳过(见文件头注释)。 -->
        <div v-if="!isDoc" class="bugdet-aside flex flex-col gap-2">
          <h6 class="ds-section-title">
            故障变更记录
            <span v-if="changelog.length" class="ds-meta">（{{ changelog.length }} 步）</span>
          </h6>

          <div v-if="!changelog.length" class="ds-empty">暂无变更记录</div>

          <!-- 外框口径与「现场截图」的主视图一致(用户 2026-09-17):同一套底/描边/圆角。
               空态刻意**不套框** —— 截图那一段也是「有图才给框,没图只剩一句空态」。 -->
          <div v-else class="bugdet-logbox">
            <Timeline :value="changelog" class="bugdet-timeline">
              <template #opposite="slotProps">
                {{ slotProps.item.change_time }}
              </template>
              <template #content="slotProps">
                {{ slotProps.item.change_detail }}（耗时{{ secondsToDuration(slotProps.item.elapsed_seconds) }}）
              </template>
            </Timeline>
          </div>
        </div>

        <!-- ── 右栏:DOC 专属 = 现场截图 ── -->
        <div v-if="isDoc" class="bugdet-aside flex flex-col gap-2">
          <h6 class="ds-section-title">
            现场截图
            <span v-if="images.length" class="ds-meta">（{{ images.length }} 张）</span>
          </h6>

          <div v-if="!images.length" class="ds-empty">暂无截图</div>

          <template v-else>
            <!-- 主视图**恒为缩略图**(单张 12~35KiB),原图只在点开图片的弹窗里取。
                 ⚠ 原先的「查看原图」按钮与「新标签打开原图」链接已按用户要求去掉:
                 原图不再有「就地铺开」这个态,于是也少了一个要跟着切图/重开一起重置的开关。
                 ⚠ 点击目标做成 <button> 而不是给 <img> 挂 click —— 按钮是语义正确的可交互元素,
                 键盘 Tab/Enter 天然可用(同 components.scss 里 .ds-timeline-hit 的做法),
                 默认外观由 .docbug-open 清零。 -->
            <div class="docbug-viewer">
              <button
                type="button"
                class="docbug-open"
                title="点击查看原图"
                @click="viewerVisible = true"
              >
                <img
                  :src="previewSrc"
                  :alt="`${issueKey} 截图 ${activeIndex + 1}`"
                  class="docbug-preview"
                />
              </button>
            </div>

            <div class="docbug-viewer-bar">
              <span class="ds-meta">{{ imageMeta }}</span>
            </div>

            <!-- 只有一张时不铺缩略图带 —— 单元素"带"只会占地方 -->
            <div v-if="images.length > 1" class="docbug-strip">
              <button
                v-for="(im, i) in images"
                :key="im.id"
                type="button"
                class="docbug-thumb"
                :class="{ 'is-active': i === activeIndex }"
                :title="`第 ${i + 1} 张 · ${im.column_label || ''}`"
                @click="selectImage(i)"
              >
                <img
                  :src="imageUrl(im, true)"
                  loading="lazy"
                  :alt="`缩略图 ${i + 1}`"
                />
                <span class="docbug-thumb-seq">{{ i + 1 }}</span>
              </button>
            </div>
          </template>
        </div>
      </div>
    </template>

    <!-- ── 原图弹窗(点主视图那张图打开)──
         嵌套 Dialog:两个弹窗都 teleport 到 body,层级由 PrimeVue 的全局 z-index 计数器决定
         (后打开的在上),不需要自己抬 z-index。
         ⚠ 这里**不**把显示状态回传给父级(不写 @update:visible → emit):关掉看图弹窗
         只应该关掉它自己;顺手把「故障详情」一起带走会让人以为是点错了关闭。
         反向那一条必须做 —— 父弹窗关闭时收起本弹窗,见 watch(它 teleport 走,
         不会随父弹窗卸载)。

         「只显示图片」(用户 2026-09-17):因而
           · 不给 `header` + `:show-header="false"` —— 标题连同页头一起消失。
             ⚠ 关闭按钮长在页头里,**去掉页头等于去掉关闭按钮**:关闭入口改由
             「点图片」承担(见 .docbug-fullview),ESC 与点遮罩仍然有效。
           · 边框 / 底色 / 阴影由 components.scss 的 .p-dialog.ds-image-viewer 去掉
             (弹窗本体是 .p-* 结构且 teleport 到 body,只能在那个全局区块覆写)。
           · 图下的元信息行(第 N/M 张 · 尺寸 · 体积)一并去掉 —— 「只显示图片」不留别的东西;
             那份信息在主视图的元信息行里仍有(同一份 imageMeta)。 -->
    <Dialog
      v-model:visible="viewerVisible"
      class="ds-dialog-lg ds-image-viewer"
      modal
      :show-header="false"
      :pt="MAXIMIZED_DIALOG_PT"
      dismissableMask
      :aria-label="`${issueKey ?? ''} 截图 ${activeIndex + 1} 原图`"
    >
      <div v-if="activeImage" class="docbug-fullview" @click="viewerVisible = false">
        <img
          :src="originalUrl"
          :alt="`${issueKey} 截图 ${activeIndex + 1} 原图`"
          class="docbug-fullimg"
        />
      </div>
    </Dialog>
  </Dialog>
</template>

<style scoped>
/* ── 左右两栏骨架 ──
   左 = 故障信息,右 = 「额外那一段」(RDM 变更记录 / DOC 现场截图)。

   ⚠ `repeat(2, 1fr)` 而非 `1fr auto`,也不要换成 flex:两栏各占 50% 是用户 2026-09-17 拍板,
   且右栏**恒定占位** —— 无内容时那一格是空的,左栏宽度与"有右栏"时完全相同
   (即用户要的「无内容则没有右栏,但左栏大小与有右栏时一样」)。
   若改成 `1fr auto`,右栏只剩一句「暂无截图」时会被内容压窄、左栏变宽 ⇒ 版式随数据抖动。
   ⚠ `min-width: 0`:grid 项默认 `min-width:auto`,内部有 `overflow:auto` 的长文本会让
   该列拒绝收缩到内容最小宽度以下(实测表现为左右栏挤出弹窗、内容被裁)。 */
.bugdet-split {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  /* 列间距为 0 —— 两栏之间的留白由**分隔线的左右内边距**带出(见 .bugdet-aside)。
     ⚠ 不能留 grid 的列 gap:gap 是「栏外的空白」,线画不进去,留了会把线推离两栏正中
       (线落在 gap 之后的右栏起点 ⇒ 左宽右窄)。列距归零后两栏各占 50%,线恰好在中线。
       行距 1.25rem 保留:两栏各 50% 时不会换行,但留着可防哪天改成单栏时上下贴死。 */
  gap: 1.25rem 0;
  align-items: start;
}

.bugdet-main,
.bugdet-aside {
  min-width: 0;
}

/* ── 两栏之间的分隔线 ──
   挂在**右栏**上,而不是在两栏中间再插一个 <div>:
   右栏是 v-if 二选一(RDM 变更记录 / DOC 现场截图),插独立元素就得跟着写两遍 v-if,
   漏一处就变成「这种来源有线、那种没有」;挂在栏上则两种来源自动都有线,无需额外判据。
   ⚠ align-self: stretch —— 容器是 align-items:start,不拉伸的话线只有右栏自身那么高,
     而右栏(尤其「暂无变更记录」时)常比左栏矮 ⇒ 线会悬在半空、不到底,看着像残线;
     拉满行高才是一条贯穿两栏的分隔线。右栏内容是顶对齐的 flex 列,被拉高不带副作用。 */
.bugdet-main {
  padding-inline-end: 0.625rem;
}

.bugdet-aside {
  padding-inline-start: 0.625rem;
  border-inline-start: 1px solid var(--ih-line);
  align-self: stretch;
}

/* 键值网格与长文本段是 RDM / 文档故障**共用**的版式,故用中性的 bugdet- 前缀
   (原 docbug- 前缀只留给截图那一段,那边确实是文档故障专有)。 */
.bugdet-grid {
  display: grid;
  /* 阈值 140px:分栏后左栏可用宽远不止 190px(见下),但**窄视口**下会掉到 ~400px,
     那时 140px 仍能排成两列;190px 则会在小屏退化成单列,16~19 个字段竖成长条。
     ⚠ 别再拿 `ds-dialog-md` 的 760px 去算左栏宽度(踩过):模板上的 `ds-dialog-md`
     只是初始尺寸,`MAXIMIZED_DIALOG_PT` 会把弹窗**强制放大**到 95vw × 95vh
     (见 src/constants/dialogPt.ts 的实测口径)。故左栏 = (95vw − 弹窗内留白 − 1.25rem) / 2。
     实测(探针 tmp-measure-labels,1440×1000):弹窗 1368 → split 1326 → 左栏 653 → 单轨 148px,4 列。
     (加分隔线后左栏内容宽再减 0.625rem + 1px ≈ 642,4 列不变 —— 140px 的阈值仍有余量。)
     全宽段列数:900/1024→2 列 · 1180/1280→3 列 · 1440/1600→4 列 · 1920→5 列;
     上述各断点**最长标签「开发负责人」(65px)均不折行**,dt/dd 也始终同行 ⇒ 140px 有余量,不必再调。 */
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.5rem 1.25rem;
  margin: 0;
}

.bugdet-field {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  min-width: 0;
}

.bugdet-field dt {
  flex: 0 0 auto;
  font-size: 0.8125rem;
  color: var(--ih-ink-muted);
}

.bugdet-field dd {
  margin: 0;
  min-width: 0;
  /* 值与名称(dt)同字号 —— 字号上的差异只该来自内容本身,不该来自排版 */
  font-size: 0.8125rem;
  color: var(--ih-ink);
  overflow-wrap: anywhere;
}

/* 优先级 Tag 要与同一行兄弟字段(纯文本 dd)的字体**完全一致** —— 不放大、不加粗。
   ⚠ 必须显式覆写,不能靠继承:Tag 的字号/字重来自主题 token
   (Aura `tag.font.size` = 0.875rem、`tag.font.weight` = 700),不随父级 font 继承 ——
   与 components.scss 里时间轴那条 `.p-tag { font-size: … }` 同源问题。
   实测该 Tag 与 dd 的字号本来就相等(都是 0.8125rem),**真正看得见的"放大"来自 700 字重**;
   两条都写出来,是为了让「与对应项一致」成为一条不随主题 token 漂移的断言。
   ⚠ font-weight 必须落到 `.p-tag` 自身(而非 `.p-tag-label`):后者继承即可拿到 400,
   且覆盖两层能让这条规则对 PrimeVue 的内部结构变化免疫。

   胶囊形(用户 2026-09-17 拍板:本弹窗内**所有**标签统一胶囊):
   用 --ih-radius-pill(999px) 这个 token,不写字面量 —— token 是唯一口径源,
   换成 9999px 就等于把"胶囊"这件事在组件里重写一遍,主题调整时不会跟着走。
   ⚠ 只挂在本弹窗的 dd 上:**不要**提到 components.scss 全局 —— 时间轴的小标签、
   表格里的状态标签各有各的形态,全局改会把它们一起变成胶囊(那些地方没人要求改)。 */
.bugdet-field dd :deep(.p-tag) {
  font-size: inherit;
  font-weight: 400;
  /* 上下内边距归零(用户 2026-09-18):与字号同理,padding 也来自主题 token
     (Aura `tag.padding` = 0.25rem 0.5rem),不随父级继承 —— 置零必须显式写在这里,
     只动块方向(上下),行方向的 0.5rem 保留。 */
  padding-block: 0;
  border-radius: var(--ih-radius-pill);
}

/* ── 长文本段(故障原因 / 描述、文档故障的 问题详述 / 原因分析 / 验证备注)──
   ⚠ 2026-09-17 撤掉 `max-height: 9rem`(用户:「下方还有区域可用,却也显示了滚动条」)。
   成因:本弹窗是 95vh 的放大态,内容区 .p-dialog-content 自带 flex:1 + overflow-y:auto,
   可用的竖向空间本来由**那一层**统一兜底;再给长文本框钉一个 9rem(144px)的天花板,
   就变成「外面明明还空着几十上百 px,框里刚过 144px 就先滚起来」—— 内外两层滚动条,
   而内层那条是凭空造出来的。
   现在高度由内容决定:短则短(不留空盒),长则跟着长;真要超出弹窗时,仍由内容区那一层
   滚动 —— 单一滚动条,层级也正确(整窗滚,而不是一小块文本自己在小窗里滚)。
   ⚠ `overflow: auto` 保留:没有高度上限时它不触发,只作窄视口/异常内容的兜底。 */
.bugdet-longtext {
  padding: 0.5rem 0.625rem;
  background: var(--ih-surface-sunken);
  border: 1px solid var(--ih-line-soft);
  border-radius: var(--ih-radius-sm);
  font-size: 0.875rem;
  color: var(--ih-ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow: auto;
}

.bugdet-longtext.is-empty {
  color: var(--ih-ink-faint);
}

/* ── 变更记录外框:与「现场截图」的主视图(.docbug-viewer)同款 ──
   用户 2026-09-17:「故障变更记录像现场截图一样,增加一个背景」⇒
   background / border / radius 三项直接对齐那一段,右栏两种来源才是同一套容器语言。
   ⚠ 空态**不套这个框**(「暂无变更记录」仍走裸的 .ds-empty):截图那边也是这么分的
     —— 有图才给主视图框,没图只剩一句「暂无截图」。别只在一侧加框。
   ⚠ `display:flex + justify-content:center` 是在**接手时间线的水平居中**:时间线原本靠
     父级(右栏列向 flex)的 align-self:center 居中;被本框包住后它不再直接是右栏的 flex 项,
     align-self 管的是竖直方向,水平居中只能由这里的 justify-content 承担。 */
.bugdet-logbox {
  display: flex;
  justify-content: center;
  padding: 0.5rem;
  background: var(--ih-surface-sunken);
  border: 1px solid var(--ih-line-soft);
  border-radius: var(--ih-radius-md);
}

/* 变更记录整块(时间 + 圆点 + 详情)在框内**水平居中**(用户 2026-09-17 要求;
   2026-09-18 复修:原先只有外框的 justify-content,**缺了收缩那一半**,居中并未真正发生)。
   ⚠ 居中是**两件事**,少一件都不成立:
       ① 外框给 `justify-content: center`(见 .bugdet-logbox);
       ② 本元素**收缩到内容宽**(下面那条 `width: fit-content`)。
     旧注释说「时间线宽度本就撑满 ⇒ margin-inline:auto 无效」—— 那是在描述**缺失 ②** 时的症状,
     不是一条该被遵守的约束:撑满时 auto 外边距与 justify-content 一样分不到剩余空间。
     补上 ② 之后两者都能居中,本项目选 `justify-content`(居中由**容器**声明,与外框同处一地)。
   ⚠ `max-width: 100%` 必须留:详情文案变长时 fit-content 会超过外框,到边即由内容换行承接。
   ⚠ 栏头「故障变更记录(N 步)」不跟着居中:它与左栏各段标题同为栏内左对齐的层级标记,
     要居中的只是时间线这一个**内容块**。 */
.bugdet-timeline {
  /* ★ 收缩到内容宽 —— 这是「整体居中」能否成立的前提,不是可选优化。
     ⚠ 少了这一条,居中是假的:实测只写 `max-width` 时本元素仍被解析成 **634px / 容器 636px**
       (铺满),外框的 justify-content:center 没有剩余空间可分,左右空隙各 1px ——
       断言「左=右」会绿灯,但视觉上整块仍贴着左边。
     ⚠⚠ `width: fit-content` **单独不够**:PrimeVue 的 `.p-timeline` 自带 `flex-grow: 1`,
       作为外框的 flex 子项它会把 fit-content 算出的宽度**再拉满**回去(实测解析值仍是 634px)。
       必须同时把 grow 归零(`flex: 0 0 auto`),收缩才真的落地。
     ⚠ max-width 必须留:详情文案变长时 fit-content 会超过外框,到边即由内容换行承接。 */
  width: fit-content;
  flex: 0 0 auto;
  max-width: 100%;
}

/* 变更记录时间线:节点之间用左右两栏(时间 | 详情),时间列定宽以免长短不一左右抖动。
   ⚠⚠ **列宽是 border-box,要按「扣掉 padding 后还剩多少」算** —— 这正是「时间被轴点挡住」的根因
      (探针 cdp-drive93 实测,1440 视口):
        · 旧值 `width: 7rem`(112px)+ 主题自带的 `padding: 0 1rem`(左右各 16px)
          ⇒ **内容宽只剩 80px**;
        · 而 `YYYY-MM-DD HH:mm:ss` 的**墨迹宽 120.19px**(0.8125rem=13px 字号下实测);
        · `white-space: nowrap` + `text-align:end` 时,溢出行不会折行、也不会往左溢出
          (负偏移被浏览器夹到 0),**整体朝右溢出到中间的轴上** ——
          实测墨迹右沿 876.19 vs 轴点左沿 852 ⇒ **压住 24.19px**(轴点本身才 18px 宽,
          相当于最后两位数字整段躺在圆点下面),竖线还再压 16.19px。
      故本块两条硬约束(改动前先拿探针复量,别再按 rem 猜):
        ① 内容宽 = `width − padding-inline-end` 必须 **> 时间戳墨迹宽**(留 ~20px 余量);
        ② `padding-inline-end` 单独承担「末字 ↔ 轴点」的间隙,**别再给左边留白** ——
           时间列是整块的最左端,左留白只会把整块撑宽、让居中的视觉中心右偏。
      现值 9.5rem(152px)− 0.75rem(12px) = **140px 内容宽**,余量 ≈ 20px,间隙 12px。
   ⚠ 别改 `width: auto / max-content` —— 各节点详情长短不一会让时间列各自为政,时间戳左右错位。 */
.bugdet-timeline :deep(.p-timeline-event-opposite) {
  flex: 0 0 auto;
  width: 9.5rem;
  padding-inline: 0 0.75rem;
  font-size: 0.8125rem;
  color: var(--ih-ink-muted);
  text-align: end;
  white-space: nowrap;
}

/* 每条记录的详情:最初(2026-09-17)按「时间轴区域的内容也要有个背景」做成小卡片;
   现去掉底色,改回纯文本 —— 时间戳与详情同落在外框底色上,不再有卡片框。
   ⚠ `align-self: flex-start`:事件行默认 stretch,不收一下内容会被拉到与左侧
     「时间戳那格」同高(时间戳列还带着主题给的 padding-bottom),下方空出一截。
   ⚠ `margin-block-end` 仍承担事件之间的分隔(原由 content 的 padding-bottom 给出,
      卡片化后那份 padding 变成卡内边距,故间距改由这条外边距补足;去掉卡片后同理保留)。 */
.bugdet-timeline :deep(.p-timeline-event-content) {
  align-self: flex-start;
  margin-block-end: 1.25rem;
  font-size: 0.875rem;
  color: var(--ih-ink);
  overflow-wrap: anywhere;
}

/* 末条不留外边距:它下面就是外框的下沿,再留一档等于框底凭空多出一截空 */
.bugdet-timeline :deep(.p-timeline-event:last-child .p-timeline-event-content) {
  margin-block-end: 0;
}

.docbug-viewer {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: 0.5rem;
  background: var(--ih-surface-sunken);
  border: 1px solid var(--ih-line-soft);
  border-radius: var(--ih-radius-md);
  overflow: auto;
}

.docbug-preview {
  display: block;
  max-width: 100%;
  /* 同时限高:截图是整屏图(实测有 2772×1458 这类宽幅,也可能出现竖版长图),
     只限宽会让竖版图把下方的元信息行与缩略图带顶到折叠线以下。限高后 img 会按比例缩放。
     ⚠ 分栏后右栏可用宽仅 ≈ 333px,且「预览 + 元信息 + 缩略图带」三行要挤在一栏里,
     故上限从 46vh/420px 收到 34vh/300px —— 否则 16:9 的截图按宽缩到 187px 高之后,
     加上元信息行(约 24px)与缩略图带(70px + 间距),整栏会顶到弹窗折叠线以下。
     ⚠ 这里是**缩略图**的尺寸口径,别拿它当原图的:"看原图"已改由点图片开弹窗承担
     (见 .docbug-fullimg),原图不在这张 333px 宽的栏里铺开。 */
  max-height: min(34vh, 300px);
  width: auto;
  height: auto;
  border-radius: var(--ih-radius-sm);
}

/* ── 原图弹窗里那张图(点主视图的图片才打开)──
   弹窗自身的边框 / 底色 / 阴影 / 页头已去掉(见 components.scss 的 .p-dialog.ds-image-viewer),
   这里只管「图片怎么摆」:
   ⚠ `inset: 0.75rem`(而不是给这一层加 padding):本项目**没有全局 box-sizing 重置**,
     content-box 下给 abs 定位的全铺层加内边距,盒子会变成「100% + 1.5rem」而被内容区裁掉。
     inset 是从包含块边缘量起的偏移,没有这个坑;顺带让图片四周留出 0.75rem 呼吸位。
   ⚠ 这一层必须**有确定高度**,下面的 max-height: 100% 才解得出来 —— 靠 `inset` 钉住即可。
     别改用 `height: 100%`:那是拿「高度由内容撑开」的父盒去解百分比,不保证成立,
     一旦解不出,原图(实测最大 2772×1458)就会按自然尺寸铺开、把图片顶出可视区。
   ⚠ 点这一层即关:页头去掉后关闭按钮一并消失(PrimeVue 的关闭按钮长在页头里),
     遮罩又只剩 95vw 之外的一圈,所以关闭入口必须落在图片上(zoom-out 光标即是提示)。 */
.docbug-fullview {
  position: absolute;
  inset: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
}

.docbug-fullimg {
  display: block;
  /* 宽高双限 ⇒ 浏览器按原比例整图缩放,宽图与竖版长图都不会溢出。
     ⚠ 原图是 1:1 的真实像素(不再有缩略图那层"发虚"的已知代价),别在这里做任何裁切。 */
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
}

/* 点击目标(主视图那张缩略图):按钮外观清零 + 放大镜光标。
   ⚠ 按钮自带 padding/border 且 font 不继承,不清零会在缩略图外多出一圈默认边框与内边距,
     那圈内边距还会连同 img 的 max-height 一起算进右栏高度。 */
.docbug-open {
  display: block;
  margin: 0;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--ih-radius-sm);
  cursor: zoom-in;
}

/* 键盘焦点环:全局那条(components.scss)只覆盖 .app-sidebar / .app-content,
   而弹窗是 teleport 到 body 的,不在那两棵子树里 —— 够不到(同 .ds-metric.is-clickable 的做法)。 */
.docbug-open:focus-visible {
  outline: 2px solid var(--ih-accent);
  outline-offset: 2px;
}

.docbug-viewer-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

/* 缩略图上限 900px、右栏只剩 ≈ 333px(不足三分之一),带上的图会明显发虚。
   ⚠⚠ 但**不能就此把 `imageUrl(im, true)` 改成拉原图**:后端 thumb 列可能为 NULL,
   且原图的用途是"点开看细节"(见 .docbug-fullview),不是铺在带上。
   发虚是分栏的已知代价,用户 2026-09-17 接受。 */
.docbug-strip {
  display: flex;
  gap: 0.5rem;
  padding-bottom: 0.25rem;
  overflow-x: auto;
}

.docbug-thumb {
  position: relative;
  flex: 0 0 auto;
  width: 112px;
  height: 70px;
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  background: var(--ih-surface-sunken);
  border: 2px solid var(--ih-line);
  border-radius: var(--ih-radius-sm);
}

.docbug-thumb.is-active {
  border-color: var(--ih-brand);
}

.docbug-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.docbug-thumb-seq {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  font-size: 0.6875rem;
  line-height: 1.35;
  color: var(--ih-ink);
  background: var(--ih-surface);
  border: 1px solid var(--ih-line);
  border-radius: var(--ih-radius-sm);
}
</style>
