<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useNotify } from '@/utils/notify'
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
  type TestcaseRecord,
  type TestcaseReport,
} from '@/api/dataImport'
import { reportsApi, type ProjectOption } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'

const confirm = useConfirm()
const notify = useNotify()

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

/**
 * 五步(2026-09-18 二改):选择项目 → 上传文档 → 数据校验 → 检查已有数据 → 执行导入。
 *
 * ⚠ 与一改的最大区别:**不再让用户手选 Sprint**。测试用例在 Jira 侧不挂迭代,但每行都有
 *   【需求】(故事号),而故事号经 rdm_issue 能确定它现在所在的迭代 —— 迭代归属因此由
 *   数据自己决定,而不是由界面上的一个下拉框决定。
 * ⚠ 「数据校验」这一步不是装饰:故事号解析不到(未同步)时后端**整份拒绝**,必须在写库
 *   之前就把这个结论摊给用户,否则他会拿到一个「成功导入 0 条」的黑箱。
 */
const currentStep = ref(1)
const stepItems = ref([
  { label: '选择项目' },
  { label: '上传文档' },
  { label: '数据校验' },
  { label: '检查已有数据' },
  { label: '执行导入' },
])

const projects = ref<ProjectOption[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedJiraProjectId = ref<string>('')
const selectedProjectName = ref<string>('')
const loadingProjects = ref(false)

/** 用户在「上传文档」选中的文件 —— 校验与导入都用它(不必让用户再选一次) */
const pendingFile = ref<File | null>(null)
/**
 * 文件控件的实例 —— 后缀不合规时要把控件内部那份选择清掉。
 *
 * ⚠ 控件是受控自己那份 files 列表的:只 reject 不收下,界面上会留着一个"幽灵文件",
 *   而按钮区仍是「选择文件」,看起来什么都没选中 —— 用户会以为是自己没点到。
 * ⚠ 类型只能就地声明:PrimeVue 4.5.5 把 `clear()` 声明进了 **emits** 接口
 *   (node_modules/primevue/fileupload/index.d.ts:621),`FileUploadMethods` 只有 `upload()`,
 *   因此 `InstanceType<typeof FileUpload>` 推不出 clear(实测 TS2339)。
 */
const fileUploadRef = ref<{ clear: () => void } | null>(null)
const validating = ref(false)
const validateResult = ref<TestcaseReport | null>(null)

const existingData = ref<TestcaseRecord[]>([])
const existingTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loadingData = ref(false)

const uploading = ref(false)
const importResult = ref<TestcaseReport | null>(null)

/** 迭代状态的中文名 —— 校验报告里要让人一眼看出这个迭代是不是还在进行 */
const SPRINT_STATE_LABEL: Record<string, string> = {
  active: '进行中',
  closed: '已结束',
  future: '未开始',
}

/** 文档里解析出的故事号 —— 「检查已有数据」与「清空」都按它收窄范围 */
const storyKeys = computed(() => (validateResult.value?.stories ?? []).map(s => s.story_key))

/** 故事号 → 迭代归属(校验报告的核心内容) */
const storyRows = computed(() => validateResult.value?.stories ?? [])

/** 入库行数 − 用例数:差额是「一个用例引用多个故事」展开出来的,不是重复导入 */
const expandNote = computed(() => {
  const r = importResult.value
  if (!r) return ''
  const written = r.imported ?? 0
  const cases = r.case_count ?? 0
  if (written === cases) return `共 ${cases} 个用例，每个引用 1 个故事，入库 ${written} 行。`
  return `共 ${cases} 个用例，其中引用多个故事的被展开成多行，故入库 ${written} 行。`
})

/** 读取的行数 vs 归并出的用例数 —— 源文档里一个用例占「首行 + N 行步骤」 */
function mergeNote(r: TestcaseReport | null) {
  if (!r) return ''
  return `源文档 ${r.total_rows ?? 0} 行 → 归并出 ${r.case_count ?? 0} 个用例（含步骤 ${r.step_count ?? 0} 条）`
}

const skipRows = computed(() => {
  const s = importResult.value?.skipped
  if (!s) return []
  return [
    {
      label: '关键字为空且不是步骤行',
      count: s.no_case_key,
      hint: '既不是用例首行也不是步骤行，无法归属',
    },
    {
      label: '步骤行出现在任何用例之前',
      count: s.orphan_step,
      hint: '没有可挂靠的用例，多半是首行被删掉了',
    },
    { label: '空的步骤行（只有步骤ID）', count: s.empty_step, hint: '没有步骤内容，未计入步骤数' },
  ].filter(r => r.count > 0)
})

async function loadProjects() {
  loadingProjects.value = true
  try {
    projects.value = await reportsApi.getProjects()
  } finally {
    loadingProjects.value = false
  }
}

/** 换项目 = 一切都失效:校验结论是「这份文件对这个项目」的判断,导入结果更是不能跨项目留 */
function resetAll() {
  pendingFile.value = null
  validateResult.value = null
  importResult.value = null
  existingData.value = []
  existingTotal.value = 0
  currentPage.value = 1
}

async function onProjectChange(projectId: number | null) {
  resetAll()
  if (projectId == null) {
    selectedJiraProjectId.value = ''
    selectedProjectName.value = ''
    return
  }
  const project = projects.value.find(p => p.id === projectId)
  selectedJiraProjectId.value = project?.project_id || ''
  selectedProjectName.value = project?.project_name || ''
}

/**
 * 「上传文档」这一步只是把文件收下 —— 真正的判定在第 3 步,用户点了才跑。
 *
 * ⚠ 2026-09-19:收文件的时机从「点确定」前移到「选中文件」。控件上的 uploadLabel/cancelLabel
 *   两个按钮已删 —— 第 2 步的语义收敛成「选文件 → 点下一步」:选中即收下(收下本身没有副作用,
 *   只是把 File 存起来),「下一步」才是确认,关闭弹窗就是取消。
 *   也因此这里不再 `currentStep = 3`:跳步是原来那个「确定,去校验」按钮的行为,
 *   留着它「下一步」就永远点不到,等于把确认动作藏回了那个按钮里。
 */
function onPickFile(event: FileUploadSelectEvent) {
  const rawFiles = event.files as File | File[] | undefined
  const file = Array.isArray(rawFiles) ? rawFiles[0] : rawFiles
  // 用户打开系统文件框又取消 ⇒ files 为空。这不是错误,不该弹警告。
  if (!file) return
  // ⚠ 只认 .csv(与后端 _require_csv 同口径)。这份导出是 CSV;用户若在 Excel 里另存过,
  //   后缀会变成 .xlsx,那种文件这里不接 —— 直接说清要什么,比事后回一个 400 便宜。
  if (!/\.csv$/i.test(file.name)) {
    notify('warn', '仅支持 .csv（Jira 导出的测试用例表）')
    fileUploadRef.value?.clear()
    return
  }
  pendingFile.value = file
  validateResult.value = null
  importResult.value = null
}

function reselectFile() {
  pendingFile.value = null
  validateResult.value = null
  importResult.value = null
}

/** 第 3 步:跑校验。**只读不写库**,可反复点。 */
async function runValidate() {
  const file = pendingFile.value
  if (!file) {
    notify('warn', '请先选择文件')
    return
  }
  validating.value = true
  try {
    const res = await dataImportApi.validateTestcases(selectedJiraProjectId.value, file)
    validateResult.value = res
    if (res.valid) {
      notify('success', `校验通过：${res.importable ?? 0} 行可导入`)
    } else {
      notify('warn', '校验未通过，请查看下方原因')
    }
  } finally {
    validating.value = false
  }
}

/** 第 4 步进入时按文档的故事号拉已有数据 —— 「这份文档会不会重复导入」就看它 */
async function loadExistingData() {
  if (!selectedJiraProjectId.value || !storyKeys.value.length) return
  loadingData.value = true
  try {
    const res = await dataImportApi.getTestcases(
      selectedJiraProjectId.value,
      currentPage.value,
      pageSize.value,
      storyKeys.value
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

function handleClear() {
  const n = storyKeys.value.length
  confirm.require({
    message:
      `将删除本次文档涉及的 ${n} 个故事号下的 ${existingTotal.value} 条测试用例，是否继续？\n`
      + '注意：只要用例关联的故事号在本次文档里，'
      + '表里这些用例（含此前导入的）都会被一并删除。',
    header: '确认删除',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '确认删除',
    rejectLabel: '取消',
    accept: async () => {
      const res = await dataImportApi.clearTestcases(selectedJiraProjectId.value, storyKeys.value)
      notify('success', `已删除 ${res.deleted} 条（覆盖 ${res.story_count} 个故事号）`)
      existingData.value = []
      existingTotal.value = 0
      currentPage.value = 1
    },
  })
}

/** 第 5 步:写库。判定与校验同源,所以这里不会再出现"校验通过却导不进去"的意外 */
async function runImport() {
  const file = pendingFile.value
  if (!file) {
    notify('warn', '请先选择文件')
    return
  }
  uploading.value = true
  importResult.value = null
  try {
    const res = await dataImportApi.uploadTestcases(selectedJiraProjectId.value, file)
    importResult.value = res
    if (res.success) {
      notify('success', `成功导入 ${res.imported ?? 0} 行（${res.case_count ?? 0} 个用例）`)
      currentPage.value = 1
      await loadExistingData()
    } else {
      notify('error', '没有导入任何数据，请查看下方原因')
    }
  } finally {
    uploading.value = false
  }
}

/** 导入完成后再导同一份文件 = 幂等覆盖，这里给个明确的「再导一次」入口 */
function handleAgain() {
  importResult.value = null
}

function handleReset() {
  currentStep.value = 1
  selectedProjectId.value = null
  selectedJiraProjectId.value = ''
  selectedProjectName.value = ''
  resetAll()
}

function handleClose() {
  handleReset()
  emit('close')
}

// 进入第 4 步才去查已有数据:在此之前范围(故事号集合)都还没确定。
watch(currentStep, (step) => {
  if (step === 4) loadExistingData()
})

watch(() => props.visible, (val) => {
  if (val) loadProjects()
})
</script>

<template>
  <Dialog
    :visible="visible"
    header="文档测试用例导入"
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
            <label class="ds-meta" for="tc-import-project">选择项目</label>
            <Select
              v-model="selectedProjectId"
              inputId="tc-import-project"
              :options="projects"
              optionLabel="project_name"
              optionValue="id"
              placeholder="请选择项目"
              :loading="loadingProjects"
              @change="onProjectChange($event.value)"
            />
          </div>
          <Message severity="info" :closable="false">
            导入源是 Jira 的<b>测试用例导出 CSV</b>：一个用例占「首行（含关键字）+ N 行步骤」，
            界面会按<b>关键字</b>归并成一个用例，并把步骤折成测试步骤。
            用例的<b>迭代归属由文档里的「需求」（故事号）反查</b>，不需要你手选迭代。
          </Message>
          <div class="flex justify-end gap-2 pt-4">
            <Button label="下一步" :disabled="!selectedProjectId" @click="currentStep = 2" />
          </div>
        </div>

        <!-- ── 2. 上传文档 ── -->
        <div v-if="currentStep === 2" class="flex flex-col gap-4">
          <Message severity="info" :closable="false">
            上传 CSV（<b>.csv</b>），需包含列：关键字、概要、描述、测试用例集、最新结果、
            标签、步骤ID、步骤、测试数据、期望结果、<b>需求</b>。
            编码支持 UTF-8（含 BOM）与 GBK。
          </Message>

          <!-- 只有「选择文件」一个按钮:选中即收下,确认交给下方「下一步」,取消交给弹窗关闭 -->
          <FileUpload
            v-if="!pendingFile"
            ref="fileUploadRef"
            customUpload
            :multiple="false"
            accept=".csv"
            chooseLabel="选择文件"
            :showUploadButton="false"
            :showCancelButton="false"
            :disabled="validating"
            @select="onPickFile"
          />

          <div v-else class="flex items-center justify-between gap-4">
            <span class="ds-meta">已选择：{{ pendingFile.name }}</span>
            <Button label="重新选择" severity="secondary" text size="small" @click="reselectFile" />
          </div>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 1" />
            <Button label="下一步" :disabled="!pendingFile" @click="currentStep = 3" />
          </div>
        </div>

        <!-- ── 3. 数据校验 ── -->
        <div v-if="currentStep === 3" class="flex flex-col gap-4">
          <p v-if="pendingFile" class="ds-meta">待校验文件：{{ pendingFile.name }}</p>

          <div v-if="validating" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在解析并解析故事号的迭代归属…</span>
          </div>

          <template v-if="!validateResult && !validating">
            <Message severity="info" :closable="false">
              校验<b>只读不写库</b>，可反复执行。它会解析文档里的每个故事号，
              并到 rdm_issue 里查出该故事号现在所属的迭代 —— 任何一个故事号查不到，
              <b>整份文件都会被拒绝</b>（没有迭代归属的用例在报表里是隐形的）。
            </Message>
            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 2" />
              <Button label="开始校验" :disabled="!pendingFile" @click="runValidate" />
            </div>
          </template>

          <template v-if="validateResult">
            <Message :severity="validateResult.valid ? 'success' : 'error'" :closable="false">
              <template v-if="validateResult.valid">
                校验通过：<b>{{ validateResult.importable ?? 0 }}</b> 行可导入
                （{{ validateResult.case_count ?? 0 }} 个用例，共读取
                {{ validateResult.total_rows ?? 0 }} 行）
              </template>
              <template v-else-if="!validateResult.header_ok">
                表头校验未通过，文件无法用于导入
              </template>
              <template v-else>
                校验未通过，整份文件被拒绝（共读取 {{ validateResult.total_rows ?? 0 }} 行）
              </template>
            </Message>

            <p class="ds-meta">{{ mergeNote(validateResult) }}</p>

            <div v-if="storyRows.length" class="flex flex-col gap-2">
              <p class="ds-meta">故事号 → 迭代归属</p>
              <DataTable :value="storyRows" class="ds-table">
                <Column field="story_key" :header="TH.storyKey" class="ds-nowrap" />
                <Column :header="TH.sprint" class="ds-nowrap">
                  <template #body="{ data }">
                    {{ data.sprint_name || data.sprint_id || '—' }}
                  </template>
                </Column>
                <Column header="迭代状态" class="ds-nowrap">
                  <template #body="{ data }">
                    {{ SPRINT_STATE_LABEL[data.state] || data.state || '—' }}
                  </template>
                </Column>
                <Column field="case_count" header="用例数" class="ds-nowrap" />
              </DataTable>
            </div>

            <div v-if="validateResult.missing_stories?.length" class="flex flex-col gap-2">
              <p class="ds-meta">
                以下故事号在 rdm_issue 中不存在（共 {{ validateResult.missing_stories.length }} 个）
              </p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="k in validateResult.missing_stories.slice(0, 20)" :key="k">{{ k }}</li>
              </ul>
            </div>

            <div v-if="validateResult.case_sets?.length" class="flex flex-col gap-2">
              <p class="ds-meta">文档中的用例集</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="cs in validateResult.case_sets" :key="cs.name">
                  {{ cs.name }}：{{ cs.count }} 个用例
                </li>
              </ul>
            </div>

            <div v-if="validateResult.errors?.length" class="flex flex-col gap-2">
              <p class="ds-meta">原因</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="(err, idx) in validateResult.errors" :key="idx">{{ err }}</li>
              </ul>
            </div>

            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 2" />
              <Button label="重新校验" severity="secondary" @click="runValidate" />
              <Button
                label="下一步"
                :disabled="!validateResult.valid"
                @click="currentStep = 4"
              />
            </div>
          </template>

        </div>

        <!-- ── 4. 检查已有数据 ── -->
        <div v-if="currentStep === 4" class="flex flex-col gap-4">
          <div v-if="loadingData" class="flex flex-col items-center gap-2 py-8">
            <ProgressSpinner strokeWidth="4" />
          </div>

          <template v-else-if="existingTotal > 0">
            <Message severity="warn" :closable="false">
              本次文档涉及的 {{ storyKeys.length }} 个故事号下已有 <b>{{ existingTotal }}</b> 条测试用例。
              直接导入不会清空它们，只会按「用例 + 故事」覆盖同一条。
            </Message>
            <DataTable :value="existingData" :loading="loadingData" class="ds-table">
              <Column field="case_key" :header="TH.code" class="ds-nowrap" />
              <Column field="case_name" :header="TH.name" />
              <Column field="module" :header="TH.caseSet" />
              <Column field="exec_status" :header="TH.execStatus" class="ds-nowrap" />
              <Column field="story_key" :header="TH.storyKey" class="ds-nowrap" />
              <Column field="sprint_name" :header="TH.sprint" class="ds-nowrap" />
              <Column field="step_count" :header="TH.stepCount" class="ds-nowrap" />
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
              <Button label="删除这些故事号下的用例" severity="warn" @click="handleClear" />
            </div>
          </template>

          <Message v-else severity="success" :closable="false">
            本次文档涉及的 {{ storyKeys.length }} 个故事号下暂无测试用例，直接导入即可。
          </Message>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 3" />
            <Button label="下一步" @click="currentStep = 5" />
          </div>
        </div>

        <!-- ── 5. 执行导入 ── -->
        <div v-if="currentStep === 5" class="flex flex-col gap-4">
          <Message v-if="!importResult" severity="info" :closable="false">
            将把 {{ validateResult?.case_count ?? 0 }} 个用例写入 <b>rdm_testcase</b>，
            迭代归属已由故事号确定（见上一步的校验报告）。
          </Message>

          <div v-if="uploading" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在解析并写入数据库…</span>
          </div>

          <div v-if="importResult && !importResult.success" class="flex flex-col gap-2">
            <Message severity="error" :closable="false">没有导入任何数据</Message>
            <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
              <li v-for="(err, idx) in importResult.errors" :key="idx">{{ err }}</li>
            </ul>
          </div>

          <template v-if="importResult?.success">
            <Message severity="success" :closable="false">
              成功导入 <b>{{ importResult.imported || 0 }}</b> 行
              （{{ importResult.case_count || 0 }} 个用例，步骤 {{ importResult.step_count || 0 }} 条）
            </Message>

            <p class="ds-meta">{{ mergeNote(importResult) }}</p>
            <p class="ds-meta">{{ expandNote }}</p>
            <p v-if="importResult.encoding" class="ds-meta">
              源文件按 <b>{{ importResult.encoding }}</b> 解码。
            </p>

            <div v-if="importResult.stories?.length" class="flex flex-col gap-2">
              <p class="ds-meta">写入的迭代（由故事号反查得出）</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="s in importResult.stories" :key="s.story_key">
                  {{ s.story_key }} → {{ s.sprint_name || s.sprint_id || '—' }}
                  （{{ SPRINT_STATE_LABEL[s.state || ''] || s.state || '未知' }}）：{{ s.case_count }} 个用例
                </li>
              </ul>
            </div>

            <div v-if="importResult.case_sets?.length" class="flex flex-col gap-2">
              <p class="ds-meta">写入的用例集</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="cs in importResult.case_sets" :key="cs.name">
                  {{ cs.name }}：{{ cs.count }} 个用例
                </li>
              </ul>
            </div>

            <div v-if="skipRows.length" class="flex flex-col gap-2">
              <p class="ds-meta">已跳过</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="row in skipRows" :key="row.label">
                  {{ row.label }}：{{ row.count }} 条<span class="ml-1">（{{ row.hint }}）</span>
                </li>
              </ul>
            </div>

            <div v-if="importResult.errors?.length" class="flex flex-col gap-2">
              <p class="ds-meta">明细</p>
              <ul class="flex flex-col gap-1 pl-5 list-disc ds-meta">
                <li v-for="(err, idx) in importResult.errors" :key="idx">{{ err }}</li>
              </ul>
            </div>
          </template>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 4" />
            <Button
              v-if="!importResult"
              label="开始导入"
              :disabled="uploading"
              @click="runImport"
            />
            <Button v-if="importResult?.success" label="再导一次" @click="handleAgain" />
            <!-- 本步不再给「关闭」按钮:右上角 × 与 Esc 都经 @update:visible 落到同一个 handleClose
                 (含 handleReset),按钮只是重复一遍同一件事。 -->
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>
