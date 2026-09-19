# 任务调度 Tab 页重构

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `/jobs` 任务调度页重构为任务执行记录列表 + 手动执行功能

**Architecture:** 后端新增日志查询 API 和手动执行 API；前端 Jobs.vue 完全重写，包含筛选器和手动执行弹窗

**Tech Stack:** FastAPI, SQLAlchemy, Vue 3 + Element Plus, Axios

---

## Task 1: 后端 - TaskExecutionLog 模型补充 task_exec_type

**Files:**
- Modify: `backend/src/db/models.py:476-484`

**Step 1:** 在 `to_dict()` 中添加 `task_exec_type` 字段
```python
def to_dict(self):
    return {
        "id": self.id,
        "project_config_id": self.project_config_id,
        "task_type": self.task_type,
        "scheduled_time": self.scheduled_time.isoformat()
        if self.scheduled_time
        else None,
        "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        "status": self.status,
        "error_message": self.error_message,
        "task_exec_type": self.task_exec_type,
    }
```

---

## Task 2: 后端 - record_execution 支持 task_exec_type

**Files:**
- Modify: `backend/src/api/scheduler.py:167-192`

**Step 1:** 给 `record_execution` 添加 `task_exec_type` 参数，默认 `"automatic"`
```python
def record_execution(
    project_config_id: int,
    task_type: str,
    scheduled_time: datetime,
    status: str,
    error_message: str = "",
    task_exec_type: str = "automatic",
):
    ...
    log = TaskExecutionLog(
        project_config_id=project_config_id,
        task_type=task_type,
        scheduled_time=scheduled_time,
        executed_at=datetime.now(),
        status=status,
        error_message=error_message,
        task_exec_type=task_exec_type,
    )
```

---

## Task 3: 后端 - 添加按 project_config_id 获取 ProjectRemindConfig 的辅助函数

**Files:**
- Modify: `backend/src/api/scheduler.py`

**Step 1:** 在 `get_project_configs()` 附近添加新函数
```python
def get_project_config_by_id(project_config_id: int) -> Optional[ProjectRemindConfig]:
    """根据项目配置ID获取单个 ProjectRemindConfig"""
    from db.database import get_session
    from db.models import ProjectReminderSettings, ProjectConfig

    session = get_session()
    try:
        config = session.query(ProjectConfig).filter(
            ProjectConfig.id == project_config_id
        ).first()
        if not config:
            return None

        setting = config.reminder_settings
        auth_config = get_user_jira_auth(int(config.created_by)) if config.created_by else None

        return ProjectRemindConfig(
            project_config_id=config.id,
            board_id=str(config.board_id),
            board_name=str(config.board_name),
            project_id=str(config.project_id),
            project_name=str(config.project_name),
            gitlab_group_key=str(config.gitlab_group_key or ""),
            need_story_remind=bool(setting.need_story_remind) if setting else False,
            need_task_remind=bool(setting.need_task_remind) if setting else False,
            need_sonar_scan_remind=bool(setting.need_sonar_scan_remind) if setting else False,
            need_report_data=bool(setting.need_report_data) if setting else False,
            sonar_key_prefix=str(config.sonar_key_prefix or ""),
            sonar_scan_remind_default_person=str(config.sonar_scan_remind_default_person or ""),
            robot_key=str(config.robot_key or ""),
            jira_user=auth_config.user if auth_config else "",
            jira_token=auth_config.token if auth_config else "",
            story_remind_time=setting.story_remind_time or "" if setting else "",
            task_remind_time=setting.task_remind_time or "" if setting else "",
            sonar_remind_time=setting.sonar_remind_time or "" if setting else "",
        )
    finally:
        session.close()
```

---

## Task 4: 后端 - 添加 sprint 数据检查函数

**Files:**
- Modify: `backend/src/api/scheduler.py`

**Step 1:** 添加检查 rdm_sprint/rdm_issue 是否有该 sprint 数据的函数
```python
def check_sprint_data_exists(sprint_id: str) -> bool:
    """检查指定 sprint 是否已有数据"""
    from sqlalchemy import text
    from db.database import get_session

    session = get_session()
    try:
        query = text("SELECT COUNT(1) FROM rdm_sprint WHERE sprint_id = :sprint_id")
        count = session.execute(query, {"sprint_id": sprint_id}).fetchone()[0]
        return count > 0
    finally:
        session.close()
```

---

