from __future__ import annotations

import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 迁移到 api/services 的叶子函数在此做兜底 re-export,
# 以维持既有 `from api.scheduler import X` 与 `patch("api.scheduler.X")` 路径不破坏。
from api.services.execution_log import record_execution, to_naive_beijing
from api.services.project_configs import get_project_configs
from util.dateattr import DateAttr
from util.jira import ProjectRemindConfig
from util.qywx import send_or_log

# 北京时区，所有调度时间比较与日志记录统一使用
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_beijing() -> datetime:
    """返回当前北京时间（带时区信息）"""
    return datetime.now(BEIJING_TZ)


# 配置日志
logger = logging.getLogger("Scheduler")

# 任务类型常量
TASK_TYPE_STORY = "story_reminder"
TASK_TYPE_TASK = "task_reminder"
TASK_TYPE_SONAR = "sonar_reminder"
TASK_TYPE_REPORT = "report_data"

# 任务类型 -> (中文名, 配置开关字段, 配置时间字段)
_TASK_NAME = {
    TASK_TYPE_STORY: "故事提醒任务",
    TASK_TYPE_TASK: "任务到期提醒",
    TASK_TYPE_SONAR: "Sonar扫描提醒",
}
_TASK_META = {
    TASK_TYPE_STORY: ("need_story_remind", "story_remind_time"),
    TASK_TYPE_TASK: ("need_task_remind", "task_remind_time"),
    TASK_TYPE_SONAR: ("need_sonar_scan_remind", "sonar_remind_time"),
}


def parse_time(time_str: str) -> tuple[int, int]:
    """解析 HH:MM 格式时间字符串为 (hour, minute)"""
    if not time_str:
        return 0, 0
    parts = time_str.split(":")
    try:
        hour = int(parts[0]) if len(parts) > 0 else 0
        minute = int(parts[1]) if len(parts) > 1 else 0
        return hour, minute
    except (ValueError, IndexError):
        return 0, 0


def _parse_remind_time(remind_time: str) -> tuple[int, int] | None:
    """校验并解析提醒时间；非法/空返回 None，合法 HH:MM 返回 (hour, minute)。

    与 parse_time 的区别：parse_time 对 "bad" 也会返回 (0, 0)，无法区分
    "00:00"(合法) 与 "bad"(非法)。此处用正则 + 范围二次校验，确保只有
    真实存在的 HH:MM 才会注册为调度任务。
    """
    if not remind_time:
        return None
    hour, minute = parse_time(remind_time)
    if re.fullmatch(r"\d{1,2}:\d{2}", remind_time.strip()) and 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def check_time_match(config_time: str, now: datetime) -> bool:
    """检查当前时间是否匹配指定的提醒时间"""
    if not config_time:
        return False
    hour, minute = parse_time(config_time)
    return now.hour == hour and now.minute == minute


def module_run(module, remind_config: ProjectRemindConfig):
    """统一处理消息生成与发送逻辑

    认证通过 ProjectRemindConfig.auth_config 由 task module 显式传递给
    ProjectUtil/Sprint，不再使用全局 set_default_auth。
    """
    message_list = module.gene_message(remind_config)
    if not message_list:
        return
    for message in message_list:
        if message:
            logger.info(f"[{remind_config.project_name}] {message}")
            send_or_log(remind_config.robot_key, message)


# ---------------------------------------------------------------------------
# 工作日判断：日级缓存
#
# 旧实现下 run_all_* 每分钟都被唤醒一次，每次都走 DateAttr().is_workday 查一次
# 工作日表（DB 查询）。改为精确 cron 后虽然触发频率大幅下降，但 reload/手动跑
# 仍可能密集调用；这里按"自然日"缓存一次，跨日自动失效。
# 注意：测试通过 monkeypatch 替换 api.scheduler.DateAttr，reset_scheduler_for_tests
# 会在每个用例前后清空缓存，因此不影响测试隔离。
# ---------------------------------------------------------------------------
_workday_cache_date: datetime.date | None = None
_workday_cache_val: bool | None = None


