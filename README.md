# IterHub 迭代看板

基于 RDM(JIRA) 数据的迭代质量看板：Sprint 报表、故障分析、任务调度与企微提醒。

## 技术栈

| 端 | 技术 |
| --- | --- |
| 前端 | Vue 3 + TypeScript + Vite 5 + PrimeVue 4 + Tailwind 4 + ECharts 5 + Pinia |
| 后端 | Python 3.10+ + FastAPI + SQLAlchemy + APScheduler |
| 数据库 | MySQL 8（PyMySQL） |

## 目录结构

```
.
├── backend/            # 后端服务 (FastAPI, 默认端口 8000)
│   ├── scripts/run.py  # 启动脚本(跨平台)
│   ├── sql/            # 数据库初始化脚本
│   └── .env.example    # 环境变量示例
├── frontend/           # 前端 (Vite, dev 端口 3000)
├── docker-compose.yml        # 容器化部署(含 MySQL)
├── docker-compose-nodb.yml   # 容器化部署(复用外部 MySQL)
└── deployment.yml            # Kubernetes 部署
```

## 本地开发（非容器化，Windows / Linux / macOS 通用）

### 1. 前置依赖

- Python 3.10+（含 pip）
- Node.js 20+（含 npm）
- MySQL 8（本机或可访问的远程实例）

### 2. 后端

**安装依赖**（在 `backend/` 目录下，二选一）：

```bash
uv sync
# 或不用 uv：
pip install -e .
```

**配置环境变量**：创建 `backend/.env`（可复制 `.env.example` 修改）：

```ini
MSQL_DSN=mysql+pymysql://your_user:your_password@127.0.0.1:3306/iterdb
JWT_SECRET_KEY=please-replace-with-a-long-random-string-at-least-32-chars
PUSH_ENABLED=false
```

> 注意：
> - 数据库密码含 `@ : / #` 等特殊字符时需 URL 编码（如 `@` → `%40`）
> - host 写 `127.0.0.1` 别写 `localhost`：数据库在 WSL 时，`localhost` 会先试 IPv6 `::1`（WSL 转发不监听），超时 10 秒才回退，每次新建连接都白等 10 秒
> - `JWT_SECRET_KEY` 不设置会启动时自动生成（重启后旧 token 失效，仅适合开发）

**初始化数据库**（在 MySQL 中按顺序执行 `backend/sql/` 下的两个脚本）：

1. `init_db.sql`：建库 `iterdb`、创建库用户并授权
2. `init_ddl.sql`：建表（系统/配置、RDM 与文档导入数据、报表派生表、Sprint 屏蔽名单等）

> - 存量库升级**不要**重跑 `init_ddl.sql`。结构性变更的增量脚本统一放在 `backend/sql/migration/` 下，按文件名日期顺序执行（该目录为空表示当前没有待应用的增量）
> - 表结构的权威定义就是 `init_ddl.sql`；`iterdb.sql` / `iterdb-0915.sql` 是历史导出快照，仅作参考

**启动**：

```bash
cd backend
python scripts/run.py
```

启动后监听 `0.0.0.0:8000`，首次运行自动创建 admin 用户，日志写入 `backend/logs/app.log`。

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:3000`。dev 模式下 Vite 自动把 `/api` 代理到后端：

- 默认代理地址 `http://localhost:8000`（[vite.config.ts](frontend/vite.config.ts)）
- 后端不在本机时，在 `frontend/` 下创建 `.env.development` 覆盖：
  ```ini
  VITE_API_HOST=http://192.168.x.x:8000
  ```

### 4. 生产构建

```bash
cd frontend
npm run build        # vue-tsc 类型检查 + Vite 构建
```

构建产物在 `frontend/dist/`，由 Nginx 托管（见 Docker 部署，基路径为 `/iterhub/`）。

## Docker Compose 部署

```bash
# 部署(前端 8188, 后端 8008, 数据库为外部 MySQL, 连接地址见 compose 中 MSQL_DSN)
docker compose up -d --build

# 复用宿主机 MySQL(前端 8188, 后端 8008)
docker compose -f docker-compose-nodb.yml up -d --build
```

- 访问入口：`http://localhost:8188/iterhub/`
- 需调整数据库连接时，修改 compose 中后端服务的 `MSQL_DSN` 环境变量

## Kubernetes 部署

```bash
kubectl apply -f deployment.yml
kubectl rollout restart deployment iterhub   # 更新后强制重建 pod
```

- 访问入口：`http://<节点IP>:30801/iterhub/`（NodePort）
- 数据库地址在 `deployment.yml` 的 `MSQL_DSN` 环境变量中修改
- 更新 ConfigMap（nginx 配置）后需 `kubectl rollout restart` 生效

## 端口速查

| 场景 | 前端 | 后端 |
| --- | --- | --- |
| 本地开发 | 3000 | 8000 |
| docker-compose | 8188 (`/iterhub/`) | 8008 |
| docker-compose-nodb | 8188 (`/iterhub/`) | 8008 |
| Kubernetes NodePort | 30801 (`/iterhub/`) | 8000 |

## 部署后常见问题

- **页面行为像旧版本**：浏览器缓存了旧 JS，硬刷新（Ctrl+F5）或清缓存
- **Sprint 下拉为空**：后端日志提示 `HTTP 401` 时，为项目创建者的 JIRA Token 配置错误，在项目配置中修正 `jira_token`
- **JIRA Token 失效**：报表页实时拉取 RDM 数据，认证失败时后端 `backend/logs/app.log` 中会记录 `Jira` 日志

## 生成用户登录密码哈希

在首次部署或重置密码时，需为 admin 用户生成密码哈希值。

```bash
# 激活虚拟环境后，在 `backend/` 目录下执行：
python -c "import bcrypt; print(bcrypt.hashpw('你的新密码'.encode(), bcrypt.gensalt()).decode())"
```