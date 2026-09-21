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
  type TestcaseBatchReport,
  type TestcaseRecord,
} from '@/api/dataImport'
import { reportsApi, type ProjectOption } from '@/api/reports'
import { TH } from '@/constants/tableHeaders'
import TestcaseFileReportPanel from './TestcaseFileReportPanel.vue'

const confirm = useConfirm()
const notify = useNotify()

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

/**
 * 五步:选择项目 → 上传文档 → 数据校验 → 检查已有数据 → 执行导入。
 *
 * ⚠ 2026-09-21:第 2 步改为**可一次选多份 CSV**,校验与导入都按这一批文件走。判定仍是
 *   **逐份**的 —— 某一份文件的故事号没同步,只拒它自己,不拖累同批其余文件,界面上逐份
 *   给出结论(见 TestcaseFileReportPanel)。
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

/**
 * 用户在「上传文档」选中的文件 —— 校验与导入都用这一批(不必让用户再选一次)。
 * ⚠ 2026-09-21 起是**一批**而不是一份:「一次选多份、一起导入」就是这一版要解决的问题。
 */
const pendingFiles = ref<File[]>([])
/** 文件选择控件是否展开 —— 收下文件后收起(见 onPickFile);「继续添加」再展开 */
const picking = ref(true)
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
/** 这一批文件的校验结论(逐份);null = 还没校验过 */
const validateBatch = ref<TestcaseBatchReport | null>(null)

const existingData = ref<TestcaseRecord[]>([])
const existingTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loadingData = ref(false)

const uploading = ref(false)
/** 这一批文件的导入结论(逐份);null = 还没导入过 */
const importBatch = ref<TestcaseBatchReport | null>(null)

/** 通过校验的文件 —— 第 4 步查已有数据、第 5 步导入都只针对它们 */
const validFiles = computed(() => (validateBatch.value?.files ?? []).filter(f => f.valid))

/**
 * 通过校验的文件里解析出的故事号(并集)—— 「检查已有数据」与「清空」都按它收窄范围。
 * ⚠ 取并集而不是逐份各查一遍:第 4 步问的是「这批文件会不会重复导入」,
 *   分成 N 次查询只会让同一个故事号在表里出现 N 遍。
 */
const storyKeys = computed(() => {
  const keys = new Set<string>()
  for (const file of validFiles.value) {
    for (const story of file.stories ?? []) keys.add(story.story_key)
  }
  return [...keys]
})

/** 本批可导入行数合计 —— 一句话结论用 */
const importableRows = computed(() =>
  validFiles.value.reduce((sum, f) => sum + (f.importable ?? 0), 0)
)

/** 导入批里被拒的文件数 —— 汇总文案要说清"哪些没进来" */
const rejectedCount = computed(() => {
  const batch = importBatch.value
  return batch ? batch.file_count - batch.valid_count : 0
})

/**
 * 同名 + 同大小 + 同修改时间 ⇒ 同一份文件。
 * ⚠ 重复选中同一份文件不会导错(后端 upsert 幂等),但报告里会长出重复项白白吓人,
 *   故在收文件时就去重。
 */
function sameFile(a: File, b: File) {
  return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified
}

