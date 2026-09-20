<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { projectApi, type ProjectConfig, type ProjectFormData } from '@/api/projects'
import { useConfirm } from 'primevue/useconfirm'
import { useNotify } from '@/utils/notify'
import { TH } from '@/constants/tableHeaders'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import SelectButton from 'primevue/selectbutton'
import InputMask from 'primevue/inputmask'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import ToggleSwitch from 'primevue/toggleswitch'
import Password from 'primevue/password'
import Tag from 'primevue/tag'
import Avatar from 'primevue/avatar'

const confirm = useConfirm()
const notify = useNotify()

const projects = ref<ProjectConfig[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const formData = ref<ProjectFormData>({
  board_id: '',
  board_name: '',
  project_id: '',
  project_name: '',
  gitlab_group_key: '',
  need_story_remind: false,
  need_task_remind: false,
  need_sonar_scan_remind: false,
  need_report_data: false,
  story_remind_time: '',
  task_remind_time: '',
  sonar_remind_time: '',
  sonar_key_prefix: '',
  sonar_scan_remind_default_person: '',
  robot_key: '',
  jira_user: '',
  jira_token: ''
})

const filterKeyword = ref('')
const filterStatus = ref<'all' | 'configured' | 'unconfigured'>('all')

const statusOptions = [
  { label: '全部', value: 'all' },
  { label: '已配置', value: 'configured' },
  { label: '未配置', value: 'unconfigured' },
]

// 提醒时间由 144 项下拉(00:00~23:50 步长 10 分钟)改为 HH:mm 掩码输入 ——
// 下拉需要滚动穿过上百项才能选到目标时间,输入两个数字即可。
// 注意:InputMask 的 "99:99" 只约束「两位数字:两位数字」,不校验范围,故保存前补一次校验。
// 空值视为**不合法**:调用处是「开关打开时才校验」,若空值放行,就会出现
// 「开关开着、时间空着」被静默保存,后端拿不到时间、提醒形同虚设。
function isTimeValid(t: string): boolean {
  if (!t) return false
  const m = t.match(/^(\d{2}):(\d{2})$/)
  if (!m) return false
  return Number(m[1]) < 24 && Number(m[2]) < 60
}

const reminderTags = [
  { key: 'need_story_remind' as const, timeKey: 'story_remind_time' as const, label: '进度提醒', severity: 'info' as const },
  { key: 'need_task_remind' as const, timeKey: 'task_remind_time' as const, label: '任务提醒', severity: 'success' as const },
  { key: 'need_sonar_scan_remind' as const, timeKey: 'sonar_remind_time' as const, label: '扫描提醒', severity: 'warn' as const },
  { key: 'need_report_data' as const, timeKey: null, label: '报表生成', severity: 'contrast' as const },
]

function isConfigured(row: ProjectConfig): boolean {
  return Boolean(
    row.need_story_remind ||
      row.need_task_remind ||
      row.need_sonar_scan_remind ||
      row.need_report_data
  )
}

const filteredProjects = computed(() => {
  const keyword = filterKeyword.value.trim().toLowerCase()
  return projects.value.filter(p => {
    if (filterStatus.value === 'configured' && !isConfigured(p)) return false
    if (filterStatus.value === 'unconfigured' && isConfigured(p)) return false
    if (keyword) {
      const haystack = `${p.project_name ?? ''} ${p.board_name ?? ''} ${p.gitlab_group_key ?? ''}`.toLowerCase()
      if (!haystack.includes(keyword)) return false
    }
    return true
  })
})

const hasActiveFilter = computed(
  () => filterKeyword.value.trim() !== '' || filterStatus.value !== 'all'
)

function resetFilters() {
  filterKeyword.value = ''
  filterStatus.value = 'all'
}

onMounted(() => {
  loadProjects()
})

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await projectApi.getList()
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  isEdit.value = false
  formData.value = {
    board_id: '',
    board_name: '',
    project_id: '',
    project_name: '',
    gitlab_group_key: '',
    need_story_remind: false,
    need_task_remind: false,
    need_sonar_scan_remind: false,
    need_report_data: false,
    story_remind_time: '',
    task_remind_time: '',
    sonar_remind_time: '',
    sonar_key_prefix: '',
    sonar_scan_remind_default_person: '',
    robot_key: '',
    jira_user: '',
    jira_token: '',
  }
  dialogVisible.value = true
}

