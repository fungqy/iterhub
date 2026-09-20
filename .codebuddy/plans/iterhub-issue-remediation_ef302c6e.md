---
name: iterhub-issue-remediation
overview: 按「安全→正确性→前端→可维护性」四阶段，依次修复代码审查发现的全部问题；涉及真实凭据轮换、脱敏口径、高风险事务改造与大文件拆分时，先向用户确认再动手。
todos:
  - id: sanitize-secrets
    content: 凭据去明文化：改 init_db.sql、docker-compose、deployment.yml、README、.env.example 为环境变量与占位符
    status: completed
  - id: disable-register
    content: 关闭自助注册接口；默认管理员口令改读环境变量且不再打印明文日志
    status: completed
  - id: add-auth
    content: 用 [subagent:code-explorer] 确认 jobs/scheduler 全量调用方后补登录鉴权，并同步改造受影响测试
    status: completed
  - id: fix-pagination
    content: 修复 jira.py 中 Sprint.issues 分页越界与非 200 死循环，并统一走重试封装
    status: completed
  - id: harden-backend
    content: 修复后端静默吞异常、本周边界被冻结、aware/naive 时区混用等正确性问题
    status: completed
  - id: dedupe-frontend-api
    content: 用 [skill:lsp-code-analysis] 定位引用后消除 projects.ts 与 reports.ts 重复定义并统一 getBugList 签名
    status: completed
  - id: fix-frontend-lifecycle
    content: 修复前端事件监听泄漏与轮询残留提示，并为失败分支补 catch 与用户反馈
    status: completed
    dependencies:
      - dedupe-frontend-api
  - id: confirm-decisions
    content: 就 robot_key 脱敏、读接口写库、派生表事务、大文件拆分等高风险点向用户确认后再实施
    status: completed
  - id: cleanup-deadcode
    content: 清理死代码与 __all__、收敛重复实现、错误信息脱敏、收紧 CORS 与硬编码内网地址
    status: completed
    dependencies:
      - dedupe-frontend-api
  - id: verify-and-report
    content: 跑 compileall、pytest 与 npm run build，并汇总需你手动执行的凭据轮换清单
    status: completed
    dependencies:
      - sanitize-secrets
      - disable-register
      - add-auth
      - fix-pagination
      - harden-backend
      - dedupe-frontend-api
      - fix-frontend-lifecycle
      - cleanup-deadcode
---

## 产品概述

对 IterHub（RDM 迭代看板，前后端）执行一轮按优先级排序的安全加固与缺陷修复。不改变既有业务功能与界面形态，目标是消除明文凭据、补齐接口鉴权、修复会污染报表数据的取数缺陷，并清理前后端重复实现与资源泄漏。

## 核心功能（本次修复范围）

- **凭据去明文化**：把代码、配置、文档中的明文数据库口令改为环境变量引用与占位符；保持 `backend/.env` 真实值不动，真实凭据轮换由用户后续自行执行
- **认证与权限**：关闭自助注册；默认管理员口令改为从环境变量读取且不再打印明文；为任务调度路由与作业页路由的全部接口补齐登录校验（健康检查保持匿名），并同步改造受影响的后端测试
- **取数正确性**：修复 RDM issue 分页在 500 条以上取不全并重复累加、接口异常时无限循环打同一地址的问题
- **后端健壮性**：消除静默吞异常；修复「本周」边界被进程启动时间冻结、时间串二次时区转换、带时区与不带时区混用导致的判定偏差
- **前端一致性**：消除两套重复的报表接口模块与同名冲突签名（保留两个模块，统一 getBugList 参数顺序）；修复事件监听未清理造成的泄漏与轮询残留提示；补齐失败分支的用户反馈
- **整洁度**：清理死代码与错误导出、收敛重复实现、错误信息脱敏、收紧跨域配置、去硬编码内网地址

## 需用户确认的决策点（执行到相应步骤时即时中断并询问）

- 企微 robot_key 是否在项目列表接口脱敏（会影响项目编辑回显）
- 报表 Sprint 列表接口「读接口却写库」是否改为纯只读
- 主表与派生表分属两个事务的一致性是否本轮改造
- 超大文件（后端 data_import.py、reports.py，前端弹窗组件）是否纳入本轮拆分
- 默认管理员口令环境变量缺失时的期望行为（拒绝启动 或 跳过创建并告警）

## 技术栈

沿用现有技术栈，不引入新依赖、不改变架构：

- 后端：Python 3.10+ / FastAPI / SQLAlchemy / PyMySQL / APScheduler / bcrypt + python-jose / pytest
- 前端：Vue 3 + TypeScript + Vite 5 + PrimeVue 4 + Pinia
- 数据库：MySQL 8
- 部署：Docker Compose / Kubernetes（deployment.yml）