/** 列表 / v-for 的稳定 key */
function fileKey(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

async function loadProjects() {
  loadingProjects.value = true
  try {
    projects.value = await reportsApi.getProjects()
  } catch {
    // 失败提示由 axios 拦截器统一给出;下拉保持为空,不留半截数据
  } finally {
    loadingProjects.value = false
  }
}

/** 换项目 = 一切都失效:校验结论是「这批文件对这个项目」的判断,导入结果更是不能跨项目留 */
function resetAll() {
  pendingFiles.value = []
  picking.value = true
  validateBatch.value = null
  importBatch.value = null
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
 * ⚠ 2026-09-21 支持多选:一批文件就是「一次导入」的单位,校验与写库都按批走。
 *   不合规的后缀**只忽略那几份**而不是整批作废(并点名说明)—— 用户一次拖进 10 个文件,
 *   不该因为混进一个 .xlsx 就全部重选。
 */
function onPickFile(event: FileUploadSelectEvent) {
  const rawFiles = event.files as File | File[] | undefined
  const picked = rawFiles == null ? [] : Array.isArray(rawFiles) ? rawFiles : [rawFiles]
  if (!picked.length) {
    // 用户打开系统文件框又取消。已有文件时顺手把控件收起来,别占着位置。
    if (pendingFiles.value.length) picking.value = false
    return
  }

  const accepted: File[] = []
  const rejected: string[] = []
  for (const file of picked) {
    // ⚠ 只认 .csv(与后端 require_testcase_files 同口径)。这份导出是 CSV;用户若在 Excel
    //   里另存过,后缀会变成 .xlsx —— 那种文件这里不接,直接说清要什么比事后回一个 400 便宜。
    if (!/\.csv$/i.test(file.name)) {
      rejected.push(file.name)
      continue
    }
    if (pendingFiles.value.some(f => sameFile(f, file))) continue
    if (accepted.some(f => sameFile(f, file))) continue
    accepted.push(file)
  }
  if (rejected.length) {
    notify('warn', `仅支持 .csv（Jira 导出的测试用例表），已忽略：${rejected.join('、')}`)
  }
  if (accepted.length) pendingFiles.value = [...pendingFiles.value, ...accepted]

  fileUploadRef.value?.clear()
  picking.value = false
  // 文件集合一变,上一次的校验结论就不再对应当前这批文件
  validateBatch.value = null
  importBatch.value = null
}

function removeFile(file: File) {
  pendingFiles.value = pendingFiles.value.filter(f => !sameFile(f, file))
  if (!pendingFiles.value.length) picking.value = true
  validateBatch.value = null
  importBatch.value = null
}

function clearFiles() {
  pendingFiles.value = []
  picking.value = true
  validateBatch.value = null
  importBatch.value = null
}

/** 第 3 步:逐份跑校验。**只读不写库**,可反复点。 */
async function runValidate() {
  if (!pendingFiles.value.length) {
    notify('warn', '请先选择文件')
    return
  }
  validating.value = true
  try {
    const res = await dataImportApi.validateTestcases(selectedJiraProjectId.value, pendingFiles.value)
    validateBatch.value = res
    if (res.success) {
      const importable = res.files.reduce((sum, f) => sum + (f.valid ? f.importable ?? 0 : 0), 0)
      notify('success', `校验通过：${res.valid_count} 个文件共 ${importable} 行可导入`)
    } else {
      notify('warn', '所有文件都未通过校验，请查看下方原因')
    }
  } catch {
    // 失败提示由 axios 拦截器统一给出(校验结论保持为空,不会留下「半份报告」)
  } finally {
    validating.value = false
  }
}

/** 第 4 步进入时按这批文件的故事号拉已有数据 —— 「这批文件会不会重复导入」就看它 */
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
  } catch {
    // 失败提示由 axios 拦截器统一给出;列表保持上一次的结论,不误报为「没有数据」
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
      `将删除这批文件涉及的 ${n} 个故事号下的 ${existingTotal.value} 条测试用例，是否继续？\n`
      + '注意：只要用例关联的故事号在这批文件里，'
      + '表里这些用例（含此前导入的）都会被一并删除。',
    header: '确认删除',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '确认删除',
    rejectLabel: '取消',
    accept: async () => {
      try {
        const res = await dataImportApi.clearTestcases(selectedJiraProjectId.value, storyKeys.value)
        notify('success', `已删除 ${res.deleted} 条（覆盖 ${res.story_count} 个故事号）`)
        existingData.value = []
        existingTotal.value = 0
        currentPage.value = 1
      } catch {
        // ⚠ confirm 的 accept 回调抛错没有任何组件会接住,会变成未处理的 rejection。
        //   失败提示由 axios 拦截器统一给出,这里吞掉即可。
      }
    },
  })
}

