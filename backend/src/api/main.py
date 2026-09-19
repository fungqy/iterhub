import logging
import sys
import threading
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, data_import, jobs, projects, reports, sprint_filter
from api.routes import scheduler as scheduler_routes
from api.scheduler import get_scheduler
from util.errors import install_exception_handler

logger = logging.getLogger("Main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时创建默认登录账号
    from db.database import create_default_user
    from util.qywx import PUSH_ENABLED

    create_default_user()

    # 后台线程初始化工作日数据:当前年(优先读 src/config/holiday-{year}.json),
    # 下一年缺失时可能回退 CDN,放入后台避免拉取阻塞服务启动
    def _init_holidays() -> None:
        from holiday import holidays

        try:
            holidays.update_holidays_table()
        except Exception:
            logger.exception("启动时初始化工作日数据失败")

    threading.Thread(
        target=_init_holidays, name="holiday-init", daemon=True
    ).start()

    # 仅在推送开启时打横幅:关闭时无输出,避免每次启动都噪声一片
    if PUSH_ENABLED:
        logger.warning("=" * 60)
        logger.warning(" 企微推送已开启 (PUSH_ENABLED=true)，将真实发送企微消息")
        logger.warning("=" * 60)

    scheduler = get_scheduler()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="迭代看板服务",
    description="迭代任务调度、提醒与项目管理工具API",
    version="1.0.0",
    lifespan=lifespan,
)

# 全局异常处理:把未捕获的 requests 异常归类为 502/504,
# 只打单行友好日志,不再输出完整 traceback。
install_exception_handler(app)

# CORS配置
# - allow_credentials=False: 本项目用 JWT Bearer header 鉴权,不使用 cookie,故无需 credentials
# - 同时 allow_origins=["*"] 在规范下与 credentials=True 互斥;改成 False 后即可保持通配
#   (生产环境若改为指定 origin,这里同步改回列表即可)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(scheduler_routes.router)
app.include_router(reports.router)
app.include_router(data_import.router)
app.include_router(sprint_filter.router)


@app.get("/", tags=["健康检查"])
async def root():
    """服务健康检查"""
    return {"status": "ok", "service": "iterhub", "version": "1.0.0"}


@app.get("/health", tags=["健康检查"])
async def health():
    """服务健康状态(深度:DB ping + 调度器状态)"""
    from sqlalchemy import text

    components: dict = {"database": "unknown", "scheduler": "unknown"}
    overall_ok = True

    # 1) MySQL ping:用 SELECT 1 验证连接池可用
    try:
        from db.database import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as e:
        components["database"] = f"error: {e}"
        overall_ok = False

    # 2) 调度器状态:已启动且能列出 job
    try:
        scheduler = get_scheduler()
        running = getattr(scheduler.scheduler, "running", False)
        components["scheduler"] = "ok" if running else "not_running"
        if not running:
            overall_ok = False
    except Exception as e:
        components["scheduler"] = f"error: {e}"
        overall_ok = False

    return {
        "status": "healthy" if overall_ok else "degraded",
        "components": components,
    }