def is_workday_today() -> bool:
    """返回今天是否为工作日（按自然日缓存，避免重复查库）"""
    global _workday_cache_date, _workday_cache_val
    today = now_beijing().date()
    if _workday_cache_date == today and _workday_cache_val is not None:
        return _workday_cache_val
    val = bool(DateAttr().is_workday)
    _workday_cache_date = today
    _workday_cache_val = val
    return val


def _reset_workday_cache() -> None:
    """仅供测试使用：清空工作日缓存。"""
    global _workday_cache_date, _workday_cache_val
    _workday_cache_date = None
    _workday_cache_val = None


# ---------------------------------------------------------------------------
# 执行层（自动 + 手动共用）
# ---------------------------------------------------------------------------

def _execute_task(module, config: ProjectRemindConfig, scheduled_time: datetime, task_type: str):
    """执行单个任务的统一封装：消息生成/发送 + 执行日志(分类后的友好错误)。

    三类提醒任务原先各自复制一份 try/except，且 run_task_reminder 记录的是
    原始 str(e) 而其他两类记录 classify_error 的友好信息——口径不一致。
    统一在此处收口，全部记录友好信息。
    """
    logger.info(f"[{config.project_name}] 执行 [{_TASK_NAME[task_type]}] ...")
    try:
        module_run(module, config)
        record_execution(config.project_config_id, task_type, scheduled_time, "success")
    except Exception as e:
        from util.errors import classify_error

        _status, friendly = classify_error(e)
        logger.error(
            f"[{config.project_name}] 执行 [{_TASK_NAME[task_type]}] 失败: {friendly}"
        )
        record_execution(config.project_config_id, task_type, scheduled_time, "failed", friendly)


def run_story_task(remind_config: ProjectRemindConfig, scheduled_time: datetime):
    """执行故事提醒任务"""
    from task import remind_week_story as module

    _execute_task(module, remind_config, scheduled_time, TASK_TYPE_STORY)


def run_task_reminder(remind_config: ProjectRemindConfig, scheduled_time: datetime):
    """执行子任务到期提醒"""
    from task import remind_expire_task as module

    _execute_task(module, remind_config, scheduled_time, TASK_TYPE_TASK)


def run_sonar_scan_reminder(remind_config: ProjectRemindConfig, scheduled_time: datetime):
    """执行Sonar扫描提醒"""
    import task.remind_sonar_scan as sonar_module

    _execute_task(sonar_module, remind_config, scheduled_time, TASK_TYPE_SONAR)


def _run_task_for_type(task_type: str, config: ProjectRemindConfig, scheduled_time: datetime):
    """按任务类型分派到对应的 run_* 执行函数。"""
    if task_type == TASK_TYPE_STORY:
        run_story_task(config, scheduled_time)
    elif task_type == TASK_TYPE_TASK:
        run_task_reminder(config, scheduled_time)
    elif task_type == TASK_TYPE_SONAR:
        run_sonar_scan_reminder(config, scheduled_time)


def _manual_run(task_type: str, config: ProjectRemindConfig, scheduled_time: datetime, module):
    """手动执行单个任务的统一封装（与 _execute_task 几乎一致，但失败要向上抛出）。

    注意 record_execution 自身已吞掉 DB 异常（见 execution_log 实现），因此把
    "执行业务"与"记录失败日志"分两层：业务异常被捕获并记一条 failed 日志后原样
    re-raise（交给全局 handler 决定 HTTP 状态码）；记录动作本身不再进 try，
    避免把 record_execution 的 DB 错误掩盖掉真正的业务异常。
    """
    logger.info(f"[{config.project_name}] 手动执行 [{_TASK_NAME[task_type]}] ...")
    try:
        module_run(module, config)
    except Exception as e:
        from util.errors import classify_error

        _status, friendly = classify_error(e)
        logger.error(
            f"[{config.project_name}] 手动执行 [{_TASK_NAME[task_type]}] 失败: {friendly}"
        )
        # 记录失败日志（record_execution 内部已吞掉 DB 异常，不会再次抛出）
        record_execution(
            config.project_config_id, task_type, scheduled_time, "failed", friendly, task_exec_type="manual"
        )
        raise
    record_execution(
        config.project_config_id, task_type, scheduled_time, "success", task_exec_type="manual"
    )


