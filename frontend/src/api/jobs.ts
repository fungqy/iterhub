import { get, post } from "./index";

export interface JobInfo {
    id: string;
    name: string;
    next_run_time: string | null;
    trigger: string;
}

export interface JobsResponse {
    total: number;
    jobs: JobInfo[];
}

export interface TodayTask {
    project_name: string;
    task_type: string;
    scheduled_time: string;
    status: "pending" | "success" | "failed" | "expired";
    executed_at: string | null;
}

export interface TaskLogItem {
    id: number;
    project_name: string;
    task_type: string;
    executed_at: string | null;
    scheduled_time: string | null;
    status: string;
    error_message: string;
    task_exec_type: string;
}

export interface TaskLogsResponse {
    total: number;
    page: number;
    page_size: number;
    items: TaskLogItem[];
}

export interface ManualExecuteRequest {
    project_config_id: number;
}

export interface ManualReportDataRequest {
    project_config_id: number;
    /** 一次可入队多个 Sprint;后端按顺序排队执行(见 scheduler.py 的说明) */
    sprint_ids: string[];
}

/** 未入队的 Sprint 及原因(已在执行 / RDM 未找到) */
export interface ManualReportDataSkipped {
    sprint_id: string;
    reason: string;
}

export interface ManualReportDataResponse {
    status: string;
    /** 真正入队的 Sprint —— 轮询只盯这些,被跳过的不会产生状态 */
    task_ids: string[];
    skipped: ManualReportDataSkipped[];
    message: string;
}

export interface ReportDataStatusResponse {
    sprint_id: string;
    status: "pending" | "running" | "success" | "failed" | "unknown";
    started_at?: number;
    finished_at?: number;
    error?: string;
}

export interface TaskLogsQuery {
    page: number;
    page_size: number;
    project_name?: string;
    executed_date?: string;
    task_type?: string;
}

export const jobApi = {
    getJobs() {
        return get<JobsResponse>("/jobs")
    },

    getTodayTasks() {
        return get<TodayTask[]>("/scheduler/today-tasks")
    },

    triggerJob(jobId: string) {
        return post(`/jobs/${jobId}/trigger`)
    },

    triggerStoryReminder() {
        return post("/jobs/story-reminder/trigger")
    },

    triggerTaskReminder() {
        return post("/jobs/task-reminder/trigger")
    },

    getLogs(params: TaskLogsQuery) {
        return get<TaskLogsResponse>("/scheduler/logs", params)
    },

    manualStoryReminder(data: ManualExecuteRequest) {
        return post("/scheduler/manual/story-reminder", data)
    },

    manualTaskReminder(data: ManualExecuteRequest) {
        return post("/scheduler/manual/task-reminder", data)
    },

    manualSonarReminder(data: ManualExecuteRequest) {
        return post("/scheduler/manual/sonar-reminder", data)
    },

    /**
     * 批量检查所选 Sprint 是否已有数据。
     * 返回 `existing` = 命中的 sprint_id 列表;多选时只发一次请求(后端一次 IN 查询)。
     */
    checkReportDataExists(sprintIds: string[]) {
        return post<{ existing: string[] }>(
            "/scheduler/manual/report-data/check",
            { sprint_ids: sprintIds }
        )
    },

    manualReportData(data: ManualReportDataRequest) {
        return post<ManualReportDataResponse>(
            "/scheduler/manual/report-data",
            data
        )
    },

    getReportDataStatus(sprintId: string) {
        return get<ReportDataStatusResponse>(
            `/scheduler/manual/report-data/status/${sprintId}`
        )
    },
};