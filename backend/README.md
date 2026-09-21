# 迭代看板服务

基于 FastAPI + APScheduler 的后端任务调度服务，支持项目管理配置API。

## 功能特性

- **任务调度**：自动调度任务（工作日 08:30 故事提醒，17:20 任务到期提醒）
- **项目管理**：提供 REST API 管理项目配置（支持每个项目单独配置JIRA账号）
- **用户认证**：JWT认证，管理员可管理所有项目，普通用户只能管理自己创建的项目
- **手动触发**：支持通过API手动触发任务

## 启动服务

```bash
# 安装依赖
pip install -e .

# 启动服务（默认 0.0.0.0:8000）
python scripts/run.py

# 或直接用 uvicorn
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## API 接口

### 认证相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录 |
| GET | `/api/auth/me` | 获取当前用户信息 |

> 自助注册接口已下线:账号只能由初始化/运维流程创建(初始口令取自 `ADMIN_PASSWORD` 环境变量)。

### 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 获取项目列表 |
| GET | `/api/projects/{id}` | 获取项目详情 |
| POST | `/api/projects` | 创建项目配置 |
| PUT | `/api/projects/{id}` | 更新项目配置 |
| DELETE | `/api/projects/{id}` | 删除项目配置 |

### 任务调度

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 获取所有任务状态 |
| POST | `/api/jobs/story-reminder/trigger` | 手动触发故事提醒 |
| POST | `/api/jobs/task-reminder/trigger` | 手动触发任务提醒 |
| POST | `/api/jobs/{job_id}/trigger` | 手动触发指定任务 |

### 健康检查

| 方法 | 路径 | 状态码 | 说明 |
|------|------|--------|------|
| GET | `/` | 200 | 进程基本信息 |
| GET | `/livez` | 200 | **存活探针**:只证明进程自身还活着,不碰任何外部依赖(livenessProbe 用) |
| GET | `/health` | 200 / 503 | **就绪探针**:DB ping + 调度器状态,任一不可用即 503(readinessProbe、Docker HEALTHCHECK 用) |

> ⚠ 两者分工不可互换:livenessProbe 指向 `/health` 会让 MySQL 抖动升级为容器反复重启;
> readinessProbe 指向 `/livez` 则会让库已挂掉的实例继续接流量。

## 环境变量

```bash
# 数据库配置
DB_HOST=10.39.52.58
DB_PORT=3306
DB_USER=zoomlion
DB_PASSWORD=xxx
DB_NAME=iterdb

# JWT配置
JWT_SECRET_KEY=your-secret-key-change-in-production
```

## 权限说明

- **管理员**：可查看、创建、更新、删除所有项目配置
- **普通用户**：只能查看、创建、更新、删除自己创建的项目配置

## 部署

可以使用 systemd 管理服务：

```ini
[Unit]
Description=Project Tools Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/iterhub/backend
ExecStart=/usr/bin/env python3 /path/to/iterhub/backend/scripts/run.py
Restart=always

[Install]
WantedBy=multi-user.target
```