def manual_run_story_task(config: ProjectRemindConfig, scheduled_time: datetime):
    from task import remind_week_story as module

    _manual_run(TASK_TYPE_STORY, config, scheduled_time, module)


def manual_run_task_reminder(config: ProjectRemindConfig, scheduled_time: datetime):
    from task import remind_expire_task as module

    _manual_run(TASK_TYPE_TASK, config, scheduled_time, module)


def manual_run_sonar_scan_reminder(config: ProjectRemindConfig, scheduled_time: datetime):
    import task.remind_sonar_scan as sonar_module

    _manual_run(TASK_TYPE_SONAR, config, scheduled_time, sonar_module)


def get_today_tasks_status():
    """获取今日任务状态"""
    if not DateAttr().is_workday:
        return []

    from sqlalchemy import and_

    from db.database import get_session
    from db.models import ProjectConfig, TaskExecutionLog

    with get_session() as session:
        today = now_beijing().replace(hour=0, minute=0, second=0, microsecond=0)
        # ⚠ 过滤边界必须是 naive 北京时间:TaskExecutionLog.scheduled_time 是无时区列,
        #   拿 aware 值比较只能靠驱动丢 tzinfo 才「碰巧正确」(见 to_naive_beijing)。
        day_start = to_naive_beijing(today)
        day_end = to_naive_beijing(
            today.replace(hour=23, minute=59, second=59)
        )

        # 获取今日所有执行记录
        logs = (
            session.query(TaskExecutionLog)
            .filter(
                and_(
                    TaskExecutionLog.scheduled_time >= day_start,
                    TaskExecutionLog.scheduled_time <= day_end,
                )
            )
            .all()
        )

        # 构建执行记录映射 {(project_config_id, task_type): log}
        log_map = {(log.project_config_id, log.task_type): log for log in logs}

        # 获取所有项目配置
        configs = session.query(ProjectConfig).all()

        result = []
        now = now_beijing()

        for config in configs:
            settings = config.reminder_settings
            if not settings:
                continue

            # 检查每个任务类型
            tasks = [
                (
                    "story_reminder",
                    settings.need_story_remind,
                    settings.story_remind_time,
                ),
                ("task_reminder", settings.need_task_remind, settings.task_remind_time),
                (
                    "sonar_reminder",
                    settings.need_sonar_scan_remind,
                    settings.sonar_remind_time,
                ),
            ]

            for task_type, needed, remind_time in tasks:
                if not needed or not remind_time:
                    continue

                # 计算计划执行时间
                hour, minute = parse_time(remind_time)
                scheduled_time = today.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )

                # 获取执行记录
                log = log_map.get((config.id, task_type))

                # 确定状态
                if log:
                    status = log.status
                    executed_at = (
                        log.executed_at.isoformat() if log.executed_at else None
                    )
                elif scheduled_time < now:
                    status = "expired"  # 已过期未执行
                    executed_at = None
                else:
                    status = "pending"  # 待执行
                    executed_at = None

                result.append(
                    {
                        "project_name": config.project_name,
                        "task_type": task_type,
                        "scheduled_time": scheduled_time.isoformat(),
                        "status": status,
                        "executed_at": executed_at,
                    }
                )

        # 按计划执行时间排序
        result.sort(key=lambda x: x["scheduled_time"])
        return result


