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
    sprint_id: string;
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

    checkReportDataExists(projectConfigId: number, sprintId: string) {
        return get<{ exists: boolean }>(
            `/scheduler/manual/report-data/check/${projectConfigId}/${sprintId}`
        )
    },

    manualReportData(data: ManualReportDataRequest) {
        return post("/scheduler/manual/report-data", data)
    },

    getReportDataStatus(sprintId: string) {
        return get<ReportDataStatusResponse>(
            `/scheduler/manual/report-data/status/${sprintId}`
        )
    },
};