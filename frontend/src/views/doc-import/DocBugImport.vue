<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useNotify } from '@/utils/notify'
import { formatDateTime } from '@/utils/datetime'
import Dialog from 'primevue/dialog'
import Select from 'primevue/select'
import Button from 'primevue/button'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Paginator, { type PageState } from 'primevue/paginator'
import Message from 'primevue/message'
import Steps from 'primevue/steps'
import FileUpload, { type FileUploadSelectEvent } from 'primevue/fileupload'
import ProgressSpinner from 'primevue/progressspinner'
import {
  dataImportApi,
  type DocBugRecord,
  type UploadResponse,
  type UploadSkipSummary,
  type ValidateResponse,
} from '@/api/dataImport'
import { reportsApi, type ProjectOption } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import BugInstanceDetailDialog from '../reports/components/BugInstanceDetailDialog.vue'

const confirm = useConfirm()
const notify = useNotify()

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// ── 已有文档故障列表的行点击 → 统一的「故障详情」──
// 这张表同样是一份故障列表(内容 = rdm_doc_bug),故与报表页的列表保持同一行为:
// 点行开详情(字段 + 现场截图)。导入后要核对截图是否真的进来了,这里是最顺手的位置。
const docDetailVisible = ref(false)
const docDetailKey = ref<string | null>(null)

function docRowClass(row: DocBugRecord): string {
  return row.key ? 'is-clickable' : ''
}

function openDocDetail(row: DocBugRecord): void {
  if (!row.key) return
  docDetailKey.value = row.key
  docDetailVisible.value = true
}

// ── 六步(2026-09-19 改版)────────────────────────────────────
// 选择项目 → 选择 Sprint → 上传文档 → 数据校验 → 检查已有数据 → 执行导入。
//
// 与「文档测试用例导入」同形,但**验证的维度不同**,别照抄它的判定:
//   那个向导的迭代归属由【需求】(故事号)反查 rdm_issue 得出,用户不选迭代;
//   这个向导的迭代是用户**显式选中**的,文档里 sprint 列与之不符的行全部跳过。
//
// 上一版是三步(选择项目 → 上传文件 → 完成导入),校验与「已有数据」都塞在上传步里。
// 改成六步的理由不是"步骤越多越清楚",而是"选择迭代"这一步把导入范围从整个项目
// 收窄到了单个迭代:范围变了,校验结论、已有数据的清单、清空的边界都得跟着变,
// 塞在一个步骤里已经说不清"这个数字是对谁成立的"。
const currentStep = ref(1)
const stepItems = ref([
  { label: '选择项目' },
  { label: '选择 Sprint' },
  { label: '上传文档' },
  { label: '数据校验' },
  { label: '检查已有数据' },
  { label: '执行导入' },
])