/** 第 5 步:写库。判定与校验同源,所以这里不会再出现"校验通过却导不进去"的意外 */
async function runImport() {
  if (!pendingFiles.value.length) {
    notify('warn', '请先选择文件')
    return
  }
  uploading.value = true
  importBatch.value = null
  try {
    const res = await dataImportApi.uploadTestcases(selectedJiraProjectId.value, pendingFiles.value)
    importBatch.value = res
    const rejected = res.file_count - res.valid_count
    if (res.success) {
      // 部分文件被拒时用 warn 而不是 success:结论是"导了,但不全",别让绿条盖过这件事
      const tail = rejected ? `；${rejected} 个文件被拒绝（见下方原因）` : ''
      notify(
        rejected ? 'warn' : 'success',
        `成功导入 ${res.imported} 行（${res.valid_count} 个文件）${tail}`
      )
      currentPage.value = 1
      await loadExistingData()
    } else {
      notify('error', '没有导入任何数据，请查看下方原因')
    }
  } catch {
    // 失败提示由 axios 拦截器统一给出;导入结论留空,由用户重试
  } finally {
    uploading.value = false
  }
}

/** 导入完成后再导同一批文件 = 幂等覆盖，这里给个明确的「再导一次」入口 */
function handleAgain() {
  importBatch.value = null
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

        <!-- ── 2. 上传文档(可一次选多份) ── -->
        <div v-if="currentStep === 2" class="flex flex-col gap-4">
          <Message severity="info" :closable="false">
            上传 CSV（<b>.csv</b>），需包含列：关键字、概要、描述、测试用例集、最新结果、
            标签、步骤ID、步骤、测试数据、期望结果、<b>需求</b>。
            编码支持 UTF-8（含 BOM）与 GBK。支持<b>一次选择多份</b>，校验与导入都按这一批走。
          </Message>

          <!-- 已收下的文件列表:可逐个移除,也可「继续添加」再补几份 -->
          <div v-if="pendingFiles.length" class="flex flex-col gap-2">
            <div class="flex items-center justify-between gap-4">
              <span class="ds-meta">已选择 {{ pendingFiles.length }} 个文件</span>
              <div class="flex gap-2">
                <Button
                  v-if="!picking"
                  label="继续添加"
                  severity="secondary"
                  text
                  size="small"
                  @click="picking = true"
                />
                <Button label="清空" severity="secondary" text size="small" @click="clearFiles" />
              </div>
            </div>
            <ul class="flex flex-col gap-2">
              <li
                v-for="file in pendingFiles"
                :key="fileKey(file)"
                class="flex items-center justify-between gap-4"
              >
                <span class="ds-meta">{{ file.name }}</span>
                <Button
                  icon="pi pi-times"
                  severity="secondary"
                  text
                  rounded
                  size="small"
                  aria-label="移除该文件"
                  @click="removeFile(file)"
                />
              </li>
            </ul>
          </div>

          <!-- 只有「选择文件」一个按钮:选中即收下,确认交给下方「下一步」,取消交给弹窗关闭 -->
          <FileUpload
            v-if="picking"
            ref="fileUploadRef"
            customUpload
            :multiple="true"
            accept=".csv"
            chooseLabel="选择文件"
            :showUploadButton="false"
            :showCancelButton="false"
            :disabled="validating"
            @select="onPickFile"
          />

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 1" />
            <Button label="下一步" :disabled="!pendingFiles.length" @click="currentStep = 3" />
          </div>
        </div>

        <!-- ── 3. 数据校验(逐份出结论) ── -->
        <div v-if="currentStep === 3" class="flex flex-col gap-4">
          <p v-if="pendingFiles.length" class="ds-meta">
            待校验文件（{{ pendingFiles.length }} 个）：{{ pendingFiles.map(f => f.name).join('、') }}
          </p>

          <div v-if="validating" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在逐份解析并解析故事号的迭代归属…</span>
          </div>

          <template v-if="!validateBatch && !validating">
            <Message severity="info" :closable="false">
              校验<b>只读不写库</b>，可反复执行。它会逐份解析文档里的每个故事号，
              并到 rdm_issue 里查出该故事号现在所属的迭代 —— 某份文件里有故事号查不到，
              <b>该份文件被整份拒绝</b>（没有迭代归属的用例在报表里是隐形的），
              但<b>不影响同一批的其它文件</b>。
            </Message>
            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 2" />
              <Button label="开始校验" :disabled="!pendingFiles.length" @click="runValidate" />
            </div>
          </template>

          <template v-if="validateBatch">
            <Message :severity="validateBatch.success ? 'success' : 'error'" :closable="false">
              <template v-if="validateBatch.valid_count === validateBatch.file_count">
                校验通过：{{ validateBatch.file_count }} 个文件全部可导入，共
                {{ importableRows }} 行
              </template>
              <template v-else-if="validateBatch.success">
                {{ validateBatch.file_count }} 个文件中
                <b>{{ validateBatch.valid_count }}</b> 个可导入（共 {{ importableRows }} 行），
                其余 {{ validateBatch.file_count - validateBatch.valid_count }} 个被拒绝
                —— 导入时只会写入可导入的文件
              </template>
              <template v-else>
                所有文件都未通过校验（共 {{ validateBatch.file_count }} 份），无法导入
              </template>
            </Message>

            <TestcaseFileReportPanel
              v-for="(report, idx) in validateBatch.files"
              :key="`${idx}-${report.filename}`"
              :report="report"
              phase="validate"
            />

            <div class="flex justify-end gap-2 pt-4">
              <Button label="上一步" severity="secondary" @click="currentStep = 2" />
              <Button label="重新校验" severity="secondary" @click="runValidate" />
              <Button label="下一步" :disabled="!validateBatch.success" @click="currentStep = 4" />
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
              本次通过校验的 {{ validFiles.length }} 份文件涉及的 {{ storyKeys.length }} 个故事号下已有
              <b>{{ existingTotal }}</b> 条测试用例。
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
            本次通过校验的 {{ validFiles.length }} 份文件涉及的 {{ storyKeys.length }} 个故事号下
            暂无测试用例，直接导入即可。
          </Message>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 3" />
            <Button label="下一步" @click="currentStep = 5" />
          </div>
        </div>

        <!-- ── 5. 执行导入(逐份出结论) ── -->
        <div v-if="currentStep === 5" class="flex flex-col gap-4">
          <Message v-if="!importBatch" severity="info" :closable="false">
            将把 <b>{{ validFiles.length }}</b> 份通过校验的文件（共 {{ importableRows }} 行）
            写入 <b>rdm_testcase</b>，迭代归属已由故事号确定（见上一步的校验报告）。
            被拒绝的文件<b>一条也不会写</b>。
          </Message>

          <div v-if="uploading" class="flex items-center gap-2 ds-meta">
            <ProgressSpinner strokeWidth="4" class="w-5 h-5" />
            <span>正在逐份解析并写入数据库…</span>
          </div>

          <template v-if="importBatch">
            <Message
              :severity="importBatch.success ? (rejectedCount ? 'warn' : 'success') : 'error'"
              :closable="false"
            >
              <template v-if="importBatch.success">
                成功导入 <b>{{ importBatch.imported }}</b> 行
                （{{ importBatch.valid_count }} 个文件）<template v-if="rejectedCount">
                  ；另有 {{ rejectedCount }} 个文件被拒绝，未写入任何数据（见下方原因）
                </template>
              </template>
              <template v-else>所有文件都没有导入任何数据</template>
            </Message>

            <TestcaseFileReportPanel
              v-for="(report, idx) in importBatch.files"
              :key="`${idx}-${report.filename}`"
              :report="report"
              phase="import"
            />
          </template>

          <div class="flex justify-end gap-2 pt-4">
            <Button label="上一步" severity="secondary" @click="currentStep = 4" />
            <Button
              v-if="!importBatch"
              label="开始导入"
              :disabled="uploading"
              @click="runImport"
            />
            <Button v-if="importBatch?.success" label="再导一次" @click="handleAgain" />
            <!-- 本步不再给「关闭」按钮:右上角 × 与 Esc 都经 @update:visible 落到同一个 handleClose
                 (含 handleReset),按钮只是重复一遍同一件事。 -->
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>