def _run_all_for_type(task_type: str, need_flag: str, time_attr: str, run_fn):
    """按任务类型遍历所有项目配置，工作日门禁 + 到点(分钟级)匹配后执行。

    保留为"手动按类型跑全部"的入口（HTTP /jobs/{type}/run 调用），
    自动触发已改由 dispatch_project_task 精确 cron 负责。
    """
    now = now_beijing()

    logger.info(
        f"============================= {now} {_TASK_NAME[task_type]} ============================="
    )

    # 工作日判断放在运行时，避免 reload_jobs 在非工作日清空所有任务
    if not is_workday_today():
        logger.info(f"非工作日，跳过 [{_TASK_NAME[task_type]}] 任务")
        return

    project_configs = get_project_configs()
    for config in project_configs:
        if not getattr(config, need_flag):
            continue
        # 检查项目是否配置了提醒时间
        remind_time = getattr(config, time_attr) or ""
        if not remind_time:
            logger.info(f"[{config.project_name}] 未配置 [{_TASK_NAME[task_type]}] 时间，跳过")
            continue
        # 检查时间是否匹配
        if check_time_match(remind_time, now):
            # 计算计划执行时间
            hour, minute = parse_time(remind_time)
            scheduled_time = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            run_fn(config, scheduled_time)
        else:
            logger.debug(
                f"[{config.project_name}] 当前时间不匹配 [{_TASK_NAME[task_type]}] 时间({remind_time})，跳过"
            )


def run_all_story_tasks():
    """执行所有需要提醒的项目的故事提醒任务"""
    _run_all_for_type(TASK_TYPE_STORY, "need_story_remind", "story_remind_time", run_story_task)


def run_all_task_reminders():
    """执行所有需要提醒的项目的任务提醒"""
    _run_all_for_type(TASK_TYPE_TASK, "need_task_remind", "task_remind_time", run_task_reminder)


def run_all_sonar_scan_reminders():
    """执行所有需要提醒的项目的Sonar扫描提醒"""
    _run_all_for_type(
        TASK_TYPE_SONAR, "need_sonar_scan_remind", "sonar_remind_time", run_sonar_scan_reminder
    )


def dispatch_project_task(task_type: str, project_config_id: int):
    """per-(项目, 类型) 精确 cron 的回调。

    由 APScheduler 在配置的 hour:minute 精确触发，因此：
    1. 进程短时宕机可在 misfire_grace_time 内自动补发（旧"每分钟轮询+比对"做不到）；
    2. 非到点分钟零开销，不再每分钟空转查库。
    运行时仍做工作日门禁与配置有效性校验，配置变更/禁用后下一次触发自然失效。
    """
    if task_type not in _TASK_META:
        logger.warning(f"未知任务类型: {task_type}")
        return

    if not is_workday_today():
        logger.debug(f"非工作日，跳过 [{task_type}] 项目 {project_config_id}")
        return

    config = get_project_config_by_id(project_config_id)
    if config is None:
        logger.warning(f"项目配置不存在 id={project_config_id}，跳过 [{task_type}]")
        return

    need_flag, time_attr = _TASK_META[task_type]
    if not getattr(config, need_flag):
        return

    parsed = _parse_remind_time(getattr(config, time_attr) or "")
    if parsed is None:
        return

    hour, minute = parsed
    now = now_beijing()
    scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    _run_task_for_type(task_type, config, scheduled_time)