async function openEditDialog(row: ProjectConfig) {
  isEdit.value = true
  // ⚠ 必须取详情:列表接口对 robot_key 脱敏(且不回吐 jira_token),
  //   拿列表值填表单再保存会把掩码/空值写回库,真实凭据被覆盖。
  let detail: ProjectConfig
  try {
    detail = await projectApi.getById(row.id)
  } catch {
    return // 错误提示由拦截器统一处理
  }
  formData.value = {
    id: detail.id,
    board_id: detail.board_id,
    board_name: detail.board_name,
    project_id: detail.project_id,
    project_name: detail.project_name,
    gitlab_group_key: detail.gitlab_group_key,
    sonar_key_prefix: detail.sonar_key_prefix,
    sonar_scan_remind_default_person: detail.sonar_scan_remind_default_person,
    robot_key: detail.robot_key,
    jira_user: detail.jira_user,
    jira_token: detail.jira_token ?? '',
    need_story_remind: detail.need_story_remind ?? false,
    need_task_remind: detail.need_task_remind ?? false,
    need_sonar_scan_remind: detail.need_sonar_scan_remind ?? false,
    need_report_data: detail.need_report_data ?? false,
    story_remind_time: detail.reminder_settings?.story_remind_time ?? '',
    task_remind_time: detail.reminder_settings?.task_remind_time ?? '',
    sonar_remind_time: detail.reminder_settings?.sonar_remind_time ?? '',
  }
  dialogVisible.value = true
}

async function handleSave() {
  if (!formData.value.board_id || !formData.value.project_id) {
    notify('warn', '请填写必填项')
    return
  }

  // 提醒时间校验:开关打开时,时间必填且须为合法的 24 小时 HH:mm。
  // 掩码只保证「两位:两位」的格式,不保证范围,故在此补一次判断。
  const enabledReminders = [
    { on: formData.value.need_story_remind, t: formData.value.story_remind_time, label: '进度提醒' },
    { on: formData.value.need_task_remind, t: formData.value.task_remind_time, label: '任务提醒' },
    { on: formData.value.need_sonar_scan_remind, t: formData.value.sonar_remind_time, label: '扫描提醒' },
  ]
  for (const { on, t, label } of enabledReminders) {
    if (on && !isTimeValid(t)) {
      notify('warn', t ? `「${label}」的时间应为 HH:mm(24 小时制)` : `「${label}」已开启,请填写提醒时间`)
      return
    }
  }

  try {
    // 后端要求开关字段嵌套在 reminder_settings 中，需从平铺的表单字段组装
    const payload = {
      board_id: formData.value.board_id,
      board_name: formData.value.board_name,
      project_id: formData.value.project_id,
      project_name: formData.value.project_name,
      gitlab_group_key: formData.value.gitlab_group_key,
      sonar_key_prefix: formData.value.sonar_key_prefix,
      sonar_scan_remind_default_person: formData.value.sonar_scan_remind_default_person,
      robot_key: formData.value.robot_key,
      jira_user: formData.value.jira_user,
      jira_token: formData.value.jira_token,
      reminder_settings: {
        need_story_remind: formData.value.need_story_remind,
        need_task_remind: formData.value.need_task_remind,
        need_sonar_scan_remind: formData.value.need_sonar_scan_remind,
        need_report_data: formData.value.need_report_data,
        // 只有开关打开时才带上时间,避免关闭的提醒仍提交一个遗留时间值
        story_remind_time: formData.value.need_story_remind ? (formData.value.story_remind_time || undefined) : undefined,
        task_remind_time: formData.value.need_task_remind ? (formData.value.task_remind_time || undefined) : undefined,
        sonar_remind_time: formData.value.need_sonar_scan_remind ? (formData.value.sonar_remind_time || undefined) : undefined,
      },
    }
    if (isEdit.value) {
      await projectApi.update(formData.value.id!, payload)
      notify('success', '更新成功')
    } else {
      await projectApi.create(payload)
      notify('success', '创建成功')
    }
    dialogVisible.value = false
    loadProjects()
  } catch (error) {
    // error already handled by interceptor
  }
}