## 实施策略

按「链路安全 → 接口鉴权 → 取数正确性 → 后端健壮性 → 前端 → 整洁度与验证」的顺序分批推进，每批收尾跑一次验证，保证每步都可独立回滚。全部改动落在既有分层（路由层 / 服务层 / 任务层 / 工具层）之内，复用既有工具函数（如 `util/qywx.py:_mask_key`、`util/errors.py` 的脱敏口径），不新增模式。

关键决策与理由：

- **鉴权用依赖注入而非中间件**：沿用 `api/auth.py:get_current_user_from_header`，在 `APIRouter` 或各端点挂 `Depends`，与既有 `projects.py`、`reports.py` 写法一致；`/` 与 `/health` 不在这些路由内，天然保持匿名，k8s 探针不受影响。
- **凭据只做去明文化**：`MSQL_DSN` 已由 `db/config.py:get_dsn()` 从环境变量读取，故改动集中在「配置样例与部署清单里的字面值」以及被 git 跟踪的 `init_db.sql`；`docker-compose` 使用 `${VAR:?}` 强制注入，避免静默回退到弱口令。
- **分页修复保持签名不变**：`Sprint.issues()` 只修内部循环（不可变模板 + 每轮重组 URL + 非 200 抛错或重试），对外行为与返回结构不变，`rdm_report_data` 调用方零改动。
- **时间处理统一到 `Asia/Shanghai`**：`DateAttr` 去掉静态方法的 `date.today()` 默认参数、任务模块内 `DateAttr` 改为惰性求值，避免 import 期冻结；`to_beijing_mysql_datetime` 增加「已是 naive 北京时间」的短路分支。
- **前端只修冲突不合并**：按你的决策保留两个 API 模块，仅删除重复类型定义、把 `getBugList` 签名统一为后端真实顺序 `(sprintId, developer?, priority?, tag?)`，并显式标注两个 `getSprints` 的数据源差异。

性能与可靠性：均为常量级改动，不新增查询轮次；`project_configs.get_project_configs()` 的 N+1 收敛可减少每项目一次建连；后端 `pytest` 缓存与前端 `vue-tsc` 增量为常规量级。

## 执行注意事项

- 后端命令必须用 `backend/.venv/Scripts/python.exe`（系统 PATH 无 Python）；验证基线：`pytest tests -q` 当前 175 passed，前端 `npm run build` 当前通过
- 补鉴权后 `backend/tests/api/test_scheduler_routes.py`、`backend/tests/api/test_manual_endpoint_e2e.py` 会变 401，必须同步注入 token 或 override 依赖，切勿只改产品代码
- 不修改 `backend/.env` 的真实值；不删除 `.codebuddy`；不新增临时脚本，如产生必须清理
- 不改动 `backend/sql/iterdb.sql`、`iterdb-0915.sql`、`docs/*.xlsx`（已被 gitignore，仅提醒用户轮换密钥）
- 每批改动保持向后兼容（响应字段只增不减），涉及确认点的改动先停手询问

## 目录结构（受影响文件清单）