// ── 第 1 步:选择项目 ──────────────────────────────────────────
const projects = ref<ProjectOption[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedJiraProjectId = ref<string>('')
const selectedProjectName = ref<string>('')
const loadingProjects = ref(false)

// ── 第 2 步:选择 Sprint ───────────────────────────────────────
/**
 * 候选来自 GET /data-import/sprints/{id},**只有 state='closed' 的迭代**(用户 2026-09-19 拍板)。
 * ⚠ 统一 String() 归一化:库里 sprint_id 是 varchar(50),但不保证每个环境都由 pymysql
 *   还原成 str —— 一旦这里混进 number,与后端回显的 sprint_id 做全等比较就会静默不等。
 */
const sprints = ref<{ sprint_id: string; sprint_name: string }[]>([])
const selectedSprintId = ref<string>('')
const loadingSprints = ref(false)

const selectedSprintName = computed(() => {
  const hit = sprints.value.find(s => s.sprint_id === selectedSprintId.value)
  return hit?.sprint_name || selectedSprintId.value || ''
})

// ── 第 3 步:上传文档 ──────────────────────────────────────────
/** 已选中的文件 —— 第 4 步校验与第 6 步导入都用它,不必让用户重选一次。 */
const pendingFile = ref<File | null>(null)
/**
 * 文件控件的实例 —— 后缀不合规时要把控件内部那份选择清掉。
 *
 * ⚠ 控件受控于自己那份 files 列表:只 reject 不收下,界面上会留着一个"幽灵文件",
 *   而按钮区仍是「选择文件」,看起来什么都没选中 —— 用户会以为是自己没点到。
 * ⚠ 类型只能就地声明:PrimeVue 4.5.5 把 `clear()` 声明进了 **emits** 接口
 *   (node_modules/primevue/fileupload/index.d.ts:621),`FileUploadMethods` 只有 `upload()`,
 *   因此 `InstanceType<typeof FileUpload>` 推不出 clear(实测 TS2339)。
 */
const fileUploadRef = ref<{ clear: () => void } | null>(null)

// ── 第 4 步:数据校验 ──────────────────────────────────────────
// 校验(只读、不写库)与导入拆成两步:报告是给人看的,导入要人点头。
// 理由见 api/dataImport.ts 的 validateDocBugs 注释:上传是宽容的,一旦点了就在写库,
// 用户想改只能清空重来;校验把同一套判定提前摊开,零副作用、可反复调。
const validating = ref(false)
const validateResult = ref<ValidateResponse | null>(null)
/** 校验报告的展开/收起:行级明细默认收起,先给结论再给证据。 */
const showValidateDetail = ref(false)

// ── 第 5 步:检查已有数据 ──────────────────────────────────────
/**
 * 已有数据按**所选迭代**取,不是整个项目(getDocBugs 的 sprintId 参数)。
 * 这与第 2 步的收窄是同一件事的两面:范围既然是"这个迭代",清单和"先清空"的
 * 边界就必须也是它 —— 否则导迭代 B 时点一下清空会把刚导好的迭代 A 一起删掉。
 */
const existingData = ref<DocBugRecord[]>([])
const existingTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loadingData = ref(false)

// ── 第 6 步:执行导入 ──────────────────────────────────────────
const uploading = ref(false)
const importResult = ref<UploadResponse | null>(null)

/** 有可导入行时,把结论与行级明细分成两段展示 */
const validateIssues = computed(() => {
  const v = validateResult.value
  if (!v) return []
  return Object.entries(v.invalid_detail)
    .sort((a, b) => b[1] - a[1])
    .map(([field, count]) => `[${field}] 未通过：${count} 行`)
})

/**
 * 跳过原因 → 展示行。校验报告与导入结果共用(两边都是后端同一套分桶)。
 *
 * ⚠ 「不属于所选迭代」排在最前:本次流程下它是最常被问起的一条 —— 一份表里
 *   属于别的迭代的行本来就该被跳过,用户第一眼要看的是"跳了多少、都去哪了"。
 */
function skipRowsOf(s?: UploadSkipSummary) {
  if (!s) return []
  return [
    {
      label: '不属于本次所选迭代',
      count: s.other_sprint,
      hint: `这些行属同一项目下的其它迭代，换成对应迭代再导一次`,
    },
    { label: '未标注 sprint', count: s.no_sprint, hint: '在表里补上「sprint」列的值即可参与导入' },
    { label: '属于其它项目', count: s.other_project, hint: '换成对应项目再导一次' },
    { label: '匹配不到同名迭代', count: s.unknown_sprint, hint: '核对 rdm_sprint 里的迭代名' },
    { label: '字段校验未通过', count: s.invalid, hint: '见下方行号明细' },
    { label: '删除线废弃行', count: s.strikethrough, hint: '维护方标掉的，按约定忽略' },
  ].filter(r => (r.count ?? 0) > 0)
}

const validateSkipRows = computed(() => skipRowsOf(validateResult.value?.skipped))
const importSkipRows = computed(() => skipRowsOf(importResult.value?.skipped))

/**
 * 「校验通过几条 / 实际写入几条」的差额说明。
 *
 * 两条口径**本来就不同源**（这不是 bug,是拍板过的取舍):校验走 strict(6 个必填列),
 * 导入走宽松(只要求编号与问题详述齐全)。于是缺优先级/处理人那类行会「校验拦下、导入放行」,
 * 实测同一份表可以是 2 条 vs 42 条。此前按钮直接写「确认导入 {校验通过数} 条」,
 * 等于把一个刻意不精确的数当承诺;现在改成:按钮不带数,差额在结果页说清楚。
 */
const strictVsWritten = computed(() => {
  const r = importResult.value
  const checked = validateResult.value?.importable
  if (!r?.success || checked == null) return ''
  const written = r.imported ?? 0
  if (written === checked) return `与校验通过的 ${checked} 条一致。`
  if (written > checked) {
    return `校验通过 ${checked} 条，实际写入 ${written} 条：多出的 ${written - checked} 条是`
      + '「校验未通过但导入侧放行」的行(导入侧只要求编号与问题详述齐全)。'
  }
  // 反向差额虽然少见但确实可能:校验与导入之间 rdm_sprint 会被同步任务全量重写,
  // 迭代没了或换了项目,那一行就不再属于本次范围(见后端 upload_doc_bugs 的说明)。
  return `校验通过 ${checked} 条，实际写入 ${written} 条：少了 ${checked - written} 条 —— `
    + '校验之后库里的迭代归属可能被同步任务改过，也可能该行已不属于本项目的范围。'
})

/** 截图入库结论(张数 / 体积 / 耗时)。后端回了这些字段,此前一条都没展示。 */
const imageSummary = computed(() => {
  const r = importResult.value
  const n = r?.images ?? 0
  if (!r?.success || !n) return ''
  const mib = ((r.images_total_bytes ?? 0) / 1024 / 1024).toFixed(1)
  const secs = r.image_seconds ? `，耗时 ${r.image_seconds}s` : ''
  return `${n} 张（${mib} MiB${secs}）`
})

/**
 * 锚点统计 —— 只在有锚点可解释时给一行。
 * 为什么值得显示:实测 395 个锚点最终只入库 54 张(其余属别的项目/无 sprint 的行),
 * 没有这行数字时用户的第一反应是「截图导入漏了」。
 */
const imageStatsLine = computed(() => {
  const s = importResult.value?.image_stats
  if (!s?.anchors_total) return ''
  return [
    `锚点 ${s.anchors_total}`,
    `入库 ${s.images_yielded ?? 0}`,
    `非本次导入行 ${s.skipped_row_not_imported ?? 0}`,
    `列越界 ${s.skipped_unknown_column ?? 0}`,
    `媒体缺失 ${s.skipped_no_media ?? 0}`,
  ].join(' · ')
})

async function loadProjects() {
  loadingProjects.value = true
  try {
    projects.value = await reportsApi.getProjects()
  } finally {
    loadingProjects.value = false
  }
}

/** 换项目 = 后面所有步骤的结论全部失效,一律清空重来(含已选的迭代)。 */
async function onProjectChange(projectId: number | null) {
  selectedSprintId.value = ''
  sprints.value = []
  resetFromFile()

  if (projectId == null) {
    selectedJiraProjectId.value = ''
    selectedProjectName.value = ''
    return
  }
  const project = projects.value.find(p => p.id === projectId)
  selectedJiraProjectId.value = project?.project_id || ''
  selectedProjectName.value = project?.project_name || ''

  await loadSprints()
}

async function loadSprints() {
  if (selectedProjectId.value == null) return
  loadingSprints.value = true
  try {
    const res = await dataImportApi.getClosedSprints(selectedProjectId.value)
    sprints.value = res.map(s => ({
      sprint_id: String(s.sprint_id),
      // 迭代名缺失时回落到 id,免得下拉里是一行空白、点下去还不知道选了啥
      sprint_name: s.sprint_name || `#${s.sprint_id}`,
    }))
  } finally {
    loadingSprints.value = false
  }
}

/** 换迭代 = 本次范围变了,文件与所有下游结论一并作废。 */
function onSprintChange() {
  resetFromFile()
}

/** 清掉「文件 → 校验 → 已有数据 → 导入结果」这条链上的一切 */
function resetFromFile() {
  pendingFile.value = null
  validateResult.value = null
  showValidateDetail.value = false
  existingData.value = []
  existingTotal.value = 0
  currentPage.value = 1
  importResult.value = null
}

async function loadExistingData() {
  if (!selectedJiraProjectId.value || !selectedSprintId.value) return

  loadingData.value = true
  try {
    const res = await dataImportApi.getDocBugs(
      selectedJiraProjectId.value,
      currentPage.value,
      pageSize.value,
      selectedSprintId.value
    )
    existingData.value = res.items
    existingTotal.value = res.total
  } finally {
    loadingData.value = false
  }
}

function onPage(e: PageState) {
  currentPage.value = e.page + 1
  pageSize.value = e.rows
  loadExistingData()
}

function handleReimport() {
  confirm.require({
    message: `将清空「${selectedProjectName.value}」下「${selectedSprintName.value}」的 `
      + `${existingTotal.value} 条文档故障（其它迭代的数据不受影响），是否继续？`,
    header: '确认重新导入',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '确认',
    rejectLabel: '取消',
    accept: async () => {
      const res = await dataImportApi.clearDocBugs(
        selectedJiraProjectId.value,
        selectedSprintId.value
      )
      notify('success', `已清空 ${res.deleted} 条`)
      existingData.value = []
      existingTotal.value = 0
      currentPage.value = 1
      importResult.value = null
    },
  })
}

/**
 * 第 3 步只**收下文件**,不读表。
 *
 * 这里刻意不做"选完就顺带校验":校验要完整解析这份含 390 张内嵌截图、实测 297MB 的表,
 * 做两遍等于让用户多等一遍。文件先存着,第 4 步由用户点「开始校验」再跑一次,
 * 第 6 步导入复用同一个 File 对象 —— 全程只解析一次(后端 spool 到临时文件的成本另算)。
 *
 * ⚠ 2026-09-19:控件上的 uploadLabel/cancelLabel 两个按钮已删,收文件的时机随之从「点确定」
 *   前移到「选中文件」—— 第 3 步的语义收敛成「选文件 → 点下一步」:选中即收下(收下本身没有
 *   副作用,只是把 File 存起来),「下一步」才是确认,关闭弹窗就是取消。
 *   本函数原本就不跳步(不同于测试用例那份),所以这里只需换事件源。
 */
function onPickFile(event: FileUploadSelectEvent) {
  const rawFiles = event.files as File | File[] | undefined
  const file = Array.isArray(rawFiles) ? rawFiles[0] : rawFiles
  // 用户打开系统文件框又取消 ⇒ files 为空。这不是错误,不该弹警告。
  if (!file) return
  // ⚠ 只认 .xlsx(2026-09-17):解析用的是 openpyxl,它**读不了** OLE2 的老版 .xls ——
  //   此前这里与后端都放行 .xls,用户选到 .xls 会拿到一个 500「处理文件失败」。
  //   收起后缀白名单比事后解释便宜;大小写不敏感(浏览器 accept 本来就忽略大小写,
  //   此前的大小写敏感正则会把 `A.XLSX` 误判成"不支持的格式")。
  if (!/\.xlsx$/i.test(file.name)) {
    notify('warn', '仅支持 .xlsx（Excel 2007+）；老版 .xls 请先另存为 .xlsx')
    fileUploadRef.value?.clear()
    return
  }

  resetFromFile()
  pendingFile.value = file
}

/** 第 4 步:跑校验。只读不写库,可反复调。 */
async function runValidate() {
  const file = pendingFile.value
  if (!file || !selectedSprintId.value) return

  validateResult.value = null
  showValidateDetail.value = false
  validating.value = true
  try {
    const res = await dataImportApi.validateDocBugs(
      selectedJiraProjectId.value,
      selectedSprintId.value,
      file
    )
    validateResult.value = res

    if (res.valid) {
      notify('success', `校验通过：${res.importable} 条可导入`)
    } else {
      notify('warn', '校验未通过，请查看下方原因')
    }
  } finally {
    validating.value = false
  }
}

/** 第 6 步:用户确认校验报告后 → 真正写库。 */
async function runImport() {
  const file = pendingFile.value
  if (!file) return

  uploading.value = true
  try {
    const res = await dataImportApi.uploadDocBugs(
      selectedJiraProjectId.value,
      selectedSprintId.value,
      file
    )
    importResult.value = res

    if (res.success) {
      notify('success', `成功导入 ${res.imported} 条数据`)
    } else {
      // ⚠ 用 error 而不是 warn:这一次是真的一条都没进库,结论块也按 error 渲染
      // (页面上必须与「成功」有肉眼可辨的区别,不能只靠用户读数字)。
      notify('error', '没有导入任何数据，请查看下方原因')
    }
  } finally {
    uploading.value = false
  }
}

/** 校验没过 / 想改文件 → 回第 3 步重选 */
function reselectFile() {
  pendingFile.value = null
  validateResult.value = null
  showValidateDetail.value = false
}

function handleReset() {
  currentStep.value = 1
  selectedProjectId.value = null
  selectedJiraProjectId.value = ''
  selectedProjectName.value = ''
  selectedSprintId.value = ''
  sprints.value = []
  resetFromFile()
}

function handleClose() {
  handleReset()
  emit('close')
}

// 时间展示统一走 @/utils/datetime。原先的本地实现是字符串替换 + 切片,
// 与其它页面输出格式不一致(且无法处理时区)。
function formatTime(val: string | null) {
  return formatDateTime(val)
}

// 第 5 步的数据在**进入该步时**才拉:它依赖第 2 步选定的迭代,提前拉会拿到别的迭代的清单。
watch(currentStep, (step) => {
  if (step === 5) loadExistingData()
})

watch(() => props.visible, (val) => {
  if (val) {
    loadProjects()
  }
})
</script>

<template>
  <Dialog
    :visible="visible"
    header="文档故障导入"
    class="ds-dialog-lg"
    modal
    :dismissableMask="false"
    @update:visible="!$event && handleClose()"
  >
    <div class="flex flex-col gap-6">
      <Steps :model="stepItems" :activeStep="currentStep - 1" :readonly="true" />

      <div class="flex flex-col gap-4">
        <!-- ── 1. 选择项目 ── -->
        <div v-if="currentStep === 1" class="flex flex-col gap-4">
          <div class="flex flex-col gap-2">
            <label class="ds-meta" for="import-project">选择项目</label>
            <Select
              v-model="selectedProjectId"
              inputId="import-project"
              :options="projects"
              optionLabel="project_name"
              optionValue="id"
              placeholder="请选择项目"
              :loading="loadingProjects"
              @change="onProjectChange($event.value)"
            />
          </div>
          <Message severity="info" :closable="false">
            导入源是「问题明细表」整张表：每行的迭代归属取自表内的 <b>sprint</b> 列，
            只导入属于所选项目、且属于所选迭代的行，其余行会被跳过并在结果里列出原因。
            一份表可以含多个迭代，按迭代分几次导入即可。
          </Message>
          <div class="flex justify-end gap-2 pt-4">
            <Button label="下一步" :disabled="!selectedProjectId" @click="currentStep = 2" />
          </div>
        </div>

        <!-- ── 2. 选择 Sprint ── -->
        <div v-if="currentStep === 2" class="flex flex-col gap-4">
          <div class="flex flex-col gap-2">
            <label class="ds-meta" for="import-sprint">选择 Sprint</label>
            <Select
              v-model="selectedSprintId"
              inputId="import-sprint"
              :options="sprints"
              optionLabel="sprint_name"
              optionValue="sprint_id"
              placeholder="请选择迭代"
              :loading="loadingSprints"
              :disabled="!selectedJiraProjectId"
              @change="onSprintChange()"
            />
          </div>

          <Message v-if="!loadingSprints && selectedJiraProjectId && !sprints.length"
            severity="warn" :closable="false">
            该项目下没有<b>已关闭</b>的迭代，无法按迭代导入。
            请确认 rdm_sprint 是否已同步该项目的数据。
          </Message>
          <Message v-else severity="info" :closable="false">
            本次导入范围 = <b>{{ selectedProjectName }}</b> × 所选迭代。
            下拉里只有<b>已关闭</b>的迭代；文档中 sprint 列是别的迭代的行一律跳过。
          </Message>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 1" />
            <Button label="下一步" :disabled="!selectedSprintId" @click="currentStep = 3" />
          </div>
        </div>

        <!-- ── 3. 上传文档 ── -->
        <div v-if="currentStep === 3" class="flex flex-col gap-4">
          <Message severity="info" :closable="false">
            上传 Excel（<b>.xlsx</b>，Excel 2007+；老版 .xls 请先另存为 .xlsx），需包含<b>问题明细表</b>的列：自动编号、优先级、处理人、处理状态、处理方式、功能点、问题详述、创建日期、sprint、故事号、问题类别、原因分析、处理意见、解决日期
          </Message>
          <Message severity="warn" :closable="false">
            本次只导入迭代为 <b>{{ selectedSprintName }}</b> 的行：
            表内 <b>sprint</b> 列写的是其它迭代的行会被跳过，并在下一步的校验报告里按原因列出。
            迭代名允许有空格/连字符/大小写的差异（按归一化后比对）。
          </Message>

          <!-- 只有「选择文件」一个按钮:选中即收下,确认交给下方「下一步」,取消交给弹窗关闭 -->
          <FileUpload
            v-if="!pendingFile"
            ref="fileUploadRef"
            customUpload
            :multiple="false"
            accept=".xlsx"
            chooseLabel="选择文件"
            :showUploadButton="false"
            :showCancelButton="false"
            :disabled="validating || uploading"
            @select="onPickFile"
          />

          <div v-else class="flex items-center justify-between gap-4">
            <span class="ds-meta">已选择：{{ pendingFile.name }}</span>
            <Button label="重新选择" severity="secondary" text size="small" @click="reselectFile" />
          </div>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 2" />
            <Button label="下一步" :disabled="!pendingFile" @click="currentStep = 4" />
          </div>
        </div>

        <!-- ── 4. 数据校验 ── -->
        <div v-if="currentStep === 4" class="flex flex-col gap-4">
          <p v-if="pendingFile" class="ds-meta">待校验文件：{{ pendingFile.name }}</p>

          <div v-if="validating" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在校验，含大量内嵌截图的表格需要一些时间…</span>
          </div>

          <template v-if="!validateResult && !validating">
            <Message severity="info" :closable="false">
              校验<b>只读不写库</b>，可反复执行。它会按「所选项目 ∩ 所选迭代
              （{{ selectedSprintName }}）」筛出本次范围内的行，再逐行检查必填字段；
              范围之外的行只统计、不判错。
            </Message>
            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 3" />
              <Button label="开始校验" :disabled="!pendingFile" @click="runValidate" />
            </div>
          </template>

          <!-- ── 校验报告 ── -->
          <template v-if="validateResult">
            <Message
              :severity="validateResult.valid ? 'success' : 'error'"
              :closable="false"
            >
              <template v-if="validateResult.valid">
                校验通过：<b>{{ validateResult.importable }}</b> 条可导入（共读取
                {{ validateResult.total_count }} 行）
              </template>
              <template v-else-if="!validateResult.header_ok">
                表头校验未通过，文件无法用于导入
              </template>
              <template v-else>
                校验未通过：<b>{{ selectedSprintName }}</b> 范围内没有可导入的行（共读取
                {{ validateResult.total_count }} 行）
              </template>
            </Message>

            <p v-if="validateResult.sprints.length" class="ds-meta">
              本次导入范围：<b>{{ selectedSprintName }}</b> —— 命中
              {{ validateResult.sprints[0].count }} 行
            </p>

            <div v-if="validateSkipRows.length" class="flex flex-col gap-2">
              <p class="ds-meta">已跳过（不在本次范围内）</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="row in validateSkipRows" :key="row.label">
                  {{ row.label }}：{{ row.count }} 条<span class="ml-1">（{{ row.hint }}）</span>
                </li>
              </ul>
            </div>

            <div v-if="validateIssues.length" class="flex flex-col gap-2">
              <p class="ds-meta">未通过的原因</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="(line, idx) in validateIssues" :key="idx">{{ line }}</li>
              </ul>
            </div>

            <!-- 行级明细默认收起:结论先给,证据按需展开。
                 一屏铺 50 条行号会把人淹掉,而"要不要回源头改表"这个决定
                 靠的是上面那几行聚合数字。 -->
            <div v-if="validateResult.errors.length" class="flex flex-col gap-2">
              <Button
                :label="showValidateDetail ? '收起行级明细' : `查看行级明细（${validateResult.errors.length} 条）`"
                severity="secondary"
                text
                size="small"
                class="self-start"
                @click="showValidateDetail = !showValidateDetail"
              />
              <ul v-if="showValidateDetail" class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="(err, idx) in validateResult.errors" :key="idx">{{ err }}</li>
              </ul>
            </div>

            <p class="ds-meta">
              导入侧的判定比校验宽松(只要求编号与问题详述齐全),实际写入数可能多于校验通过的
              {{ validateResult.importable }} 条，以导入结果页的数字为准。
            </p>

            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 3" />
              <Button label="换个文件" severity="secondary" @click="reselectFile" />
              <Button
                label="下一步"
                :disabled="!validateResult.valid"
                @click="currentStep = 5"
              />
            </div>
          </template>
        </div>

        <!-- ── 5. 检查已有数据 ── -->
        <div v-if="currentStep === 5" class="flex flex-col gap-4">
          <div v-if="loadingData" class="flex flex-col items-center gap-2 py-8">
            <ProgressSpinner strokeWidth="4" />
          </div>

          <template v-else-if="existingTotal > 0">
            <Message severity="warn" :closable="false">
              「{{ selectedProjectName }}」下「<b>{{ selectedSprintName }}</b>」已有
              {{ existingTotal }} 条文档故障（点击任意一行查看详情）。
              直接导入不会清空它们，只会按<b>编号</b>覆盖同一条。
            </Message>
            <DataTable
              :value="existingData"
              :loading="loadingData"
              class="ds-table"
              :row-class="docRowClass"
              @row-click="openDocDetail($event.data)"
            >
              <Column field="key" :header="TH.code" class="ds-nowrap" />
              <Column field="name" :header="TH.name" />
              <Column field="priority" :header="TH.priority" class="ds-nowrap" />
              <Column field="maker" :header="TH.maker" class="ds-nowrap" />
              <Column field="status" :header="TH.status" class="ds-nowrap" />
              <Column field="sprint_name" :header="TH.sprint" class="ds-nowrap" />
              <Column :header="TH.createdAt" class="ds-nowrap">
                <template #body="{ data }">
                  {{ formatTime(data.propose_time) }}
                </template>
              </Column>
            </DataTable>
            <div>
              <Paginator
                :first="(currentPage - 1) * pageSize"
                :rows="pageSize"
                :totalRecords="existingTotal"
                template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink"
                currentPageReportTemplate="共 {totalRecords} 条"
                @page="onPage"
              />
            </div>
            <div class="flex justify-end">
              <Button label="重新导入（先清空本迭代）" severity="warn" @click="handleReimport" />
            </div>
          </template>

          <Message v-else severity="success" :closable="false">
            「{{ selectedProjectName }}」下「{{ selectedSprintName }}」暂无文档故障数据，直接导入即可。
          </Message>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 4" />
            <Button label="下一步" @click="currentStep = 6" />
          </div>
        </div>

        <!-- ── 6. 执行导入 ── -->
        <div v-if="currentStep === 6" class="flex flex-col gap-4">
          <Message v-if="!importResult" severity="info" :closable="false">
            将把「{{ selectedProjectName }}」下迭代为 <b>{{ selectedSprintName }}</b> 的行写入
            <b>rdm_doc_bug</b>，其余行照旧跳过（见上一步的校验报告）。
          </Message>

          <div v-if="uploading" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在写入数据库，含大量内嵌截图的表格需要一些时间…</span>
          </div>

          <template v-if="importResult">
            <!-- 结论块分两态:一条没进库时**不能**再渲染成绿色的「成功导入 0 条数据」——
                 失败态以前就是这么被显示出来的(颜色与措辞都与事实相反)。 -->
            <Message :severity="importResult.success ? 'success' : 'error'" :closable="false">
              <template v-if="importResult.success">
                成功导入 {{ importResult.imported || 0 }} 条数据（共读取
                {{ importResult.total_count || 0 }} 行）
              </template>
              <template v-else>
                没有导入任何数据：共读取 {{ importResult.total_count || 0 }} 行，全部被跳过或未通过校验，
                原因见下方
              </template>
            </Message>

            <p v-if="strictVsWritten" class="ds-meta">{{ strictVsWritten }}</p>

            <div v-if="importResult.sprints?.length" class="flex flex-col gap-2">
              <p class="ds-meta">写入的迭代</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="s in importResult.sprints" :key="s.sprint_id">
                  {{ s.sprint_name || s.sprint_id }}：{{ s.count }} 条
                </li>
              </ul>
            </div>

            <!-- ── 现场截图这一段以前完全没展示 ──
                 后端回了 images / images_total_bytes / image_seconds / image_stats /
                 image_error / image_skipped 六个字段,前端只声明了类型、没有任何消费方:
                 截图写库失败或整段被跳过时,用户只看到「成功导入 N 条」,只能事后逐个点开
                 详情才发现没图 —— 而本页开头那条注释恰恰写着"导入后要核对截图是否真的进来了"。
                 三态互斥(按后端 _sync_doc_bug_images 的分支):有错 / 有跳过 / 有入库。 -->
            <div v-if="importResult.success" class="flex flex-col gap-2">
              <p class="ds-meta">现场截图</p>
              <Message
                :severity="importResult.image_error ? 'error' : (importResult.image_skipped ? 'warn' : 'info')"
                :closable="false"
              >
                <template v-if="importResult.image_error">
                  截图导入失败：{{ importResult.image_error }}（上面的业务数据已入库，未一并回滚）
                </template>
                <template v-else-if="imageSummary">已入库 {{ imageSummary }}</template>
                <template v-else>
                  {{ importResult.image_skipped || '本次没有可入库的截图' }}
                </template>
              </Message>
              <p v-if="imageStatsLine" class="ds-meta">锚点统计：{{ imageStatsLine }}</p>
            </div>

            <div v-if="importSkipRows.length" class="flex flex-col gap-2">
              <p class="ds-meta">已跳过</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="row in importSkipRows" :key="row.label">
                  {{ row.label }}：{{ row.count }} 条<span class="ml-1">（{{ row.hint }}）</span>
                </li>
              </ul>
            </div>

            <div v-if="importResult.errors?.length" class="flex flex-col gap-2">
              <p class="ds-meta">明细</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="(err, idx) in importResult.errors" :key="idx">
                  {{ err }}
                </li>
              </ul>
            </div>
          </template>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 5" />
            <Button
              v-if="!importResult"
              label="开始导入"
              :disabled="uploading"
              @click="runImport"
            />
            <Button v-if="importResult?.success" label="再导一次" @click="currentStep = 3" />
            <!-- 本步不再给「关闭」按钮:右上角 × 与 Esc 都经 @update:visible 落到同一个 handleClose
                 (含 handleReset),按钮只是重复一遍同一件事。 -->
          </div>
        </div>
      </div>
    </div>

    <!-- 统一的「故障详情」(字段 + 现场截图)。组件虽挂在本导入弹窗内，
         但自 2026-09-19 起渲染为**非模态右侧抽屉**、teleport 到 body ——
         ⚠ 故层级**不由 DOM 顺序决定**，而是 PrimeVue 每次开浮层向全局计数器取号（后开的更大）。
         抽屉非模态 ⇒ 底下的导入弹窗仍可点，两边互不遮挡。 -->
    <BugInstanceDetailDialog
      v-model:visible="docDetailVisible"
      source="DOC"
      :issue-key="docDetailKey"
    />
  </Dialog>
</template>