function handleDelete(row: ProjectConfig) {
  confirm.require({
    message: '确定要删除该项目吗？',
    header: '提示',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '删除',
    rejectLabel: '取消',
    accept: async () => {
      try {
        await projectApi.delete(row.id!)
        notify('success', '删除成功')
        loadProjects()
      } catch {
        // handled by interceptor
      }
    },
  })
}


</script>

<template>
  <div class="flex flex-col gap-6">
    <div class="ds-page-head">
      <div>
        <h1>项目信息</h1>
      </div>
      <Button icon="pi pi-plus" label="录入项目" @click="openAddDialog" />
    </div>
    <Card class="ds-card">
      <template #content>
        <div class="flex flex-wrap items-center gap-3">
          <IconField>
            <InputIcon class="pi pi-search" />
            <InputText
              v-model="filterKeyword"
              placeholder="搜索项目名称 / 面板 / GitLab"
              showClear
            />
          </IconField>
          <SelectButton
            v-model="filterStatus"
            :options="statusOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>
      </template>
    </Card>
    <Card class="ds-card">
      <template #content>
        <DataTable :value="filteredProjects" :loading="loading" class="ds-table">
          <template #empty>
            <div class="ds-empty">
              <p>{{ hasActiveFilter ? '没有匹配的项目' : '暂无项目' }}</p>
              <p class="ds-meta">{{ hasActiveFilter ? '尝试调整搜索关键词或筛选条件' : '点击录入项目创建第一个项目' }}</p>
              <Button
                v-if="hasActiveFilter"
                label="清除筛选"
                severity="secondary"
                @click="resetFilters"
              />
              <Button
                v-else
                label="录入项目"
                icon="pi pi-plus"
                @click="openAddDialog"
              />
            </div>
          </template>
          <Column field="project_name" :header="TH.project">
            <template #body="{ data }">
              <div class="flex items-center gap-3">
                <Avatar :label="data.project_name?.charAt(0) || 'P'" shape="circle" />
                <div>
                  <div>{{ data.project_name }}</div>
                </div>
              </div>
            </template>
          </Column>
          <!-- 短列挂 ds-nowrap(机制见 ExecutionLogTable / BugListDialog 注释);
               「项目」属名称类、长度不可控 ⇒ 不挂,省下的宽度归它(它还带头像,更需要空间)。 -->
          <Column field="gitlab_group_key" :header="TH.gitlabGroup" class="ds-nowrap">
            <template #body="{ data }">
              <Tag
                v-if="data.gitlab_group_key"
                severity="secondary"
                :value="data.gitlab_group_key"
              />
              <span v-else class="ds-meta">未配置</span>
            </template>
          </Column>
          <Column :header="TH.reminderConfig" class="min-w-[170px] ds-nowrap">
            <template #body="{ data }">
              <div class="flex flex-col gap-1 min-w-[130px]">
                <template v-for="t in reminderTags" :key="t.key">
                  <div v-if="data[t.key]" class="flex items-center gap-2 py-0.5 text-sm whitespace-nowrap">
                    <span class="ds-tag-dot" :class="`tone-${t.severity}`"></span>
                    <span>{{ t.label }}</span>
                  </div>
                </template>
                <span
                  v-if="!reminderTags.some(t => data[t.key])"
                  class="ds-meta"
                >—</span>
              </div>
            </template>
          </Column>
          <Column :header="TH.actions" headerClass="text-center ds-nowrap" bodyClass="text-center">
            <template #body="{ data }">
              <div class="flex justify-center gap-2">
                <Button
                  label="编辑"
                  link
                  @click="openEditDialog(data as ProjectConfig)"
                />
                <Button
                  label="删除"
                  link
                  severity="danger"
                  @click="handleDelete(data as ProjectConfig)"
                />
              </div>
            </template>
          </Column>
        </DataTable>
      </template>
    </Card>

    <!-- Dialog -->
    <Dialog
      v-model:visible="dialogVisible"
      :header="isEdit ? '编辑项目' : '录入项目'"
      class="ds-dialog-md"
      modal
      :dismissableMask="false"
    >
      <div class="flex flex-col gap-6">
        <section class="flex flex-col gap-4">
          <h3 class="ds-section-title">项目基础</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-board-id">面板 ID *</label>
              <InputText id="pl-board-id" v-model="formData.board_id" :disabled="isEdit" placeholder="JIRA 面板 ID" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-board-name">面板名称 *</label>
              <InputText id="pl-board-name" v-model="formData.board_name" placeholder="JIRA 面板名称" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-project-id">项目 ID *</label>
              <InputText id="pl-project-id" v-model="formData.project_id" :disabled="isEdit" placeholder="JIRA 项目 ID" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-project-name">项目名称 *</label>
              <InputText id="pl-project-name" v-model="formData.project_name" placeholder="项目显示名称" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-jira-user">JIRA 用户</label>
              <InputText id="pl-jira-user" v-model="formData.jira_user" placeholder="JIRA 登录用户名" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-jira-token">JIRA 密码</label>
              <Password inputId="pl-jira-token" v-model="formData.jira_token" :feedback="false" toggleMask placeholder="JIRA 密码/Token" fluid />
            </div>
          </div>
        </section>

        <section class="flex flex-col gap-4">
          <h3 class="ds-section-title">集成配置</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-gitlab-group">GitLab Group</label>
              <InputText id="pl-gitlab-group" v-model="formData.gitlab_group_key" placeholder="GitLab Group 标识" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-sonar-prefix">Sonar Key 前缀</label>
              <InputText id="pl-sonar-prefix" v-model="formData.sonar_key_prefix" placeholder="SonarQube 项目 Key 前缀" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-sonar-person">Sonar 默认人</label>
              <InputText id="pl-sonar-person" v-model="formData.sonar_scan_remind_default_person" placeholder="企微用户名" fluid />
            </div>
            <div class="flex flex-col gap-2">
              <label class="ds-meta" for="pl-robot-key">企微机器人 Key</label>
              <InputText id="pl-robot-key" v-model="formData.robot_key" placeholder="企业微信机器人 Webhook Key" fluid />
            </div>
          </div>
        </section>

        <section class="flex flex-col gap-4">
          <h3 class="ds-section-title">定时任务提醒</h3>
          <div class="flex flex-col gap-3">
            <!-- 时间输入固定占位(关闭时 disabled),不再随开关显隐 —— 原先用 v-if 会让整行高度突变 -->
            <div class="flex items-center gap-3">
              <ToggleSwitch v-model="formData.need_story_remind" inputId="pl-remind-story" />
              <label class="min-w-[80px]" for="pl-remind-story">进度提醒</label>
              <InputMask
                v-model="formData.story_remind_time"
                mask="99:99"
                placeholder="HH:mm"
                class="flex-1"
                :disabled="!formData.need_story_remind"
                aria-label="进度提醒时间"
              />
            </div>
            <div class="flex items-center gap-3">
              <ToggleSwitch v-model="formData.need_task_remind" inputId="pl-remind-task" />
              <label class="min-w-[80px]" for="pl-remind-task">任务提醒</label>
              <InputMask
                v-model="formData.task_remind_time"
                mask="99:99"
                placeholder="HH:mm"
                class="flex-1"
                :disabled="!formData.need_task_remind"
                aria-label="任务提醒时间"
              />
            </div>
            <div class="flex items-center gap-3">
              <ToggleSwitch v-model="formData.need_sonar_scan_remind" inputId="pl-remind-sonar" />
              <label class="min-w-[80px]" for="pl-remind-sonar">扫描提醒</label>
              <InputMask
                v-model="formData.sonar_remind_time"
                mask="99:99"
                placeholder="HH:mm"
                class="flex-1"
                :disabled="!formData.need_sonar_scan_remind"
                aria-label="扫描提醒时间"
              />
            </div>
            <div class="flex items-center gap-3">
              <ToggleSwitch v-model="formData.need_report_data" inputId="pl-remind-report" />
              <label class="min-w-[80px]" for="pl-remind-report">报表生成</label>
            </div>
          </div>
        </section>
      </div>
      <template #footer>
        <Button label="取消" severity="secondary" @click="dialogVisible = false" />
        <Button label="保存" @click="handleSave" />
      </template>
    </Dialog>
  </div>
</template>