class TaskScheduler:
    """任务调度器

    每个(项目, 任务类型)注册一个精确 cron 任务(CronTrigger(hour, minute))，
    由 APScheduler 在到点时触发 dispatch_project_task；工作日判断刻意放在
    dispatch 运行时，以确保 reload_jobs 能正确重建所有 job，且配置变更即时生效。
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=BEIJING_TZ)
        self._setup_jobs()

    def _build_project_jobs(self):
        """根据当前项目配置，为每个(项目, 类型)注册精确 cron 任务。

        读取配置失败(DB 瞬时不可用等)时只记日志、本轮注册 0 个 job，
        不向上抛——避免调度器构造失败拖垮整个应用启动；后续 reload_jobs
        或周期性 reload 会重新读取配置补齐。
        """
        try:
            project_configs = get_project_configs()
        except Exception as e:
            logger.warning(f"读取项目配置失败，跳过本次 job 注册: {e}")
            return
        for config in project_configs:
            pid = config.project_config_id
            for task_type, (need_flag, time_attr) in _TASK_META.items():
                if not getattr(config, need_flag):
                    continue
                parsed = _parse_remind_time(getattr(config, time_attr) or "")
                if parsed is None:
                    continue
                hour, minute = parsed
                trigger = CronTrigger(hour=hour, minute=minute, timezone=BEIJING_TZ)
                job_id = f"{task_type}:{pid}"
                self.scheduler.add_job(
                    dispatch_project_task,
                    trigger,
                    args=[task_type, pid],
                    id=job_id,
                    name=f"{_TASK_NAME[task_type]} · {config.project_name}",
                    replace_existing=True,
                    misfire_grace_time=300,
                    coalesce=True,
                    max_instances=1,
                )

    def _setup_jobs(self):
        """根据项目配置注册所有精确 cron 任务。"""
        self._build_project_jobs()
        logger.info("调度任务已根据项目配置注册")

    def reload_jobs(self):
        """重新加载所有任务配置"""
        # 移除所有现有任务
        self.scheduler.remove_all_jobs()
        # 重新构建任务（读取最新项目配置，使新增/改时间/禁用即时生效）
        self._build_project_jobs()
        logger.info("调度任务已重新加载")

    def start(self):
        """启动调度器"""
        if self.scheduler.running:
            logger.info("任务调度器已在运行，跳过 start")
            return
        self.scheduler.start()
        logger.info("任务调度器已启动")

    def stop(self):
        """停止调度器"""
        if not self.scheduler.running:
            return
        self.scheduler.shutdown()
        logger.info("任务调度器已停止")

    def get_jobs(self):
        """获取所有任务状态"""
        jobs = []
        for job in self.scheduler.get_jobs():
            # APScheduler 3.x：next_run_time 仅在 scheduler.start() 之后才会被赋值，
            # 此前访问会抛 AttributeError，所以用 getattr 兜底。
            next_run_time = getattr(job, "next_run_time", None)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": str(next_run_time) if next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs

    def run_job_now(self, job_id: str):
        """手动触发任务。

        - job_id 为三大类型常量时：运行该类型下所有项目(run_all_*)；
        - job_id 为 "{type}:{project_config_id}" 时：仅运行该项目该类型；
        - 其他：返回 error。
        """
        if job_id == TASK_TYPE_STORY:
            run_all_story_tasks()
            return {"status": "success", "message": "故事提醒任务已执行"}
        elif job_id == TASK_TYPE_TASK:
            run_all_task_reminders()
            return {"status": "success", "message": "任务提醒任务已执行"}
        elif job_id == TASK_TYPE_SONAR:
            run_all_sonar_scan_reminders()
            return {"status": "success", "message": "Sonar扫描提醒任务已执行"}

        if ":" in job_id:
            task_type, _, pid_str = job_id.partition(":")
            if task_type in _TASK_META:
                try:
                    pid = int(pid_str)
                except ValueError:
                    return {"status": "error", "message": f"未知任务: {job_id}"}
                dispatch_project_task(task_type, pid)
                return {"status": "success", "message": f"{_TASK_NAME[task_type]} 项目 {pid} 已执行"}

        return {"status": "error", "message": f"未知任务: {job_id}"}


# 全局调度器单例（线程安全的懒加载）
_scheduler_instance: TaskScheduler | None = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> TaskScheduler:
    """获取全局调度器实例（线程安全的单例）

    main.py 的 lifespan、所有路由层、所有手动触发入口都必须通过此函数
    获取调度器，禁止在任何地方直接 `TaskScheduler()`，以避免出现多实例
    导致接口操作的不是真正在运行的那个调度器。
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        with _scheduler_lock:
            if _scheduler_instance is None:
                _scheduler_instance = TaskScheduler()
    return _scheduler_instance


def start_scheduler():
    """启动调度器"""
    get_scheduler().start()


def stop_scheduler():
    """停止调度器"""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance:
            _scheduler_instance.stop()
            _scheduler_instance = None


def reset_scheduler_for_tests():
    """仅供测试使用：重置全局单例，使得每个测试用例都能获得干净的 TaskScheduler。"""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None:
            try:
                _scheduler_instance.stop()
            except Exception:
                pass
        _scheduler_instance = None
    # 工作日缓存与单例绑定，重置时一并清空，保证测试隔离
    _reset_workday_cache()


# get_project_config_by_id 需在 dispatch_project_task 中使用，置于文件尾部避免顶部环状依赖
from api.services.project_configs import get_project_config_by_id  # noqa: E402