## Task 5: 后端 - 新增任务日志查询 API

**Files:**
- Modify: `backend/src/api/routes/scheduler.py`

**Step 1:** 新增 `GET /api/scheduler/logs` 端点
- Query params: `page`, `page_size`, `project_name`, `executed_date`, `task_type`
- 默认过滤 `executed_at` 为当天
- JOIN `project_configs` 获取 project_name
- 返回分页结果

```python
from datetime import datetime, date
from typing import Optional
from fastapi import Query, Depends
from sqlalchemy import and_, func, desc
from db.database import get_session
from db.models import TaskExecutionLog, ProjectConfig
from api.routes.auth import get_current_user_from_header


@router.get("/logs")
def get_execution_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    project_name: Optional[str] = Query(None),
    executed_date: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user_from_header),
):
    session = get_session()
    try:
        query = session.query(TaskExecutionLog, ProjectConfig.project_name).join(
            ProjectConfig,
            TaskExecutionLog.project_config_id == ProjectConfig.id
        )

        # 默认当天
        if executed_date:
            try:
                target_date = datetime.strptime(executed_date, "%Y-%m-%d")
            except ValueError:
                target_date = datetime.now()
        else:
            target_date = datetime.now()
        
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = query.filter(
            and_(
                TaskExecutionLog.executed_at >= day_start,
                TaskExecutionLog.executed_at <= day_end,
            )
        )

        if project_name:
            query = query.filter(ProjectConfig.project_name.like(f"%{project_name}%"))
        
        if task_type:
            query = query.filter(TaskExecutionLog.task_type == task_type)

        total = query.count()
        results = query.order_by(desc(TaskExecutionLog.executed_at)).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = []
        for log, proj_name in results:
            items.append({
                "id": log.id,
                "project_name": proj_name,
                "task_type": log.task_type,
                "executed_at": log.executed_at.isoformat() if log.executed_at else None,
                "scheduled_time": log.scheduled_time.isoformat() if log.scheduled_time else None,
                "status": log.status,
                "error_message": log.error_message,
                "task_exec_type": log.task_exec_type,
            })

        return {"total": total, "page": page, "page_size": page_size, "items": items}
    finally:
        session.close()
```

---

## Task 6: 后端 - 手动执行 API（story/task/sonar）

**Files:**
- Modify: `backend/src/api/routes/scheduler.py`

**Step 1:** 添加请求体模型和端点
```python
from pydantic import BaseModel

class ManualExecuteRequest(BaseModel):
    project_config_id: int


class ManualReportDataRequest(BaseModel):
    project_config_id: int
    sprint_id: str


@router.post("/manual/story-reminder")
def manual_story_reminder(req: ManualExecuteRequest):
    from api.scheduler import get_project_config_by_id, run_story_task

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = datetime.now()
    run_story_task(config, now)
    return {"status": "success", "message": f"项目 {config.project_name} 故事提醒已执行"}


@router.post("/manual/task-reminder")
def manual_task_reminder(req: ManualExecuteRequest):
    from api.scheduler import get_project_config_by_id, run_task_reminder

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = datetime.now()
    run_task_reminder(config, now)
    return {"status": "success", "message": f"项目 {config.project_name} 任务提醒已执行"}


@router.post("/manual/sonar-reminder")
def manual_sonar_reminder(req: ManualExecuteRequest):
    from api.scheduler import get_project_config_by_id, run_sonar_scan_reminder

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    now = datetime.now()
    run_sonar_scan_reminder(config, now)
    return {"status": "success", "message": f"项目 {config.project_name} Sonar提醒已执行"}
```

但注意: `run_story_task`/`run_task_reminder`/`run_sonar_scan_reminder` 内部调用的 `record_execution` 默认 `task_exec_type="automatic"`。
这些手动调用需要改为 `task_exec_type="manual"`。

所以在 scheduler.py 中添加包装函数:
```python
def manual_run_story_task(config: ProjectRemindConfig, scheduled_time: datetime):
    from task import remind_week_story as module
    try:
        module_run(module, config)
        record_execution(config.project_config_id, TASK_TYPE_STORY, scheduled_time, "success", task_exec_type="manual")
    except Exception as e:
        record_execution(config.project_config_id, TASK_TYPE_STORY, scheduled_time, "failed", str(e), task_exec_type="manual")
        raise

# 同理 manual_run_task_reminder, manual_run_sonar_scan_reminder
```

然后在 routes 中调用这些 manual 版本。