```
iterhub/
├── backend/
│   ├── .env.example                                  # [MODIFY] 示例 DSN 改占位符，与 README 口径统一
│   ├── docker-compose.yml                            # [MODIFY] DSN/ROOT_PASSWORD/密码改 ${VAR:?} 引用
│   ├── src/
│   │   ├── api/
│   │   │   ├── main.py                               # [MODIFY] 收紧 CORS origins（保持 /health 匿名）
│   │   │   ├── auth.py                               # [MODIFY] utcnow 改 now(timezone.utc)；移除未用的 get_current_user
│   │   │   ├── routes/
│   │   │   │   ├── auth.py                           # [MODIFY] 关闭/移除 POST /register
│   │   │   │   ├── jobs.py                           # [MODIFY] 5 个接口补齐登录依赖
│   │   │   │   ├── scheduler.py                      # [MODIFY] 除 /logs 外的 10 个接口补齐登录依赖
│   │   │   │   ├── projects.py                       # [MODIFY] robot_key 回吐口径（视确认结果）
│   │   │   │   └── data_import.py                    # [MODIFY] 异常回显改走 util/errors 脱敏口径
│   │   │   └── services/
│   │   │       ├── project_configs.py                # [MODIFY] check_sprint_data_exists 异常语义；N+1 收敛
│   │   │       └── execution_log.py                  # [MODIFY] aware 值写入 naive 列的口径统一
│   │   ├── db/
│   │   │   ├── config.py                             # [MODIFY] docstring 示例口令改占位符
│   │   │   ├── database.py                           # [MODIFY] create_default_user 口令读环境变量、不打印明文
│   │   │   ├── dboperator.py                         # [MODIFY] truncate_table / exec_sql 不再吞异常
│   │   │   └── sqls.py                               # [DELETE] 整文件仅注释的死模块
│   │   ├── task/
│   │   │   ├── __init__.py                           # [MODIFY] all 改 __all__，移除死别名
│   │   │   ├── report_wiki_data.py                   # [MODIFY] 无生产入口的死代码与 import 期强校验
│   │   │   ├── remind_week_story.py                  # [MODIFY] 模块级 DateAttr 改惰性求值
│   │   │   ├── remind_expire_task.py                 # [MODIFY] 同上
│   │   │   └── remind_sonar_scan.py                  # [MODIFY] 同上；GitLab 请求补状态码校验
│   │   └── util/
│   │       ├── jira.py                               # [MODIFY] 分页/死循环修复、统一重试、时区二次转换短路
│   │       └── dateattr.py                           # [MODIFY] 去 date.today() 默认参数、时区口径统一、删死方法
│   ├── sql/init_db.sql                               # [MODIFY] 明文口令改占位符（该文件已被 git 跟踪）
│   └── tests/api/
│       ├── conftest.py                               # [MODIFY] 新增鉴权夹具（注入 token / override 依赖）
│       ├── test_scheduler_routes.py                  # [MODIFY] 适配鉴权后调用
│       └── test_manual_endpoint_e2e.py               # [MODIFY] 同上
├── frontend/
│   └── src/
│       ├── api/
│       │   ├── projects.ts                           # [MODIFY] 删重复类型与死方法、统一 getBugList 签名
│       │   └── reports.ts                            # [MODIFY] 同步同一签名与注释口径
│       └── views/
│           ├── dashboard/Dashboard.vue               # [MODIFY] 补 catch、any 改 ProjectConfig
│           ├── jobs/Jobs.vue                         # [MODIFY] 补 catch
│           ├── jobs/components/ManualExecuteDialog.vue # [MODIFY] stopPolling 同时 removeGroup
│           ├── doc-import/DocBugImport.vue           # [MODIFY] 补 catch（含 confirm.require 回调）
│           ├── doc-import/DocTestcaseImport.vue      # [MODIFY] 同上
│           ├── projects/ProjectList.vue              # [MODIFY] robot_key 回显口径（视确认结果）
│           └── reports/
│               ├── Reports.vue                       # [MODIFY] scroll 监听在卸载/换元素时移除
│               ├── BugDetailDialog.vue               # [MODIFY] 新增 onUnmounted 移除 window resize
│               └── components/charts.ts              # [MODIFY] RDM_BROWSE_URL 改环境变量
├── docker-compose.yml                                # [MODIFY] DSN 改 ${MSQL_DSN:?}
├── deployment.yml                                    # [MODIFY] DSN 改 Secret/环境变量引用
└── README.md                                         # [MODIFY] 示例 DSN 改占位符
```

## 关键实现要点（接口级）

- 鉴权：在 `routes/jobs.py`、`routes/scheduler.py` 两端点的函数签名追加 `current_user: dict = Depends(get_current_user_from_header)`，不改变返回结构
- 分页修复：`Sprint.issues()` 内改为「模板常量 + 每轮拼 startAt/maxResults + 非 200 抛错」，避免 `jql` 被 `.format()` 原地覆盖
- 脱敏：复用 `util/qywx.py:_mask_key` 与 `util/errors.py` 的截断口径，不新写脱敏函数

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose: 在给 `routes/jobs.py`、`routes/scheduler.py` 补鉴权之前，全仓确认这两个路由的全部调用方（前端 `api/jobs.ts`、后端 `tests/api/*`、部署探针、脚本），避免加鉴权造成回归或误伤匿名端点
- Expected outcome: 输出「调用方清单 + 文件:行号 + 是否需同步改造/保持匿名」的结论，据此确定测试改造范围与必须保持匿名的端点（`/`、`/health`）

### Skill

- **lsp-code-analysis**
- Purpose: 精确查找 `projects.ts` / `reports.ts` 中重复符号（`reportsApi`、`BugListItem`、`ReopenBugItem`、`BugDetailResponse`）与 `getBugList` 的全部引用点，做影响面分析
- Expected outcome: 得到每个符号的真实引用清单（调用点文件与行号），据此安全删除死代码并把 `getBugList` 签名统一为后端真实顺序，确保不遗漏任何误用点