---

## Task 7: 后端 - report_data 手动执行 API + sprint 数据检查

**Files:**
- Modify: `backend/src/api/routes/scheduler.py`
- Modify: `backend/src/api/scheduler.py`

**Step 1:** sprint 数据检查端点
```python
@router.get("/manual/report-data/check/{project_config_id}/{sprint_id}")
def check_report_data_exists(project_config_id: int, sprint_id: str):
    from api.scheduler import check_sprint_data_exists
    exists = check_sprint_data_exists(sprint_id)
    return {"exists": exists}
```

**Step 2:** report_data 手动执行端点
```python
@router.post("/manual/report-data")
def manual_report_data(req: ManualReportDataRequest):
    from api.scheduler import get_project_config_by_id
    from task.report_rdm_data import process_sprint

    config = get_project_config_by_id(req.project_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="项目配置不存在")

    process_sprint(req.sprint_id)
    return {"status": "success", "message": f"项目 {config.project_name} 报表数据已执行"}
```

---

## Task 8: 前端 - API 层更新

**Files:**
- Modify: `frontend/src/api/jobs.ts`

**Step 1:** 添加新的接口类型和 API 函数
```typescript
export interface TaskLogItem {
  id: number
  project_name: string
  task_type: string
  executed_at: string | null
  scheduled_time: string | null
  status: string
  error_message: string
  task_exec_type: string
}

export interface TaskLogsResponse {
  total: number
  page: number
  page_size: number
  items: TaskLogItem[]
}

export interface ManualExecuteRequest {
  project_config_id: number
}

export interface ManualReportDataRequest {
  project_config_id: number
  sprint_id: string
}

export const jobApi = {
  // keep old ones for Dashboard compatibility
  getJobs() { ... },
  getTodayTasks() { ... },

  // new APIs
  getLogs(params: {
    page: number
    page_size: number
    project_name?: string
    executed_date?: string
    task_type?: string
  }) {
    return api.get<TaskLogsResponse>('/scheduler/logs', { params }) as unknown as Promise<TaskLogsResponse>
  },

  manualStoryReminder(data: ManualExecuteRequest) {
    return api.post('/scheduler/manual/story-reminder', data)
  },

  manualTaskReminder(data: ManualExecuteRequest) {
    return api.post('/scheduler/manual/task-reminder', data)
  },

  manualSonarReminder(data: ManualExecuteRequest) {
    return api.post('/scheduler/manual/sonar-reminder', data)
  },

  checkReportDataExists(projectConfigId: number, sprintId: string) {
    return api.get<{ exists: boolean }>(`/scheduler/manual/report-data/check/${projectConfigId}/${sprintId}`) as unknown as Promise<{ exists: boolean }>
  },

  manualReportData(data: ManualReportDataRequest) {
    return api.post('/scheduler/manual/report-data', data)
  },
}
```

---

## Task 9: 前端 - Jobs.vue 完全重写

**Files:**
- Modify: `frontend/src/views/jobs/Jobs.vue`

**Step 1:** 重写为任务执行记录表格 + 手动执行功能

页面结构:
- 顶部: 标题 + 筛选器行 (项目名称输入框, 执行日期选择器, 任务类型下拉) + 刷新按钮
- 中间: 手动执行操作区 (4 个按钮: 进度提醒/任务提醒/代码扫描/报表数据)
- 主内容: 分页表格 (序号/项目名称/任务类型/执行时间/调度时间/执行状态/错误信息/任务执行类型)
- 弹窗: 手动执行弹窗 (根据任务类型显示不同内容)

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { jobApi, type TaskLogItem } from '@/api/jobs'
import { projectApi, type ProjectConfig } from '@/api/projects'
import { reportsApi, type SprintOption } from '@/api/projects'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const logs = ref<TaskLogItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)

// filters
const filterProjectName = ref('')
const filterExecutedDate = ref(new Date().toISOString().slice(0, 10))
const filterTaskType = ref('')

// manual execution
const projects = ref<ProjectConfig[]>([])
const dialogVisible = ref(false)
const dialogTaskType = ref('')
const dialogProjectId = ref<number | null>(null)
const dialogSprintId = ref('')
const sprints = ref<SprintOption[]>([])
const dialogLoading = ref(false)

const taskTypeMap: Record<string, string> = {
  story_reminder: '进度提醒',
  task_reminder: '任务提醒',
  sonar_reminder: 'Sonar扫描',
  report_data: '报表数据',
}

const statusMap: Record<string, { text: string; cls: string }> = {
  success: { text: '成功', cls: 'status-success' },
  failed: { text: '失败', cls: 'status-failed' },
}

const execTypeMap: Record<string, string> = {
  automatic: '自动',
  manual: '手动',
}

const taskTypeOptions = [
  { value: '', label: '全部' },
  { value: 'story_reminder', label: '进度提醒' },
  { value: 'task_reminder', label: '任务提醒' },
  { value: 'sonar_reminder', label: 'Sonar扫描' },
  { value: 'report_data', label: '报表数据' },
]

onMounted(async () => {
  await Promise.all([loadLogs(), loadProjects()])
})

async function loadLogs() {
  loading.value = true
  try {
    const res = await jobApi.getLogs({
      page: currentPage.value,
      page_size: pageSize.value,
      project_name: filterProjectName.value || undefined,
      executed_date: filterExecutedDate.value || undefined,
      task_type: filterTaskType.value || undefined,
    })
    logs.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadProjects() {
  projects.value = await projectApi.getList()
}

async function loadSprints(projectConfigId: number) {
  sprints.value = await reportsApi.getSprints(projectConfigId)
}

function handleSearch() {
  currentPage.value = 1
  loadLogs()
}

function handleReset() {
  filterProjectName.value = ''
  filterExecutedDate.value = new Date().toISOString().slice(0, 10)
  filterTaskType.value = ''
  currentPage.value = 1
  loadLogs()
}

function openManualDialog(taskType: string) {
  dialogTaskType.value = taskType
  dialogProjectId.value = null
  dialogSprintId.value = ''
  sprints.value = []

  if (taskType === 'report_data') {
    // will load sprints when project is selected
  }

  dialogVisible.value = true
}

async function onProjectChange(projectId: number | null) {
  if (projectId && dialogTaskType.value === 'report_data') {
    await loadSprints(projectId)
  }
}

async function confirmExecute() {
  if (!dialogProjectId.value) {
    ElMessage.warning('请选择项目')
    return
  }

  if (dialogTaskType.value === 'report_data') {
    if (!dialogSprintId.value) {
      ElMessage.warning('请选择 Sprint')
      return
    }

    // check if data exists
    const { exists } = await jobApi.checkReportDataExists(dialogProjectId.value, dialogSprintId.value)
    if (exists) {
      await ElMessageBox.confirm(
        '该 Sprint 的相关表中已有数据，继续执行数据将被覆盖，是否继续？',
        '确认覆盖',
        { confirmButtonText: '继续执行', cancelButtonText: '取消', type: 'warning' }
      )
    }
  }

  dialogLoading.value = true
  try {
    switch (dialogTaskType.value) {
      case 'story_reminder':
        await jobApi.manualStoryReminder({ project_config_id: dialogProjectId.value })
        break
      case 'task_reminder':
        await jobApi.manualTaskReminder({ project_config_id: dialogProjectId.value })
        break
      case 'sonar_reminder':
        await jobApi.manualSonarReminder({ project_config_id: dialogProjectId.value })
        break
      case 'report_data':
        await jobApi.manualReportData({
          project_config_id: dialogProjectId.value,
          sprint_id: dialogSprintId.value,
        })
        break
    }
    ElMessage.success('任务执行成功')
    dialogVisible.value = false
    loadLogs()
  } catch {
    // error handled by interceptor
  } finally {
    dialogLoading.value = false
  }
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  })
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadLogs()
}
</script>
```

模板和样式省略，但需要完整实现。包含:
- 筛选器区域 (inline form)
- 4 个手动执行按钮 (el-button 组)
- el-table 展示日志列表
- el-pagination 分页
- el-dialog 手动执行弹窗:
  - 对于 story/task/sonar: 只显示项目选择器 (el-select)
  - 对于 report_data: 显示项目选择器 + sprint 选择器

---

## 验证步骤

1. 启动后端: `cd backend && uvicorn src.api.main:app --reload`
2. 启动前端: `cd frontend && npm run dev`
3. 访问 `/jobs` 页面，确认:
   - 默认展示当天日志
   - 可按项目名称筛选
   - 可按日期筛选
   - 手动执行 story/task/sonar 弹窗只选项目
   - 手动执行 report_data 弹窗选项目+sprint
   - sprint 已有数据时弹出覆盖确认